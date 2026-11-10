# Daily runbook (this dev cycle: manual pulls and uploads)

Any JFDC member (an `operator`) can do steps 1–4. Step 5 needs the `reviewer` or `admin` role, and strike
decisions also need a `confirmer`'s sign-off.

## 0. One-time setup
1. Install: see the README quickstart.
2. Set `JFDC_DATA_DIR` to the committee's **SharePoint-synced** data folder. Only the Chair and the Matching
   lead have write access to `roles.yaml` and `ledger/` in that folder.
3. The Chair copies `config/roles.example.yaml` to `<data dir>/roles.yaml` and fills in GT emails.

### OneDrive / SharePoint sync conflicts
If two people write to the data folder at once, OneDrive can create a conflict copy such as
`ledger/decisions-LAPTOP.jsonl` or `manifest (1).jsonl`. `jfdc` then **refuses** to ingest, decide, mark notices sent or run
(exit code 3), because the copy may hold decisions the real file doesn't. To fix it, append the copy's lines to the
real file, dropping lines that already appear there, then delete the copy. Keep the data folder set to **"Always keep on this device"**.

## 1. Pull the data
| What | Where | Cadence |
|---|---|---|
| **JFC Data Sheet** (the whole `.xlsx`) | Walker's sheet, updated Mon/Tue and Wed/Thu | After each update. One upload covers three sources: `Data Pasting Site` (Engage export), `CampusLabs_Budget_Requests` (scraper output with event dates) and `FY27 Final Budgets`. Other tabs are skipped. |
| Recap Form responses | Microsoft Forms → Open in Excel → download | **Every run** (a run is blocked if this file is more than 24 h old) |
| Bill PDF (optional) | Bill page → **PDF** button | Only for a bill missing from the scraper tab |

All times are **Eastern** (Engage, Forms and `--as-of`).

## 2. Ingest
```bash
jfdc ingest <files...> --by you@gatech.edu --as-of 2026-11-06T09:00
```
`--as-of` is **when you pulled the data**, not when you're uploading it. Read every warning. Two in particular:
- *"Newest record … days before its as-of"*: you probably downloaded an old file.
- *"close to Engage's ~65k export cap"*: the export may be truncated.

The same file uploaded twice is skipped automatically. A file with renamed columns is rejected, and the
message says which column is missing.

## 3. Run
```bash
jfdc run
```
This writes `runs/<id>/JFDC_Compliance_Report_<date>.xlsx`, `notices.csv` and `eml/` drafts.

## 4. Check the report
- **Summary:** confirm every input's "as of" date is what you expect.
- **Needs Review:** each row comes with a suggested `jfdc decide …` command.
- **Data Quality / No Event Date:** problems in the inputs.

## 5. Review gate (reviewer / admin)
```bash
jfdc decide link_confirm recap_id=96 bill_id=378001 --actor lead@gatech.edu
jfdc decide alias_add alias="GWiE" rso="Graduate Women in Engineering" --actor lead@gatech.edu
jfdc decide event_date_override bill_id=381493 event_date=2026-09-24 --reason "RSO typed 2006" --actor lead@gatech.edu
jfdc decide exemption bill_id=... --reason "event cancelled, SOFO confirmed" --actor lead@gatech.edu
```
Then send the **Strike Confirmation** sheet to Walker or JFC. When it comes back filled in:
```bash
jfdc import-confirmations returned_report.xlsx --actor lead@gatech.edu
jfdc run
```

## 6. Send
1. The Chair reviews the workbook (charter requirement) and sends it to the JVPF.
2. Send the notice drafts from the JFC mailbox: open each `.eml` in Outlook, or mail-merge `notices.csv`.
3. Record what was sent, so nothing goes out twice:
```bash
jfdc mark-sent <run_id> --actor you@gatech.edu
```
