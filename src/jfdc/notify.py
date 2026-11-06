"""Stage 7: notices to the student who submitted the bill (C1).

This cycle: a mail-merge CSV + .eml drafts that a person sends from the JFC mailbox.
Next cycle: the email bot sends the same queue. Each (bill, notice) goes out once.
"""

from __future__ import annotations

import csv
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from .config import REPO_ROOT
from .pipeline import RunResult

TEMPLATES = REPO_ROOT / "templates" / "notices"
SUBJECTS = {
    "REMINDER_OPEN": "Post-Event Recap due {due_date} - Bill {bill_id}",
    "REMINDER_DUE_SOON": "Reminder: Post-Event Recap due in {days_left} day(s) - Bill {bill_id}",
    "STRIKE_1": "SAF Policy 9.5.2 - Strike 1 for {rso} (Bill {bill_id})",
    "STRIKE_2": "SAF Policy 9.5.2 - Strike 2 for {rso} (Bill {bill_id})",
    "STRIKE_3": "SAF Policy 9.5.2 - Strike 3 for {rso} (Bill {bill_id})",
    "STRIKE_REMOVED": "Strike removed for {rso} (Bill {bill_id})",
    "INCOMPLETE_FIX": "Your Post-Event Recap for Bill {bill_id} is incomplete",
}


def build_queue(res: RunResult, already_sent: list[dict], due_soon_days: int) -> pd.DataFrame:
    sent = {(n["bill_id"], n["notice"]) for n in already_sent}
    q = []
    req = res.requirements
    for r in req.to_dict("records") if len(req) else []:
        if not r["submitter_email"]:
            continue
        if r["status"] == "DUE":
            q.append((r, "REMINDER_DUE_SOON" if r["days_left"] <= due_soon_days else "REMINDER_OPEN"))
        elif r["status"] == "INCOMPLETE":
            q.append((r, "INCOMPLETE_FIX"))  # drafted; reviewer decides whether to send (C7)
    stk = res.strikes
    for s in stk.to_dict("records") if len(stk) else []:
        r = req[req["bill_id"] == s["bill_id"]].iloc[0].to_dict()
        if s["state"] == "confirmed" and s["ordinal"]:
            q.append((r | {"consequence": s["consequence"]}, f"STRIKE_{min(int(s['ordinal']), 3)}"))
        elif s["state"] == "removed":
            q.append((r, "STRIKE_REMOVED"))
    rows = []
    for r, kind in q:
        if (r["bill_id"], kind) in sent:
            continue
        ctx = {k: ("" if v is None or (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()}
        ctx.setdefault("consequence", "")
        body = (TEMPLATES / f"{kind}.txt").read_text().format(**ctx)
        rows.append({"notice": kind, "bill_id": r["bill_id"], "rso": r["rso"], "to": r["submitter_email"],
                     "to_name": r["submitter_name"], "subject": SUBJECTS[kind].format(**ctx), "body": body})
    return pd.DataFrame(rows, columns=["notice", "bill_id", "rso", "to", "to_name", "subject", "body"])


def write_notices(queue: pd.DataFrame, out_dir: Path, sender: str = "") -> None:
    queue.to_csv(out_dir / "notices.csv", index=False, quoting=csv.QUOTE_ALL)
    eml = out_dir / "eml"
    eml.mkdir(exist_ok=True)
    for i, n in enumerate(queue.to_dict("records"), start=1):
        m = EmailMessage()
        m["To"] = n["to"]
        if sender:
            m["From"] = sender
        m["Subject"] = n["subject"]
        m["X-Unsent"] = "1"  # Outlook opens it as an unsent draft
        m.set_content(n["body"])
        (eml / f"{i:03d}_{n['notice']}_{n['bill_id']}.eml").write_bytes(bytes(m))
