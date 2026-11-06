"""`jfdc` command line. Run `jfdc --help`."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import load_config
from .ingest.detect import IngestError
from .ingest.service import ingest_file
from .ledger import PermissionDenied, record_decision
from .notify import build_queue, write_notices
from .pipeline import StaleDataError, run_pipeline
from .report import write_run
from .workspace import Workspace, default_data_dir


def _ws(args) -> Workspace:
    return Workspace(Path(args.data_dir) if args.data_dir else default_data_dir())


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def cmd_init(args):
    ws = _ws(args)
    ws.init()
    print(f"Initialized JFDC data directory at {ws.root}")
    if not (ws.root / "roles.yaml").exists():
        print("Next: copy config/roles.example.yaml to roles.yaml in that folder and fill in GT emails.")


def cmd_ingest(args):
    ws = _ws(args)
    ws.require_initialized()
    cfg = load_config(ws.root)
    rc = 0
    for f in args.files:
        try:
            results = ingest_file(ws, cfg, Path(f), by=args.by, source=args.source, as_of=_dt(args.as_of))
        except IngestError as e:
            print(f"REJECTED {f}: {e}", file=sys.stderr)
            rc = 1
            continue
        for res in results:
            tab = f" [{res.sheet}]" if res.sheet else ""
            if res.duplicate_of:
                print(f"SKIPPED  {Path(f).name}{tab}: {res.warnings[0]}")
                continue
            u = res.upload
            print(f"OK       {Path(f).name}{tab} -> {u.upload_id} ({u.source}) {u.rows_ok} rows, "
                  f"{u.rows_quarantined} quarantined, as of {u.as_of}")
            for w in res.warnings:
                print(f"  warning: {w}")
            for i in res.issues[:10]:
                print(f"  row {i['row']}: {i['code']} {i['message']}")
    return rc


def cmd_status(args):
    ws = _ws(args)
    ws.require_initialized()
    ups = ws.uploads()
    if not ups:
        print("No uploads yet.")
        return
    df = pd.DataFrame([u.__dict__ for u in ups])[["upload_id", "source", "as_of", "newest_record", "rows_ok",
                                                   "rows_quarantined", "uploaded_by", "original_name"]]
    print(df.to_string(index=False))


def cmd_run(args):
    ws = _ws(args)
    ws.require_initialized()
    cfg = load_config(ws.root)
    try:
        res = run_pipeline(ws, cfg, as_of=_dt(args.as_of), allow_stale=args.allow_stale)
    except StaleDataError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    out = write_run(res, ws.runs_dir)
    queue = build_queue(res, ws.notices_sent(), cfg.policy["recap"]["due_soon_days"])
    write_notices(queue, out)
    req = res.requirements
    print(f"Run {out.name}  as of {res.as_of:%Y-%m-%d %H:%M}  FY{res.fy}  {res.watermark}")
    if len(req):
        print(req.groupby(["class", "status"]).size().to_string())
    print(f"Strikes awaiting confirmation: {int((res.strikes['state'] == 'proposed').sum()) if len(res.strikes) else 0}")
    print(f"Review items: {len(res.review)}   Flags: {len(res.flags)}   Notices drafted: {len(queue)}")
    for w in res.warnings:
        print(f"warning: {w}")
    print(f"Report: {out}")


def cmd_decide(args):
    ws = _ws(args)
    cfg = load_config(ws.root)
    payload = dict(kv.split("=", 1) for kv in args.fields)
    try:
        e = record_decision(ws, cfg, args.type, args.actor, args.reason or "", **payload)
    except (PermissionDenied, ValueError) as err:
        print(f"DENIED: {err}", file=sys.stderr)
        return 1
    print(f"Recorded {e['type']} {e['id']}")


def cmd_import_confirmations(args):
    """Read the filled-in 'Strike Confirmation' sheet Walker/JFC returned."""
    ws = _ws(args)
    cfg = load_config(ws.root)
    df = pd.read_excel(args.workbook, sheet_name="Strike Confirmation", dtype=str).fillna("")
    action_col = next(c for c in df.columns if c.startswith("Action"))
    by_col = next(c for c in df.columns if c.startswith("Confirmed by"))
    kinds = {"confirm": "strike_confirm", "waive": "strike_waive", "remove": "strike_remove"}
    n, rc = 0, 0
    for r in df.to_dict("records"):
        act = r[action_col].strip().lower()
        if not act:
            continue
        if act not in kinds:
            print(f"Bill {r['bill_id']}: unknown action {r[action_col]!r}", file=sys.stderr)
            rc = 1
            continue
        try:
            record_decision(ws, cfg, kinds[act], args.actor, r.get("Reason", ""), bill_id=r["bill_id"],
                            confirmed_by=r[by_col], source=Path(args.workbook).name)
            n += 1
        except (PermissionDenied, ValueError) as err:
            print(f"Bill {r['bill_id']}: DENIED {err}", file=sys.stderr)
            rc = 1
    print(f"Recorded {n} strike decisions.")
    return rc


def cmd_mark_sent(args):
    ws = _ws(args)
    run = ws.runs_dir / args.run_id
    q = pd.read_csv(run / "notices.csv", dtype=str)
    if args.only:
        q = q[q["bill_id"].isin(args.only)]
    for n in q.to_dict("records"):
        ws.mark_notice_sent({"bill_id": n["bill_id"], "notice": n["notice"], "to": n["to"], "run_id": args.run_id,
                             "sent_by": args.actor, "sent_at": datetime.now().isoformat(timespec="seconds")})
    print(f"Marked {len(q)} notices sent.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="jfdc", description="JFDC SAF compliance engine")
    p.add_argument("--data-dir", help="data directory (default: $JFDC_DATA_DIR or ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the data directory").set_defaults(fn=cmd_init)

    s = sub.add_parser("ingest", help="validate and store uploaded files")
    s.add_argument("files", nargs="+")
    s.add_argument("--by", required=True, help="your GT email")
    s.add_argument("--as-of", help="when the data was pulled from its source (ISO, default now)")
    s.add_argument("--source", help="force source type (normally detected from headers)")
    s.set_defaults(fn=cmd_ingest)

    sub.add_parser("status", help="list uploads").set_defaults(fn=cmd_status)

    s = sub.add_parser("run", help="build the compliance report")
    s.add_argument("--as-of", help="evaluate as of this time (default now)")
    s.add_argument("--allow-stale", action="store_true", help="produce a watermarked DRAFT despite stale recap data")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("decide", help="record a decision in the ledger (permission-checked)")
    s.add_argument("type")
    s.add_argument("fields", nargs="*", help="key=value pairs, e.g. recap_id=12 bill_id=376435")
    s.add_argument("--actor", required=True)
    s.add_argument("--reason")
    s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("import-confirmations", help="load a filled-in Strike Confirmation sheet")
    s.add_argument("workbook")
    s.add_argument("--actor", required=True)
    s.set_defaults(fn=cmd_import_confirmations)

    s = sub.add_parser("mark-sent", help="record that a run's notices were sent")
    s.add_argument("run_id")
    s.add_argument("--actor", required=True)
    s.add_argument("--only", nargs="*", help="only these bill IDs")
    s.set_defaults(fn=cmd_mark_sent)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
