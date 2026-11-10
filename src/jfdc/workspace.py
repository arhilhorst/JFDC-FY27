"""The data directory: raw uploads, upload manifest, decision ledger, run outputs.

Layout (point JFDC_DATA_DIR at a SharePoint-synced folder in production):

    <data>/roles.yaml                 who may write decisions (admin-only folder)
    <data>/raw/<source>/<file>        uploads, exactly as received, canonically named
    <data>/manifest/<entry>.json      one file per accepted upload
    <data>/ledger/decisions/<entry>.json   one file per human decision (append-only)
    <data>/notices_sent/<entry>.json  send-once log for notices
    <data>/runs/<run_id>/...          report.xlsx, notices.csv, eml/, run.json

Everything under runs/ is derived and can be deleted; raw/, manifest, ledger and
notices_sent are the system of record.

Why one file per entry: OneDrive/SharePoint sync merges NEW files from several machines without trouble,
but two machines appending to the SAME file produce a conflict copy and one side's lines go missing. Entries
are never edited, so with one file each there is nothing to conflict on. Entry names start with a UTC
timestamp, so sorting by name gives write order (ties and small clock skew between machines only matter
for entries written within the same moment).

Legacy single-file logs (manifest.jsonl, ledger/decisions.jsonl, notices_sent.jsonl) from older data
directories are still read, before the per-entry files, and are never written again.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class SyncConflictError(Exception):
    pass


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
    def manifest_dir(self) -> Path:
        return self.root / "manifest"

    @property
    def ledger_dir(self) -> Path:
        return self.root / "ledger" / "decisions"

    @property
    def notices_dir(self) -> Path:
        return self.root / "notices_sent"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    # legacy single-file logs (read-only)
    @property
    def legacy_manifest(self) -> Path:
        return self.root / "manifest.jsonl"

    @property
    def legacy_ledger(self) -> Path:
        return self.root / "ledger" / "decisions.jsonl"

    @property
    def legacy_notices(self) -> Path:
        return self.root / "notices_sent.jsonl"

    def init(self) -> None:
        for d in (self.root / "raw", self.manifest_dir, self.ledger_dir, self.notices_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def require_initialized(self) -> None:
        if not (self.manifest_dir.exists() or self.legacy_manifest.exists()):
            raise SystemExit(f"No JFDC data directory at {self.root}. Run `jfdc init` first.")

    def sync_conflicts(self) -> list[Path]:
        """Stray copies of the legacy single-file logs, e.g. OneDrive's `decisions-LAPTOP.jsonl` or
        `manifest (1).jsonl`. Each one may hold decisions/uploads the real file doesn't have."""
        expected = {self.legacy_manifest, self.legacy_ledger, self.legacy_notices}
        stems = {p.stem for p in expected}
        found = []
        for d in {p.parent for p in expected}:
            if d.exists():
                found += [p for p in d.iterdir() if p not in expected and p.is_file()
                          and any(p.name.startswith(s) for s in stems)]
        return sorted(found)

    def check_sync_conflicts(self) -> None:
        if stray := self.sync_conflicts():
            raise SyncConflictError(
                "Possible OneDrive/SharePoint sync conflict copies: "
                + ", ".join(str(p.relative_to(self.root)) for p in stray)
                + ". Merge their lines into the real file (keep every line, drop exact duplicates), "
                "delete the copy, then re-run. Nothing was written."
            )

    # ------------------------------------------------------------ manifest
    def uploads(self, source: str | None = None) -> list[Upload]:
        out = [Upload(**r) for r in _read_log(self.legacy_manifest, self.manifest_dir)]
        return [u for u in out if source is None or u.source == source]

    def find_by_hash(self, sha: str, sheet: str | None = None) -> Upload | None:
        return next((u for u in self.uploads() if u.sha256 == sha and u.sheet == sheet), None)

    def store_upload(self, src: Path, source: str, as_of: datetime, by: str, rows_ok: int,
                     rows_quarantined: int, newest_record: str | None, notes: str = "",
                     sheet: str | None = None) -> Upload:
        self.check_sync_conflicts()
        sha = sha256_file(src)
        # The id must be unique WITHOUT reading other machines' entries (they may not have synced yet).
        upload_id = f"{source}-{as_of:%Y%m%d-%H%M}-{uuid.uuid4().hex[:6]}"
        dest = self.root / "raw" / source / f"{upload_id}{src.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        os.chmod(dest, 0o444)  # raw files are immutable
        up = Upload(
            upload_id=upload_id,
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
        _write_entry(self.manifest_dir, asdict(up))
        return up

    def path_of(self, up: Upload) -> Path:
        return self.root / up.stored_path

    # ------------------------------------------------------------ ledger
    def decisions(self) -> list[dict]:
        """All decisions in write order: legacy log first, then per-entry files by name."""
        return _read_log(self.legacy_ledger, self.ledger_dir)

    def append_decision(self, entry: dict) -> None:
        _write_entry(self.ledger_dir, entry)

    # ------------------------------------------------------------ notices
    def notices_sent(self) -> list[dict]:
        return _read_log(self.legacy_notices, self.notices_dir)

    def mark_notice_sent(self, entry: dict) -> None:
        self.check_sync_conflicts()
        _write_entry(self.notices_dir, entry)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_log(legacy: Path, entry_dir: Path) -> list[dict]:
    out = []
    if legacy.exists():
        out += [json.loads(line) for line in legacy.read_text().splitlines() if line.strip()]
    if entry_dir.exists():
        # Only finished entries: in-progress temp files end in .tmp. Sync clients sometimes leave
        # partial/placeholder files, so an unreadable entry is an error, never silently skipped.
        for p in sorted(entry_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                raise SyncConflictError(
                    f"Can't read {entry_dir.name}/{p.name}: {e}. "
                    "It may still be syncing (is the folder set to 'Always keep on this device'?). "
                    "Wait for OneDrive to finish and re-run."
                ) from e
    return out


def _write_entry(entry_dir: Path, obj: dict) -> Path:
    """Write one entry as its own file, atomically (temp file + rename)."""
    entry_dir.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex[:8]}.json"
    tmp = entry_dir / f".{name}.tmp"
    tmp.write_text(json.dumps(obj, default=str, indent=1))
    os.replace(tmp, entry_dir / name)
    return entry_dir / name
