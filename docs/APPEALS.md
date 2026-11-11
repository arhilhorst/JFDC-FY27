# Strike appeals (MVP)

An RSO that believes it was **flagged by mistake** can appeal a confirmed strike. Every appeal is reviewed
by hand. The engine only matches the appeal to its strike, works out the deadline, lists what to check, and
drafts the emails.

| Rule | Setting | Where |
|---|---|---|
| Who can appeal | Any RSO with a confirmed strike | |
| Window | **30 days** from when the strike email was sent (`jfdc mark-sent`) | `policy.yaml: appeals.window_days` |
| Late appeals | Still listed, marked `timely = False`, for the admin to decide | |
| Who decides | Anyone with the **admin** role | `ledger.py` |
| Does an open appeal pause the consequence? | **No** | Chair decision |
| Outcome | **Granted:** strike removed, standing recalculated, later strikes renumbered (with correction emails). **Denied:** strike stands. Both need a reason. | |

## Flow
1. The strike email (`templates/notices/STRIKE_n.txt`) includes a **How to appeal** section, the deadline, and the
   form link (`policy.yaml: appeals.form_url`). Until the form exists, the email tells the student to reply.
2. The student fills in the **Strike Appeal Form** (below).
3. Download its responses (Forms → Open in Excel) and ingest them with the other files:
   `jfdc ingest Strike_Appeal_Form.xlsx --by you@gatech.edu --as-of ...`
4. `jfdc run` adds an **Appeals** tab: each appeal, its strike, the deadline, `checks` (things to look at),
   and the exact command to decide it. Open appeals also show in **Needs Review**. An **Appeal received**
   email is drafted for each new appeal.
5. An admin decides:
   ```bash
   jfdc decide appeal_grant appeal_id=7 bill_id=381493 --reason "Recap was filed 9/18, on time" --actor chair@gatech.edu
   jfdc decide appeal_deny  appeal_id=8 bill_id=377345 --reason "No recap until 10/20; due 9/10" --actor chair@gatech.edu
   ```
6. The next `jfdc run` drafts **Appeal granted** / **Appeal denied** emails. Send them and run `jfdc mark-sent`.

An appeal that names several bills becomes one row per bill, each decided separately. Granting an appeal on a
bill with no confirmed strike changes nothing (the Appeals tab says so).

## The Strike Appeal Form (to build, PC-8)
Create it in the **JFDC Team** (a group form), so the file uploads aren't stored in one person's OneDrive, and
restrict it to Georgia Tech accounts. Use these question titles: the engine matches on the start of each title
(`config/sources/appeals.yaml`).

| # | Question title | Type | Required |
|---|---|---|---|
| 1 | **RSO name** | Text (as it appears on Engage) | Yes |
| 2 | **Bill number** | Text, 6 digits (one per appeal if possible) | Yes |
| 3 | **Your name** | Text | Yes |
| 4 | **Your GT email** | Text | Yes |
| 5 | **Reason for appeal** | Choice: Recap was submitted on time / Event was cancelled or funds were not used / Same event as another bill / Wrong event date / Data error / Other | Yes |
| 6 | **Explanation** | Long text | Yes |
| 7 | **Supporting evidence** | File upload | No |

When it's live, paste its link into `policy.yaml → appeals.form_url`, submit one test response, and check
that `jfdc ingest` recognizes the export. If a title is worded differently, edit `config/sources/appeals.yaml`.

## Emails (drafts to tweak)
`templates/notices/`: `STRIKE_1-3.txt` (appeal section), `APPEAL_RECEIVED.txt`, `APPEAL_GRANTED.txt`,
`APPEAL_DENIED.txt`. Edit the wording freely: `{field}` placeholders are filled in by the engine, and a field
that doesn't apply prints blank.
