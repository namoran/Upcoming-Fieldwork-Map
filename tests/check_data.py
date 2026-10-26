#!/usr/bin/env python3
"""Sanity-check docs/data/fieldwork.json before it gets committed.

The fetcher already fails loudly if FDEP changes, but a run can still produce
plausible-looking rubbish (everything geocoded to 0,0, counts that don't add
up). This catches that before the map is published.

    python3 tests/check_data.py [path-to-json]
"""
import datetime as dt
import json
import pathlib
import sys

# Rough bounding box for Florida, generous enough not to trip on the Keys or
# the panhandle.
LAT_RANGE = (24.0, 31.5)
LON_RANGE = (-88.0, -79.5)

REQUIRED_KEYS = {
    "generated", "window", "facility_count", "document_count",
    "missing_coordinates", "by_county", "facilities",
}


def fail(problems):
    for p in problems:
        print("  - " + p, file=sys.stderr)
    print("%d problem(s) in the data file" % len(problems), file=sys.stderr)
    return 1


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/data/fieldwork.json")
    data = json.loads(path.read_text())
    problems = []

    missing = REQUIRED_KEYS - set(data)
    if missing:
        problems.append("missing keys: %s" % ", ".join(sorted(missing)))
    if problems:
        return fail(problems)

    try:
        dt.datetime.fromisoformat(data["generated"])
    except ValueError:
        problems.append("generated is not an ISO timestamp: %r" % data["generated"])

    window = data["window"]
    try:
        start = dt.date.fromisoformat(window["from"])
        end = dt.date.fromisoformat(window["to"])
        if start > end:
            problems.append("window starts after it ends: %s" % window)
    except (KeyError, TypeError, ValueError):
        problems.append("window is not {from,to} ISO dates: %r" % (window,))

    facilities = data["facilities"]
    if data["facility_count"] != len(facilities):
        problems.append("facility_count is %d but there are %d facilities"
                        % (data["facility_count"], len(facilities)))

    documents = 0
    counties = {}
    for fac in facilities:
        label = fac.get("id") or "<no id>"
        for key in ("id", "name", "county", "documents"):
            if key not in fac:
                problems.append("%s: missing %s" % (label, key))
        if not fac.get("documents"):
            problems.append("%s: no documents" % label)

        lat, lon = fac.get("lat"), fac.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            problems.append("%s: no coordinates" % label)
        elif not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            problems.append("%s: coordinates look wrong (%.4f, %.4f)" % (label, lat, lon))

        documents += len(fac.get("documents", []))
        counties[fac.get("county", "")] = counties.get(fac.get("county", ""), 0) + 1

        for doc in fac.get("documents", []):
            try:
                dt.date.fromisoformat(doc.get("date", ""))
            except ValueError:
                problems.append("%s: document date is not ISO: %r" % (label, doc.get("date")))

    if data["document_count"] != documents:
        problems.append("document_count is %d but the facilities list %d"
                        % (data["document_count"], documents))

    if data["by_county"] != counties:
        problems.append("by_county does not match the facilities")

    if not facilities:
        problems.append("no facilities — did the search come back empty?")

    if problems:
        return fail(problems)

    print("ok: %d facilities, %d notices, %d counties, window %s..%s"
          % (len(facilities), documents, len(counties), window["from"], window["to"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
