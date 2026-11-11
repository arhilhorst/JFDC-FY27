"""Stage 7: notices to the student who submitted the bill (C1).

This cycle: a mail-merge CSV + .eml drafts that a person sends from the JFC mailbox.
Next cycle: the email bot sends the same queue. Each (bill, notice, ref) goes out once;
`ref` is the appeal id for appeal emails.
"""

from __future__ import annotations

import csv
import re
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
    "STRIKE_RENUMBERED": "Correction: Bill {bill_id} is now Strike {ordinal} for {rso} (was Strike {old_ordinal})",
    "INCOMPLETE_FIX": "Your Post-Event Recap for Bill {bill_id} is incomplete",
    "APPEAL_RECEIVED": "Appeal received: Bill {bill_id} ({rso})",
    "APPEAL_GRANTED": "Appeal granted: strike removed for {rso} (Bill {bill_id})",
    "APPEAL_DENIED": "Appeal decision: Bill {bill_id} ({rso})",
}
APPEAL_NOTICES = {"OPEN": "APPEAL_RECEIVED", "GRANTED": "APPEAL_GRANTED", "DENIED": "APPEAL_DENIED"}
NO_FORM_YET = ("reply to this email with your RSO, the bill number, why you believe the strike is a mistake, "
               "and any proof (the online Appeal Form is coming soon)")


_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


def recipient_problem(addr: str, allowed_domains: list[str]) -> str:
    """'' if `addr` is ONE plain address on an allowed domain; otherwise why it is held.
    Student-typed text ("a@gatech.edu, everyone@gatech.edu") must never become a recipient list."""
    a = (addr or "").strip()
    if not a:
        return "no email address"
    if not _ADDRESS.match(a):
        return f"not a single plain email address: {a!r}"
    if allowed_domains and a.lower().rsplit("@", 1)[1] not in {d.lower() for d in allowed_domains}:
        return f"{a} is not on an allowed domain ({', '.join(allowed_domains)})"
    return ""


def appeal_context(appeals_cfg: dict | None, today) -> dict:
    """Fields every strike email uses to explain how to appeal."""
    from datetime import timedelta
    cfg = appeals_cfg or {}
    days = int(cfg.get("window_days", 30))
    url = (cfg.get("form_url") or "").strip()
    return {"appeal_window_days": days,
            # The window runs from when the email is SENT, which is on or after today, so this printed
            # date is never later than the real deadline.
            "appeal_deadline": today + timedelta(days=days),
            "appeal_how": f"fill out the Strike Appeal Form: {url}" if url else NO_FORM_YET}


def build_queue(res: RunResult, already_sent: list[dict], due_soon_days: int,
                appeals_cfg: dict | None = None, allowed_domains: list[str] | None = None) -> pd.DataFrame:
    allowed = ["gatech.edu"] if allowed_domains is None else allowed_domains
    # Send-once key: (bill, notice, ref). `ref` is the appeal id for appeal emails, blank otherwise.
    sent = {(n["bill_id"], n["notice"], n.get("ref") or "") for n in already_sent}
    appeal_ctx = appeal_context(appeals_cfg, res.as_of.date())
    q = []
    req = res.requirements
    for r in req.to_dict("records") if len(req) else []:
        if not r["submitter_email"]:
            continue
        if r["status"] == "DUE":
            q.append((r, "REMINDER_DUE_SOON" if r["days_left"] <= due_soon_days else "REMINDER_OPEN"))
        elif r["status"] == "INCOMPLETE":
            q.append((r, "INCOMPLETE_FIX"))  # drafted; reviewer decides whether to send (C7)
    told = last_strike_number_sent(already_sent)
    stk = res.strikes
    for s in stk.to_dict("records") if len(stk) else []:
        hit = req[req["bill_id"] == s["bill_id"]] if len(req) else req
        r = hit.iloc[0].to_dict() if len(hit) else dict(s)  # BASIS_MISSING strikes have no requirement row
        if s["state"] == "confirmed" and s["ordinal"]:
            n = min(int(s["ordinal"]), 3)
            if not bool(s.get("supported", True)):
                continue  # basis in question (removal proposed / basis missing): review first, notify nothing new
            ctx = r | appeal_ctx | {"consequence": s["consequence"], "ordinal": n}
            prior = told.get(s["bill_id"])
            if prior is None:
                q.append((ctx, f"STRIKE_{n}"))
            elif prior != n:  # an earlier strike was removed: correct the number instead of a 2nd strike notice
                q.append((ctx | {"old_ordinal": prior}, "STRIKE_RENUMBERED"))
        elif s["state"] == "removed" and not s.get("via_appeal"):  # appeal grants get APPEAL_GRANTED instead
            q.append((r, "STRIKE_REMOVED"))

    # Appeals: to the student who filed it (falls back to the bill submitter).
    apps = getattr(res, "appeals", None)
    for a in apps.to_dict("records") if apps is not None and len(apps) else []:
        hit = req[req["bill_id"] == a["bill_id"]] if len(req) and a["bill_id"] else req.iloc[0:0]
        base = hit.iloc[0].to_dict() if len(hit) else {"bill_id": a["bill_id"], "rso": a["rso"], "title": ""}
        to = a["appellant_email"] or base.get("submitter_email", "")
        ctx = base | appeal_ctx | {
            "bill_id": a["bill_id"] or "(not given)", "rso": a["bill_rso"] or a["rso"], "_ref": a["appeal_id"],
            "submitter_email": to, "submitter_name": a["appellant_name"] or base.get("submitter_name", ""),
            "appeal_id": a["appeal_id"], "appeal_reason": a["reason"], "decision_reason": a["decision_reason"],
            "appeal_submitted_at": a["submitted_at"]}
        q.append((ctx, APPEAL_NOTICES[a["status"]]))

    rows = []
    for r, kind in q:
        ref = r.get("_ref", "")
        if kind != "STRIKE_RENUMBERED" and (r["bill_id"], kind, ref) in sent:
            continue
        to = str(r.get("submitter_email") or "").strip()
        if not to and kind not in APPEAL_NOTICES.values():
            continue  # no submitter on file (e.g. old bills): nothing to send, as before
        hold = recipient_problem(to, allowed)
        ctx = _Blank({k: ("" if v is None or (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()})
        body = (TEMPLATES / f"{kind}.txt").read_text().format_map(ctx)
        rows.append({"notice": kind, "bill_id": r["bill_id"], "rso": r["rso"], "to": "" if hold else to,
                     "hold_reason": hold,
                     "to_name": ctx["submitter_name"], "ordinal": ctx["ordinal"], "ref": ref,
                     "subject": SUBJECTS[kind].format_map(ctx), "body": body})
    return pd.DataFrame(rows, columns=QUEUE_COLUMNS)


QUEUE_COLUMNS = ["notice", "bill_id", "rso", "to", "hold_reason", "to_name", "ordinal", "ref", "subject", "body"]


class _Blank(dict):
    """Template context: a field the row doesn't have renders as blank instead of raising KeyError."""

    def __missing__(self, key):
        return ""


def last_strike_number_sent(already_sent: list[dict]) -> dict[str, int]:
    """bill_id -> the strike number the RSO was last told (from STRIKE_n and STRIKE_RENUMBERED notices)."""
    told: dict[str, int] = {}
    for n in already_sent:  # in send order
        kind = n.get("notice", "")
        if kind.startswith("STRIKE_") and kind[-1].isdigit():
            told[n["bill_id"]] = int(kind[-1])
        elif kind == "STRIKE_RENUMBERED" and str(n.get("ordinal") or "").strip().isdigit():
            told[n["bill_id"]] = int(str(n["ordinal"]).strip())
    return told


def write_notices(queue: pd.DataFrame, out_dir: Path, sender: str = "") -> None:
    from .report import csv_safe  # local import: report imports pipeline, notify is imported by cli only
    csv_safe(queue, keep=("notice", "bill_id", "ref", "ordinal", "to")).to_csv(
        out_dir / "notices.csv", index=False, quoting=csv.QUOTE_ALL)
    eml = out_dir / "eml"
    eml.mkdir(exist_ok=True)
    for i, n in enumerate(queue.to_dict("records"), start=1):
        if n.get("hold_reason"):
            continue  # listed in notices.csv with the reason; a person fixes the address first
        m = EmailMessage()
        m["To"] = n["to"]
        if sender:
            m["From"] = sender
        m["Subject"] = n["subject"]
        m["X-Unsent"] = "1"  # Outlook opens it as an unsent draft
        m.set_content(n["body"])
        (eml / f"{i:03d}_{n['notice']}_{n['bill_id']}.eml").write_bytes(bytes(m))
