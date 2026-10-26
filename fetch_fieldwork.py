#!/usr/bin/env python3
"""Fetch recent FDEP field work notifications and write docs/data/fieldwork.json.

The FDEP search is a form POST plus a cookie-backed CSV export, so this cannot
run in a browser — it runs on a schedule in GitHub Actions and commits the
result, which the static map then reads.

A note on dates: a field work notification's "document date" is the day the
notice was filed with FDEP, and notices are filed on or just before the work
happens. Asking for a window that starts today always returns nothing, so the
default here is a rolling look-back window. The map therefore shows notices
filed recently — i.e. the fieldwork that is about to happen.

Usage:
    python3 fetch_fieldwork.py                    # last 14 days .. today
    python3 fetch_fieldwork.py --days-back 30
    python3 fetch_fieldwork.py --from 2026-01-01 --to 2026-02-01
"""
import argparse
import csv
import datetime as dt
import io
import json
import sys
import time
import urllib.parse

import requests

SEARCH_URL = "https://prodenv.dep.state.fl.us/DepNexus/public/electronic-documents"
EXPORT_URL = ("https://prodenv.dep.state.fl.us/DepNexus/public/"
              "export!exportElectronicDocuments?wildCardMatch=true")
DWM_LAYER = "https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/DWM_STCM/MapServer/1/query"
ERIC_LAYER = "https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/CLEANUP_SP/MapServer/8/query"

USER_AGENT = "fieldwork-map/1.0 (+https://github.com/namoran/Upcoming-Fieldwork-Map)"
BATCH = 100          # facility IDs per ArcGIS request
PAUSE = 0.5          # seconds between ArcGIS requests, to stay polite


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", help="YYYY-MM-DD (default: today - days-back)")
    ap.add_argument("--to", dest="date_to", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--days-back", type=int, default=14,
                    help="how many days of filings to look back (default 14)")
    ap.add_argument("--out", default="docs/data/fieldwork.json")
    return ap.parse_args()


def search(session, date_from, date_to):
    """Run the DepNexus search, then pull its CSV export.

    Returns [] for an empty result set. That case needs handling: the export
    endpoint does not return an empty CSV, it blows up with a Java stack trace
    and an HTML error page, so we have to notice the empty search result first.
    """
    payload = {
        "__checkbox_electronicDocument.airDivision": "true",
        "__checkbox_electronicDocument.waterDivision": "true",
        "__checkbox_electronicDocument.wasteDivision": "true",
        "electronicDocument.documentType": "FIELD WORK NOTIFICATION",
        "electronicDocument.dateFrom": date_from.strftime("%m/%d/%Y"),
        "electronicDocument.dateTo": date_to.strftime("%m/%d/%Y"),
        "electronicDocument.dateReceivedFrom": "",
        "electronicDocument.dateReceivedTo": "",
        "electronicDocument.subject": "",
        "electronicDocument.facilityId": "",
        "electronicDocument.permitId": "",
        "electronicDocument.facilityDistrict": "",
        "electronicDocument.facilityCounty": "",
        "newSearch": "Yes",
        "electronicDocument.sortCriteria": "",
    }
    resp = session.post(SEARCH_URL, data=payload, timeout=90)
    resp.raise_for_status()
    if "no documents that meet your criteria" in resp.text.lower():
        return []

    export = session.get(EXPORT_URL, timeout=120)
    export.raise_for_status()
    if "csv" not in export.headers.get("content-type", "") and not export.text.startswith("FACILITY"):
        raise SystemExit(
            "FDEP returned something that isn't the CSV export (got %s, %d bytes).\n"
            "The DepNexus form or export URL probably changed - fix search() in fetch_fieldwork.py."
            % (export.headers.get("content-type"), len(export.text))
        )

    rows = list(csv.reader(io.StringIO(export.text)))
    if not rows:
        raise SystemExit("FDEP returned an empty CSV")
    header = rows[0]
    return [dict(zip(header, r)) for r in rows[1:] if len(r) == len(header)]


def iso_date(value):
    """FDEP writes dates as MM-DD-YYYY."""
    try:
        return dt.datetime.strptime(value.strip(), "%m-%d-%Y").date().isoformat()
    except (ValueError, AttributeError):
        return value.strip()


def collect_documents(rows):
    """Group documents per facility, dropping the per-document file noise.

    FDEP attaches the same notice several times (one file per attachment), so
    the same subject+date shows up repeatedly. Collapse those into one entry and
    keep the first link.
    """
    facilities = {}
    for row in rows:
        fid = row.get("FACILITY/SITE ID", "").strip()
        if not fid:
            continue
        fac = facilities.setdefault(fid, {
            "id": fid,
            "name": row.get("FACILITY/SITE NAME", "").strip(),
            "address": row.get("FACILITY/SITE ADDRESS", "").strip(),
            "city": row.get("CITY", "").strip(),
            "county": row.get("COUNTY", "").strip(),
            "documents": [],
        })
        doc = {
            "date": iso_date(row.get("DOCUMENT DATE", "")),
            "subject": row.get("SUBJECT", "").strip(),
            "link": row.get("FILE PATH", "").strip(),
        }
        seen = {(d["date"], d["subject"]): d for d in fac["documents"]}
        existing = seen.get((doc["date"], doc["subject"]))
        if existing is None:
            fac["documents"].append(doc)
        elif not existing["link"]:
            existing["link"] = doc["link"]
    for fac in facilities.values():
        fac["documents"].sort(key=lambda d: (d["date"], d["subject"]), reverse=True)
    return facilities


def look_up_coordinates(session, ids):
    """Batch geocode facility IDs. ERIC-* ids live in a different layer."""
    numeric = [i for i in ids if i.isdigit()]
    eric = [i for i in ids if not i.isdigit()]
    found = {}

    def query(url, where, key):
        resp = session.get(url, params={
            "where": where,
            "outFields": key,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        }, timeout=90)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise SystemExit("ArcGIS error: %s" % body["error"])
        for feature in body.get("features", []):
            geom = feature.get("geometry") or {}
            if "x" in geom and "y" in geom:
                found[str(feature["attributes"][key])] = (round(geom["y"], 6), round(geom["x"], 6))
        time.sleep(PAUSE)

    for start in range(0, len(numeric), BATCH):
        chunk = numeric[start:start + BATCH]
        query(DWM_LAYER, "FACILITY_ID IN (%s)" % ",".join(chunk), "FACILITY_ID")
        print("  geocoded %d/%d" % (min(start + BATCH, len(numeric)), len(numeric)))

    for start in range(0, len(eric), BATCH):
        chunk = eric[start:start + BATCH]
        quoted = ",".join("'%s'" % i.replace("'", "''") for i in chunk)
        query(ERIC_LAYER, "ERIC_ID IN (%s)" % quoted, "ERIC_ID")
        print("  geocoded %d/%d (ERIC)" % (min(start + BATCH, len(eric)), len(eric)))

    return found


def main():
    args = parse_args()
    today = dt.date.today()
    date_to = dt.date.fromisoformat(args.date_to) if args.date_to else today
    date_from = (dt.date.fromisoformat(args.date_from) if args.date_from
                 else date_to - dt.timedelta(days=args.days_back))

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print("searching %s .. %s" % (date_from, date_to))
    rows = search(session, date_from, date_to)
    print("  %d documents" % len(rows))

    facilities = collect_documents(rows)
    print("  %d facilities" % len(facilities))

    coords = look_up_coordinates(session, list(facilities)) if facilities else {}
    placed, missing = [], []
    for fac in facilities.values():
        point = coords.get(fac["id"])
        if point:
            fac["lat"], fac["lon"] = point
            placed.append(fac)
        else:
            missing.append(fac)

    placed.sort(key=lambda f: (f["county"], f["name"]))
    by_county = {}
    for fac in placed:
        by_county[fac["county"]] = by_county.get(fac["county"], 0) + 1

    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "window": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "facility_count": len(placed),
        "document_count": sum(len(f["documents"]) for f in placed),
        "missing_coordinates": len(missing),
        "by_county": dict(sorted(by_county.items(), key=lambda kv: -kv[1])),
        "facilities": placed,
    }

    out = __import__("pathlib").Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1) + "\n")
    print("wrote %s: %d facilities, %d documents, %d without coordinates"
          % (out, len(placed), payload["document_count"], len(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
