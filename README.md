# JFDC Compliance Engine

Built for the Georgia Tech SGA Joint Finance Data Committee. It takes the spreadsheets Engage and the Post-Event Recap Form
produce, matches every funded event to its recap, and applies **SAF Policy §9.5**. The output is a daily
compliance report for the JVPF, a strike-confirmation sheet, and draft notices to bill submitters.

- **Design:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Running it each day:** [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- **Which rule does what:** [`docs/POLICY_MAPPING.md`](docs/POLICY_MAPPING.md)
- **Changes we're waiting on from Engage, the Form and the JFC sheet:** [`docs/PENDING_CHANGES.md`](docs/PENDING_CHANGES.md)

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
export JFDC_DATA_DIR="$HOME/OneDrive - Georgia Institute of Technology/JFDC/data"   # the synced SharePoint folder
jfdc init
jfdc ingest JFC_Data_Sheet.xlsx Post_Event_Recap_Form.xlsx --by you@gatech.edu --as-of 2026-11-06T09:00   # times are Eastern
jfdc run
```

## Collecting bill details: `campuslabs-scraper.js`

The browser-console scraper in this repo exports every bill on the Engage budgeting **Reviews** page,
with its Additional Information answers (event date, is-event, recap attestation), to
`CampusLabs_Budget_Requests_<date>.csv`. Ingest that CSV directly. It is the `bill_details` source,
the same format as the JFC Data Sheet tab. Rows the scraper marks in `Warnings`/`Error` are quarantined.
Usage: [`docs/SCRAPER.md`](docs/SCRAPER.md).

## How it's built

```
upload ─▶ ingest (validate, hash, store immutably) ─▶ consolidate ─▶ link recaps↔bills
       ─▶ evaluate (§9.5 status, proposed strikes, flags) ─▶ review gate (permissioned ledger)
       ─▶ report.xlsx + notice drafts ─▶ Chair approves ─▶ JVPF
```

| Path | What | Subteam |
|---|---|---|
| `campuslabs-scraper.js` | Browser scraper for bill details ([docs/SCRAPER.md](docs/SCRAPER.md)) | Data Collection |
| `src/jfdc/ingest/` | Readers for the Engage export, recap form, bill PDF/scraper and budget sheet | Data Collection |
| `src/jfdc/consolidate.py` | Current bills, bill history across exports, RSO name resolution | Data Collection |
| `src/jfdc/link.py` | Recap ↔ bill matching (exact, review, fallback) | Matching & Compliance |
| `src/jfdc/rules/` | §9.5 statuses, strikes and standing, flags | Matching & Compliance |
| `src/jfdc/ledger.py` | Permissioned, append-only decisions | Matching & Compliance |
| `src/jfdc/report.py`, `notify.py` | Workbook and notice drafts | Dashboard & Reporting |
| `config/` | Policy numbers and source column maps. **Change these, not the code.** | All |

## Ground rules

- **Never commit real data.** `.gitignore` blocks CSV, XLSX and PDF files. Tests use synthetic data only.
- **A false strike is worse than a missed one.** When the engine is unsure, the item goes to review.
- `python -m pytest` must pass before a PR merges. Each test in `tests/test_scenarios.py` covers one policy case.
