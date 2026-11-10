"""Data sources: the ONE place that knows where the data comes from.

Everything else in the app asks a source for a `Table` (headers + rows) and
never cares whether it came from a local Excel file, a CSV, a OneDrive-synced
workbook, or Microsoft Graph.

To add a new live connection (e.g. the Engage API), write a class with a
`load()` method returning a Table and a `version()` method that changes when
the data changes, then register it in `make_source()` at the bottom.
"""
from __future__ import annotations

import base64
import csv
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl


@dataclass
class Table:
    headers: list[str]
    rows: list[list[Any]]
    origin: str = ""
    loaded_at: float = field(default_factory=time.time)


def _min_fy(history_years: int) -> int:
    from datetime import date

    today = date.fromisoformat(os.environ["JFDC_TODAY"]) if os.environ.get("JFDC_TODAY") else date.today()
    fy = today.year + 1 if today.month >= 7 else today.year
    return fy - max(history_years, 1) + 1


def _table_from_xlsx_bytes(data: bytes, sheet: str | None, origin: str, opts: dict | None = None) -> Table:
    from .jfc_sheet import is_jfc_workbook, load_jfc_workbook

    opts = opts or {}
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    if not sheet and is_jfc_workbook(wb.sheetnames):
        # Walker's JFC Data Sheet: build one row per bill from its Engage export tabs.
        t = load_jfc_workbook(wb, opts.get("process_pattern", r"Bills Process"),
                              _min_fy(int(opts.get("history_fiscal_years", 2))))
        t.origin = origin
        return t
    ws = wb[sheet] if sheet else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    headers: list[str] = []
    rows: list[list[Any]] = []
    for raw in it:
        if not headers:
            if raw and any(c not in (None, "") for c in raw):
                headers = ["" if c is None else str(c) for c in raw]
            continue
        if raw is None or all(c in (None, "") for c in raw):
            continue
        rows.append(list(raw) + [None] * (len(headers) - len(raw)))
    wb.close()
    return Table(headers, rows, origin)


def _table_from_csv_bytes(data: bytes, origin: str) -> Table:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    all_rows = [r for r in reader]
    if not all_rows:
        return Table([], [], origin)
    headers = all_rows[0]
    rows = [r + [None] * (len(headers) - len(r)) for r in all_rows[1:] if any(c.strip() for c in r)]
    return Table(headers, rows, origin)


def table_from_bytes(data: bytes, name: str, sheet: str | None = None, opts: dict | None = None) -> Table:
    if name.lower().endswith((".csv", ".txt")):
        return _table_from_csv_bytes(data, name)
    return _table_from_xlsx_bytes(data, sheet, name, opts)


class FileSource:
    """Reads a local .xlsx or .csv file.

    Re-reads automatically whenever the file's modified-time changes, so if the
    path points at a OneDrive/SharePoint-synced workbook the dashboard stays
    current with no extra setup.
    """

    def __init__(self, path: str, sheet: str | None = None, optional: bool = False, opts: dict | None = None):
        self.path = Path(path)
        self.sheet = sheet
        self.optional = optional
        self.opts = opts or {}

    def describe(self) -> str:
        return f"file: {self.path}"

    def version(self) -> Any:
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return None

    def load(self) -> Table:
        if not self.path.exists():
            if self.optional:
                return Table([], [], str(self.path))
            raise FileNotFoundError(f"Data file not found: {self.path}")
        return table_from_bytes(self.path.read_bytes(), self.path.name, self.sheet, self.opts)


class GraphShareLinkSource:
    """Downloads an Excel file from SharePoint/OneDrive through Microsoft Graph.

    Works with a normal sharing link (like the master bills sheet link). Signs
    in as a Georgia Tech user with the device-code flow the first time, then
    caches the token in `.graph_token_cache.json`.

    Needs: `pip install msal`, and an Azure AD app registration (public client,
    delegated permission Files.Read.All). GT's tenant may require admin consent;
    see README "Live Microsoft connection".
    """

    def __init__(self, share_url: str, sheet: str | None = None, ttl_seconds: int = 300, opts: dict | None = None):
        self.opts = opts or {}
        self.share_url = share_url
        self.sheet = sheet
        self.ttl = ttl_seconds
        self.client_id = os.environ.get("GRAPH_CLIENT_ID", "")
        self.tenant = os.environ.get("GRAPH_TENANT_ID", "organizations")
        self.cache_path = Path(os.environ.get("GRAPH_TOKEN_CACHE", ".graph_token_cache.json"))
        self._last_fetch = 0.0

    def describe(self) -> str:
        return f"microsoft graph: {self.share_url[:60]}..."

    def version(self) -> Any:
        # Re-fetch every `ttl` seconds.
        return int(time.time() // self.ttl)

    def _token(self) -> str:
        import msal  # optional dependency

        if not self.client_id:
            raise RuntimeError("Set GRAPH_CLIENT_ID to use the Microsoft Graph source.")
        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            cache.deserialize(self.cache_path.read_text())
        app = msal.PublicClientApplication(
            self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}", token_cache=cache
        )
        scopes = ["Files.Read.All"]
        result = None
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
        if not result:
            flow = app.initiate_device_flow(scopes=scopes)
            print("\n=== Microsoft sign-in needed ===\n" + flow["message"] + "\n", flush=True)
            result = app.acquire_token_by_device_flow(flow)
        if cache.has_state_changed:
            self.cache_path.write_text(cache.serialize())
        if "access_token" not in result:
            raise RuntimeError(f"Graph sign-in failed: {result.get('error_description')}")
        return result["access_token"]

    def load(self) -> Table:
        import requests

        encoded = base64.urlsafe_b64encode(self.share_url.encode()).decode().rstrip("=")
        url = f"https://graph.microsoft.com/v1.0/shares/u!{encoded}/driveItem/content"
        resp = requests.get(url, headers={"Authorization": f"Bearer {self._token()}"}, timeout=60)
        resp.raise_for_status()
        return table_from_bytes(resp.content, "graph.xlsx", self.sheet, self.opts)


class EngageSource:
    """Placeholder for a future Campus Labs Engage API connection.

    Engage's budgeting API needs an API key issued by the Engage admin (Center
    for Student Engagement). Until then, export bills from Engage
    (Budgeting > Reviews > Export) and use a FileSource.
    """

    def __init__(self, **_: Any):
        pass

    def describe(self) -> str:
        return "engage api (not configured)"

    def version(self) -> Any:
        return None

    def load(self) -> Table:
        raise NotImplementedError("Engage API source is not implemented yet. Use an exported file.")


def make_source(spec: dict, base_dir: Path, env_override: str | None = None, optional: bool = False):
    """Build a source from a config block such as {"type": "file", "path": "..."}.

    An environment variable (e.g. RECAP_SOURCE) can override the path. If the
    override starts with https:// it is treated as a Microsoft Graph share link.
    """
    spec = dict(spec or {})
    override = os.environ.get(env_override) if env_override else None
    if override:
        if override.startswith("https://"):
            spec = {**spec, "type": "graph", "url": override}
        else:
            spec = {**spec, "type": "file", "path": override}

    kind = spec.get("type", "file")
    if kind == "file":
        p = Path(spec["path"])
        if not p.is_absolute():
            p = base_dir / p
        return FileSource(str(p), spec.get("sheet"), optional=optional, opts=spec)
    if kind == "graph":
        return GraphShareLinkSource(spec["url"], spec.get("sheet"), opts=spec)
    if kind == "engage":
        return EngageSource(**spec)
    raise ValueError(f"Unknown source type: {kind}")
