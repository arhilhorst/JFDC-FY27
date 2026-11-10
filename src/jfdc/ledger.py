"""The decision ledger: append-only human judgments, with permission checks.

Every decision is {id, type, actor, at, reason, ...payload}. Nothing is ever edited
or deleted; `revoke` cancels an earlier decision by id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .workspace import Workspace

# decision type -> (roles allowed to write it, required payload keys)
DECISION_TYPES: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "alias_add": ({"admin", "reviewer"}, ("alias", "rso")),
    "link_confirm": ({"admin", "reviewer"}, ("recap_id", "bill_id")),
    "link_reject": ({"admin", "reviewer"}, ("recap_id", "bill_id")),
    "exemption": ({"admin", "reviewer"}, ("bill_id",)),
    "funds_not_used": ({"admin", "reviewer"}, ("bill_id",)),
    "event_date_override": ({"admin", "reviewer"}, ("bill_id", "event_date")),
    # Strike decisions: entered by admin/reviewer, but `confirmed_by` MUST be a confirmer (C6).
    "strike_confirm": ({"admin", "reviewer", "confirmer"}, ("bill_id", "confirmed_by")),
    "strike_waive": ({"admin", "reviewer", "confirmer"}, ("bill_id", "confirmed_by")),
    "strike_remove": ({"admin", "reviewer", "confirmer"}, ("bill_id", "confirmed_by")),
    "report_approve": ({"admin"}, ("run_id",)),
    "revoke": ({"admin"}, ("decision_id",)),
}
STRIKE_TYPES = {"strike_confirm", "strike_waive", "strike_remove"}
REASON_REQUIRED = {"exemption", "funds_not_used", "strike_waive", "strike_remove", "revoke", "event_date_override"}


class PermissionDenied(Exception):
    pass


def roles_of(cfg: Config, email: str) -> set[str]:
    e = email.strip().lower()
    return {role for role, members in cfg.roles.items() if e in members}


def record_decision(ws: Workspace, cfg: Config, dtype: str, actor: str, reason: str = "",
                    **payload: str) -> dict:
    if dtype not in DECISION_TYPES:
        raise ValueError(f"Unknown decision type {dtype!r}. Known: {', '.join(sorted(DECISION_TYPES))}")
    allowed, required = DECISION_TYPES[dtype]
    ws.check_sync_conflicts()
    if not cfg.roles:
        raise PermissionDenied(
            f"No roles.yaml in {ws.root}. Copy config/roles.example.yaml there and fill in GT emails."
        )
    actor_roles = roles_of(cfg, actor)
    if not actor_roles & allowed:
        raise PermissionDenied(f"{actor} ({', '.join(sorted(actor_roles)) or 'operator'}) may not record {dtype}.")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValueError(f"{dtype} needs: {', '.join(missing)}")
    if dtype in REASON_REQUIRED and not reason.strip():
        raise ValueError(f"{dtype} requires a reason.")
    if dtype in STRIKE_TYPES:
        cb = payload["confirmed_by"].strip().lower()
        if "confirmer" not in roles_of(cfg, cb):
            raise PermissionDenied(f"confirmed_by={cb} is not on the confirmer list (Walker / named JFC members).")
        payload["confirmed_by"] = cb
    entry = {
        "id": uuid.uuid4().hex[:12],
        "type": dtype,
        "actor": actor.strip().lower(),
        "at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason.strip(),
        **{k: str(v).strip() for k, v in payload.items()},
    }
    ws.append_decision(entry)
    return entry


@dataclass
class LedgerState:
    """The effective state of the ledger after applying revocations."""

    aliases: dict[str, str] = field(default_factory=dict)  # org_key(alias) -> canonical RSO
    link_confirmed: set[tuple[str, str]] = field(default_factory=set)  # (recap_id, bill_id)
    link_rejected: set[tuple[str, str]] = field(default_factory=set)
    exemptions: dict[str, dict] = field(default_factory=dict)  # bill_id -> decision
    funds_not_used: dict[str, dict] = field(default_factory=dict)
    event_date_overrides: dict[str, str] = field(default_factory=dict)
    strike_decisions: dict[str, dict] = field(default_factory=dict)  # bill_id -> LATEST strike decision
    approvals: dict[str, dict] = field(default_factory=dict)  # run_id -> decision


def load_ledger(decisions: list[dict]) -> LedgerState:
    from .textnorm import org_key

    revoked = {d["decision_id"] for d in decisions if d["type"] == "revoke"}
    st = LedgerState()
    for seq, d in enumerate(decisions):
        if d["id"] in revoked or d["type"] == "revoke":
            continue
        t = d["type"]
        if t == "alias_add":
            st.aliases[org_key(d["alias"])] = d["rso"]
        elif t == "link_confirm":
            st.link_confirmed.add((d["recap_id"], d["bill_id"]))
            st.link_rejected.discard((d["recap_id"], d["bill_id"]))
        elif t == "link_reject":
            st.link_rejected.add((d["recap_id"], d["bill_id"]))
            st.link_confirmed.discard((d["recap_id"], d["bill_id"]))
        elif t == "exemption":
            st.exemptions[d["bill_id"]] = d
        elif t == "funds_not_used":
            st.funds_not_used[d["bill_id"]] = d
        elif t == "event_date_override":
            st.event_date_overrides[d["bill_id"]] = d["event_date"]
        elif t in STRIKE_TYPES:
            # Later entries win. `_seq` (position in the ledger) numbers strikes in confirmation order.
            st.strike_decisions[d["bill_id"]] = {**d, "_seq": seq}
        elif t == "report_approve":
            st.approvals[d["run_id"]] = d
    return st
