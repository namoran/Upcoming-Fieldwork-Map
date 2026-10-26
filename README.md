# Upcoming Fieldwork Map

A map of environmental fieldwork around Florida — the field work notifications
filed with the Florida Department of Environmental Protection, located on a map
and grouped by county.

**Live at <https://namoran.github.io/Upcoming-Fieldwork-Map/>**

## How it fits together

The FDEP search is a form POST backed by a session cookie, and its CSV export
sends no CORS headers, so a browser cannot call it directly. The map is
therefore two pieces:

```
fetch_fieldwork.py  →  docs/data/fieldwork.json  →  docs/index.html
   (GitHub Actions)         (committed)              (static Leaflet page)
```

`fetch_fieldwork.py` runs daily in GitHub Actions (`.github/workflows/fieldwork.yml`),
geocodes each facility through the FDEP ArcGIS services, and commits the JSON.
The page is plain HTML and JavaScript with a vendored copy of Leaflet, so it
loads in well under a second and needs no build step.

## A note on dates

A notification's "document date" is the day it was **filed** with FDEP, not the
day the fieldwork happens. Filings are made on or shortly before the work, and
never run into the future — asking FDEP for next month legitimately returns
nothing. The fetcher therefore uses a rolling look-back window (14 days by
default), which is the practical way to see what is about to happen.

Asking for a future-only window is also the one way to make the export endpoint
fail: it does not return an empty CSV, it throws a Java stack trace and an HTML
error page. The fetcher checks the search page for "no documents that meet your
criteria" before calling the export for that reason.

## Running it yourself

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_fieldwork.py                 # last 14 days
.venv/bin/python fetch_fieldwork.py --days-back 30
.venv/bin/python fetch_fieldwork.py --from 2026-01-01 --to 2026-02-01
```

Then serve `docs/` over HTTP (the page fetches the JSON, so `file://` will not
work):

```sh
cd docs && python3 -m http.server 8000
```

To refresh the data without waiting for the cron job, run it from the Actions
tab (`Update fieldwork data` → *Run workflow*).

## The data file

`docs/data/fieldwork.json`:

```jsonc
{
  "generated": "2026-10-26T18:15:09+00:00",
  "window": { "from": "2026-10-12", "to": "2026-10-26" },
  "facility_count": 337,
  "document_count": 631,
  "missing_coordinates": 0,
  "by_county": { "DUVAL": 45, "HILLSBOROUGH": 18 },
  "facilities": [
    {
      "id": "8735816", "name": "BOSTON F E", "address": "14026 NW 294TH AVE",
      "city": "ALACHUA", "county": "ALACHUA", "lat": 29.926215, "lon": -82.494346,
      "documents": [
        { "date": "2026-10-23", "subject": "PRP SUBMISSION CONFIRMATION",
          "link": "https://prodenv.dep.state.fl.us/DepStaging/api/dms/11.5245644.1" }
      ]
    }
  ]
}
```

Repeated attachments of the same notice are collapsed to one entry.

`tests/check_data.py` validates the file before the workflow commits it.

## Page features

- circle markers sized by number of notices per facility
- popup per facility listing each notice with a link to the PDF/file
- county ranking in the sidebar; click one to zoom, click again to reset
- search across facility name, address, city, county and ID

`get_fieldworknotices_website_version.py` is the original Windows console
script, kept for reference. It prompts for dates, writes
`DocumentSearchResults.csv`, and opens the result in Excel.

## Deploying

GitHub Pages serves `docs/` from `main`. There is no build step — commit and
push.
