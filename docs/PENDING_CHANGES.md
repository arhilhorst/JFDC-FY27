# Pending changes outside this repo

Changes the engine depends on that someone has to make in **Engage, the Microsoft Form or the JFC
data sheet**. The code has a fallback for each one until it lands. Remove an item once it ships.

| ID | Change | Owner | Status | What the engine does until then |
|---|---|---|---|---|
| **PC-1** | Add a required question to the Post-Event Recap Form: **"Did you use the SAF funds for this event?"** (Yes / No, event cancelled / No, funds not needed) | Chair → JVPF | Requested week of 2026-11-09 | Treats every approved bill as funds used. Funds-not-used cases are entered by a reviewer as a `funds_not_used` decision. |
| **PC-2** | Add a required question: **"Did you track attendance?"** (Yes / No) | Chair → JVPF | Requested week of 2026-11-09 | No `NOT_TRACKED` status. A recap with no attendee count goes to `INCOMPLETE` (review). |
| **PC-3** | Make the bill-number field validate to digits and commas only (Forms "number" or regex rule), or split it into "Engage bill numbers" and "Budget IDs" | JVPF | Proposed | Pattern extraction plus the review queue (47 of 150 real responses were free-form) |
| **PC-4** | Change the Form's event-date question to a **date picker** (start and end date) and make location its own question | JVPF | Proposed | Free-text date parser. Implausible dates go to review. |
| **PC-5** | A tab listing **Annual Budget events**: the 5-digit budget IDs RSOs write on recaps (26909–28681 seen), with RSO and event date. **Not in the 11/05 JFC Data Sheet**: `FY27 Final Budgets` only has per-RSO totals. | Data Collection / JVPF | Needed (B2/B3) | 5-digit IDs on recaps are listed as `budget_ref` and not checked |
| **PC-6** | Keep **every** bill's row in `CampusLabs_Budget_Requests`. The tab only holds the current review queue (40 bills on 11/05), so approved bills drop off. The engine keeps every row from every upload, so uploading after each sheet update builds the full history going forward. The ~520 bills approved before 11/05 still need a one-time back-fill. | Data Collection | Needed | Bills with no details and no recap show as `NO_EVENT_DATE` and are never struck. |
| **PC-7** | In the scraper tab, keep Q8 (event date) as **text**. Excel converts `11/18/26` into the serial `46344`. | Data Collection | Nice to have | Serials are converted back to dates |

When PC-1 and PC-2 ship, update the question text in `config/sources/recap_form.yaml` →
`optional_columns` if the wording differs. Ingest stops warning once it finds the columns.
