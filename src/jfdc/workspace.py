"""The data directory: raw uploads, upload manifest, decision ledger, run outputs.

Layout (point JFDC_DATA_DIR at a SharePoint-synced folder in production):

    <data>/roles.yaml                 who may write decisions (admin-only folder)
    <data>/raw/<source>/<file>        uploads, exactly as received, canonically named
    <data>/manifest.jsonl             one line per accepted upload
    <data>/ledger/decisions.jsonl     append-only human decisions
    <data>/notices_sent.jsonl         send-once log for notices
    <data>/runs/<run_id>/...          report.xlsx, notices.csv, eml/, run.json

Everything under runs/ is derived and can be deleted; raw/, manifest, ledger and
notices_sent are the system of record.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


def default_data_dir() -> Path:
    return Path(os.environ.get("JFDC_DATA_DIR", "data")).resolve()


@dataclass
class Upload:
    upload_id: str
    source: str
    original_name: str
    stored_path: str  # relative to data dir
    sha256: str
    as_of: str  # ISO datetime: when the data was pulled from its source
    uploaded_at: str
    uploaded_by: str
    rows_ok: int
    rows_quarantined: int
    newest_record: str | None = None
    notes: str = ""
    sheet: str | None = None  # workbook tab, for multi-source workbooks like the JFC Data Sheet

    @property
    def as_of_dt(self) -> datetime:
        return datetime.fromisoformat(self.as_of)


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------ layout
    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger" / "decisions.jsonl"

    @property
    def notices_path(self) -> Path:
        return self.root / "notices_sent.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def init(self) -> None:
        for d in ("raw", "ledger", "runs"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for f in (self.manifest_path, self.ledger_path, self.notices_path):
            f.touch(exist_ok=True)

    def require_initialized(self) -> None:
        if not self.manifest_path.exists():
            raise SystemExit(f"No JFDC data directory at {self.root}. Run `jfdc init` first.")

    # ------------------------------------------------------------ manifest
    def uploads(self, source: str | None = None) -> list[Upload]:
        out = [Upload(**r) for r in _read_jsonl(self.manifest_path)]
        return [u for u in out if source is None or u.source == source]

    def find_by_hash(self, sha: str, sheet: str | None = None) -> Upload | None:
        return next((u for u in self.uploads() if u.sha256 == sha and u.sheet == sheet), None)

    def store_upload(self, src: Path, source: str, as_of: datetime, by: str, rows_ok: int,
                     rows_quarantined: int, newest_record: str | None, notes: str = "",
                     sheet: str | None = None) -> Upload:
        sha = sha256_file(src)
        n = len(self.uploads(source)) + 1
        stamp = as_of.strftime("%Y-%m-%d_%H%M")
        name = f"{source}_{stamp}_{n:04d}{src.suffix.lower()}"
        dest = self.root / "raw" / source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        os.chmod(dest, 0o444)  # raw files are immutable
        up = Upload(
            upload_id=f"{source}-{n:04d}",
            source=source,
            original_name=src.name,
            stored_path=str(dest.relative_to(self.root)),
            sha256=sha,
            as_of=as_of.isoformat(timespec="seconds"),
            uploaded_at=datetime.now().isoformat(timespec="seconds"),
            uploaded_by=by,
            rows_ok=rows_ok,
            rows_quarantined=rows_quarantined,
            newest_record=newest_record,
            notes=notes,
            sheet=sheet,
        )
        _append_jsonl(self.manifest_path, asdict(up))
        return up

    def path_of(self, up: Upload) -> Path:
        return self.root / up.stored_path

    # ------------------------------------------------------------ ledger
    def decisions(self) -> list[dict]:
        return _read_jsonl(self.ledger_path)

    def append_decision(self, entry: dict) -> None:
        _append_jsonl(self.ledger_path, entry)

    # ------------------------------------------------------------ notices
    def notices_sent(self) -> list[dict]:
        return _read_jsonl(self.notices_path)

    def mark_notice_sent(self, entry: dict) -> None:
        _append_jsonl(self.notices_path, entry)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _append_jsonl(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")
