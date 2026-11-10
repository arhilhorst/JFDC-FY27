"""Golden §9.5 scenarios (docs/ARCHITECTURE.md §7). Strike logic must pass all of these."""

from datetime import date, datetime

import pytest
from conftest import ADMIN, CONFIRMER, DATE_Q, OPERATOR, REVIEWER, status_of

from jfdc.ingest.detect import IngestError
from jfdc.ingest.service import ingest_file
from jfdc.ledger import PermissionDenied, record_decision
from jfdc.notify import build_queue
from jfdc.pipeline import StaleDataError, run_pipeline

EV = date(2026, 9, 1)  # event; recap due 9/15 23:59:59


def rerun(w, as_of):
    return run_pipeline(w.ws, w.cfg, as_of=as_of, allow_stale=True)  # freshness has its own test


def strikes_for(res, bid):
    s = res.strikes
    return s[s["bill_id"] == str(bid)]


# 1
def test_on_time_recap_is_compliant(world):
    world.bill(100001, event_date=EV).recap(1, "100001", datetime(2026, 9, 5, 10))
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100001) == "COMPLIANT"
    assert res.strikes.empty


# 2
@pytest.mark.parametrize("sub,expected", [(datetime(2026, 9, 15, 23, 30), "COMPLIANT"),
                                          (datetime(2026, 9, 16, 0, 5), "LATE")])
def test_deadline_is_end_of_day_14(world, sub, expected):
    world.bill(100002, event_date=EV).recap(1, "100002", sub)
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100002) == expected
    assert (len(strikes_for(res, 100002)) == 1) == (expected == "LATE")


# 3
def test_due_then_overdue(world):
    world.bill(100003, event_date=EV)
    res = world.write_and_run(datetime(2026, 9, 11, 9))
    assert status_of(res, 100003) == "DUE"
    assert res.requirements.iloc[0]["days_left"] == 4
    res = rerun(world, datetime(2026, 9, 16, 9))
    assert status_of(res, 100003) == "OVERDUE"
    assert strikes_for(res, 100003)["state"].iloc[0] == "proposed"


def test_multi_day_event_clock_starts_on_last_day(world):
    world.bill(100030, event_date=None)
    world.details.append({"Bill Number": "100030", DATE_Q: "9/1/26 - 9/3/26"})
    res = world.write_and_run(datetime(2026, 9, 16, 9))
    r = res.requirements.iloc[0]
    assert r["event_date"] == date(2026, 9, 3) and r["status"] == "DUE"


# 4
def test_one_recap_covers_three_bills(world):
    for b in (100041, 100042, 100043):
        world.bill(b, event_date=EV)
    world.recap(1, "[Bill #100041], [Bill #100042], 100043", datetime(2026, 9, 5))
    res = world.write_and_run(datetime(2026, 9, 20))
    assert {status_of(res, b) for b in (100041, 100042, 100043)} == {"COMPLIANT"}
    assert (res.flags["rule_id"] == "R-9.5.3-MULTI-BILL").any()


# 5 + 7
def test_joint_event_each_rso_files_its_own(world):
    world.bill(100051, rso="Alpha Club", event_date=EV).bill(100052, rso="Beta Club", event_date=EV)
    world.recap(1, "100051, 100052", datetime(2026, 9, 5), rso="Alpha Club")
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100051) == "COMPLIANT"
    assert status_of(res, 100052) == "NEEDS_REVIEW"  # Alpha's recap can't satisfy Beta's bill
    assert strikes_for(res, 100052).empty


# 6
def test_missing_bill_number_falls_back_to_review_not_credit(world):
    world.bill(100006, event_date=EV).recap(1, "N/Aa", datetime(2026, 9, 5), dateloc="9/2/2026 Skiles")
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100006) == "NEEDS_REVIEW"
    assert res.strikes.empty
    record_decision(world.ws, world.cfg, "link_confirm", REVIEWER, recap_id="1", bill_id="100006")
    assert status_of(rerun(world, datetime(2026, 9, 20)), 100006) == "COMPLIANT"


# 8 / 16
@pytest.mark.parametrize("st", ["Rejected", "ReturnedForRevision"])
def test_unapproved_bill_needs_form_but_never_strikes(world, st):
    world.bill(100008, status=st, event_date=EV)
    res = world.write_and_run(datetime(2026, 9, 20))
    r = res.requirements.iloc[0]
    assert (r["class"], r["status"]) == ("COMPLETENESS", "OVERDUE")
    assert res.strikes.empty


def test_non_event_bill_has_no_recap_requirement(world):
    world.bill(100009, event=False)
    res = world.write_and_run(datetime(2026, 9, 20))
    assert res.requirements.empty


# 9
def test_exemption(world):
    world.bill(100010, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    record_decision(world.ws, world.cfg, "exemption", REVIEWER, reason="Event cancelled (SOFO confirmed)", bill_id="100010")
    res = rerun(world, datetime(2026, 9, 20))
    assert status_of(res, 100010) == "EXEMPT" and res.strikes.empty


# 10
def test_attendance_not_tracked_still_strikes(world):
    world.form_has_new_questions = True
    world.bill(100011, event_date=EV).recap(1, "100011", datetime(2026, 9, 5), attendees="", proof="", tracked=False)
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100011) == "NOT_TRACKED"
    assert len(strikes_for(res, 100011)) == 1


def test_incomplete_recap_is_flagged_for_review(world):
    world.bill(100012, event_date=EV).recap(1, "100012", datetime(2026, 9, 5), proof="")
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100012) == "INCOMPLETE"
    s = strikes_for(res, 100012)
    assert s["state"].iloc[0] == "proposed" and "Judgment call" in s["note"].iloc[0]


# 17 (C2)
def test_funds_not_used_reclassifies_and_proposes_removal(world):
    world.bill(100017, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100017", confirmed_by=CONFIRMER)
    record_decision(world.ws, world.cfg, "funds_not_used", REVIEWER, reason="RSO reports event cancelled",
                    bill_id="100017")
    res = rerun(world, datetime(2026, 9, 20))
    assert res.requirements.iloc[0]["class"] == "COMPLETENESS"
    s = strikes_for(res, 100017).iloc[0]
    assert s["state"] == "confirmed" and not s["supported"] and "REMOVAL PROPOSED" in s["note"]


# 18 + 11 + 19 + standing
def test_strike_numbering_consequences_and_walk_back(world):
    for i, d in enumerate([date(2026, 8, 20), date(2026, 8, 25), date(2026, 9, 1)]):
        world.bill(100100 + i, event_date=d)
    res = world.write_and_run(datetime(2026, 9, 20))
    assert set(res.strikes["state"]) == {"proposed"} and res.strikes["ordinal"].isna().all()
    assert build_queue(res, [], 3).query("notice.str.startswith('STRIKE')").empty  # nothing sent unconfirmed

    for b in ("100100", "100101", "100102"):
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id=b, confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 9, 20))
    assert list(res.strikes.sort_values("violation_date")["ordinal"]) == [1, 2, 3]
    assert res.standing.iloc[0]["standing"] == "STRIKE 3: FROZEN rest of FY"
    assert res.strikes.set_index("bill_id").at["100102", "active_until"] == date(2027, 6, 30)

    record_decision(world.ws, world.cfg, "strike_remove", REVIEWER, reason="Same event as 100101 (RSO appeal)",
                    bill_id="100100", confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 9, 20))
    by = res.strikes.set_index("bill_id")
    assert by.at["100101", "ordinal"] == 1 and by.at["100102", "ordinal"] == 2
    assert res.standing.iloc[0]["standing"].startswith("STRIKE 2: FROZEN")


def test_strike2_freeze_lasts_30_days_after_late_form(world):
    world.bill(100201, event_date=date(2026, 8, 1)).bill(100202, event_date=date(2026, 8, 20))
    world.recap(1, "100202", datetime(2026, 9, 10))  # late (due 9/3)
    world.write_and_run(datetime(2026, 9, 20))
    for b in ("100201", "100202"):
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id=b, confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 9, 20))
    s2 = res.strikes.set_index("bill_id").loc["100202"]
    assert s2["ordinal"] == 2 and s2["active_until"] == date(2026, 10, 10)


# 12 + 20
def test_strikes_count_in_event_fy_and_reset(world):
    world.bill(100300, event_date=date(2026, 6, 25), process="SGA Bills Process FY27", submitted="6/1/2026 12:00")
    world.write_and_run(datetime(2026, 7, 15))
    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100300", confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 7, 15))
    assert res.strikes.iloc[0]["fy"] == 26  # event in June => FY26, even though due in July
    assert res.standing.iloc[0]["standing"] == "GOOD"  # FY27 standing starts clean


# 13
def test_stale_recap_export_blocks_run(world):
    world.bill(100013, event_date=EV)
    with pytest.raises(StaleDataError):
        world.write_and_run(datetime(2026, 9, 20, 12), recap_as_of=datetime(2026, 9, 19, 0))
    res = run_pipeline(world.ws, world.cfg, as_of=datetime(2026, 9, 20, 12), allow_stale=True)
    assert res.watermark.startswith("DRAFT")


# 14 + 15
def test_duplicate_upload_and_renamed_column(world, tmp_path):
    world.bill(100014, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    eng = sorted((tmp_path / "in").glob("engage*.csv"))[0]
    assert ingest_file(world.ws, world.cfg, eng, by=OPERATOR)[0].duplicate_of is not None
    bad = tmp_path / "bad.csv"
    bad.write_text(eng.read_text(encoding="cp1252").replace("SubmittedOnBehalfOf", "Organization"), encoding="cp1252")
    with pytest.raises(IngestError):
        ingest_file(world.ws, world.cfg, bad, by=OPERATOR, source="engage_line_items")


# 21
def test_windows_1252_apostrophes(world):
    world.bill(100021, rso="Ramblin’ Reck Club", event_date=EV)
    world.recap(1, "100021", datetime(2026, 9, 5), rso="Ramblin' Reck Club")
    res = world.write_and_run(datetime(2026, 9, 20))
    assert status_of(res, 100021) == "COMPLIANT"


def test_rso_alias_with_acronym(world):
    world.bill(100022, rso="Graduate Women in Engineering", event_date=EV)
    world.recap(1, "100022", datetime(2026, 9, 5), rso="Graduate Women in Engineering (GWiE)")
    assert status_of(world.write_and_run(datetime(2026, 9, 20)), 100022) == "COMPLIANT"


def test_implausible_recap_date_goes_to_review(world):
    world.bill(100023).recap(1, "100023", datetime(2026, 9, 25), dateloc="09/24/2006, Ferst Center")
    res = world.write_and_run(datetime(2026, 9, 30))
    assert status_of(res, 100023) == "NEEDS_REVIEW" and res.strikes.empty


# 23
def test_notices_send_once(world):
    world.bill(100024, event_date=EV)
    res = world.write_and_run(datetime(2026, 9, 13, 9))
    q = build_queue(res, [], 3)
    assert list(q["notice"]) == ["REMINDER_DUE_SOON"] and q.iloc[0]["to"] == "s100024@gatech.edu"
    assert build_queue(res, [{"bill_id": "100024", "notice": "REMINDER_DUE_SOON"}], 3).empty


# Permissions (C9)
def test_permissions_are_enforced(world):
    world.bill(100025, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    with pytest.raises(PermissionDenied):
        record_decision(world.ws, world.cfg, "link_confirm", OPERATOR, recap_id="1", bill_id="100025")
    with pytest.raises(PermissionDenied):  # strike needs a real confirmer's sign-off
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100025", confirmed_by=OPERATOR)
    with pytest.raises(PermissionDenied):
        record_decision(world.ws, world.cfg, "revoke", REVIEWER, reason="x", decision_id="abc")
    record_decision(world.ws, world.cfg, "revoke", ADMIN, reason="x", decision_id="abc")


def test_ambiguous_backup_date_goes_to_review(world):
    world.bill(100031)
    world.details.append({"Bill Number": "100031", DATE_Q: "11/7-8/2026 with Backup: 11/14-15/2026"})
    res = world.write_and_run(datetime(2026, 12, 15))
    assert status_of(res, 100031) == "NEEDS_REVIEW" and res.strikes.empty


def test_jfc_data_sheet_workbook_ingests_every_known_tab(world, tmp_path):
    """Mirrors the real JFC Data Sheet: Excel-table placeholder headers, Excel serial datetimes, extra tabs."""
    import pandas as pd
    from conftest import ENGAGE_COLS

    world.bill(100040, submitted="45870.5")  # 2025-08-01 12:00 as an Excel serial
    eng = pd.DataFrame(world.bills, columns=ENGAGE_COLS)
    placeholder = lambda df: pd.concat(  # noqa: E731
        [pd.DataFrame([df.columns], columns=[f"Column{i + 1}" for i in range(len(df.columns))]),
         df.set_axis([f"Column{i + 1}" for i in range(len(df.columns))], axis=1)], ignore_index=True)
    det = pd.DataFrame([{"Bill Number": "100040", "Q4: Is this request intended to be used with an event (i.e. are "
                         "you requesting funding from section A)?": "Yes, and I will fill in all questions", DATE_Q: "46344"}])
    wb = tmp_path / "JFC_Data_Sheet.xlsx"
    with pd.ExcelWriter(wb) as xw:
        pd.DataFrame({"Bill Number": ["1"], "Submitter Name": ["x"]}).to_excel(xw, sheet_name="Bill Queue", index=False)
        pd.DataFrame({"RSO Name": ["Alpha Club"], "Budget Requested": ["100"], "Budget Allocated": ["50"]}).to_excel(
            xw, sheet_name="FY27 Final Budgets", index=False)
        placeholder(det).to_excel(xw, sheet_name="CampusLabs_Budget_Requests", index=False)
        placeholder(eng).to_excel(xw, sheet_name="Data Pasting Site", index=False)
    world.ws.init()
    res = ingest_file(world.ws, world.cfg, wb, by=OPERATOR, as_of=datetime(2026, 11, 20))
    assert {r.source for r in res} == {"jfc_budgets", "bill_details", "engage_line_items"}
    assert "Bill Queue" in res[0].warnings[-1]
    from jfdc.ingest.service import parse_source

    up = next(r.upload for r in res if r.source == "bill_details")
    d = parse_source(world.ws.path_of(up), "bill_details", world.cfg, up.sheet)[0]
    assert d.iloc[0]["event_last_date"] == date(2026, 11, 18) and bool(d.iloc[0]["is_event"])
    up = next(r.upload for r in res if r.source == "engage_line_items")
    (bills, _), *_ = parse_source(world.ws.path_of(up), "engage_line_items", world.cfg, up.sheet)
    assert bills.iloc[0]["first_submitted"] == pd.Timestamp("2025-08-01 12:00")


def test_scraper_csv_formula_guard_and_flagged_rows(world, tmp_path):
    """campuslabs-scraper.js output: ' guard on cells starting with '-', Warnings/Error rows quarantined."""
    import pandas as pd

    from jfdc.ingest.service import parse_source

    csv = tmp_path / "CampusLabs_Budget_Requests_2026-11-06.csv"
    pd.DataFrame([
        {"Bill Number": "100050", "Organization": "Alpha Club", DATE_Q: "'-11/18/26", "Warnings": "", "Error": ""},
        {"Bill Number": "100051", "Organization": "Alpha Club", DATE_Q: "11/19/26", "Warnings": "info tab timed out", "Error": ""},
        {"Bill Number": "100052", "Organization": "Alpha Club", DATE_Q: "", "Warnings": "", "Error": "TypeError"},
    ]).to_csv(csv, index=False, encoding="utf-8-sig")
    world.ws.init()
    (r,) = ingest_file(world.ws, world.cfg, csv, by=OPERATOR, as_of=datetime(2026, 11, 6))
    assert r.source == "bill_details" and r.upload.rows_ok == 1 and r.upload.rows_quarantined == 2
    d = parse_source(world.ws.path_of(r.upload), "bill_details", world.cfg)[0]
    assert d.iloc[0]["event_last_date"] == date(2026, 11, 18)


# Strike integrity: numbering, persistence, FY carryover, sync conflicts
def _sent(queue, run_id="r1"):
    return [{"bill_id": n["bill_id"], "notice": n["notice"], "ordinal": n["ordinal"], "run_id": run_id}
            for n in queue.to_dict("records")]


def test_confirming_an_older_strike_later_does_not_renumber(world):
    world.bill(100400, event_date=date(2026, 8, 20)).bill(100401, event_date=date(2026, 9, 1))
    world.write_and_run(datetime(2026, 9, 20))
    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100401", confirmed_by=CONFIRMER)
    q1 = build_queue(rerun(world, datetime(2026, 9, 20)), [], 3)
    assert q1.query("notice.str.startswith('STRIKE')")[["bill_id", "notice"]].values.tolist() == [["100401", "STRIKE_1"]]

    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100400", confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 9, 21))
    by = res.strikes.set_index("bill_id")
    assert by.at["100401", "ordinal"] == 1 and by.at["100400", "ordinal"] == 2
    q2 = build_queue(res, _sent(q1), 3).query("notice.str.startswith('STRIKE')")
    assert q2[["bill_id", "notice"]].values.tolist() == [["100400", "STRIKE_2"]]


def test_removed_strike_sends_renumber_correction_not_a_new_strike(world):
    world.bill(100410, event_date=date(2026, 8, 20)).bill(100411, event_date=date(2026, 9, 1))
    world.write_and_run(datetime(2026, 9, 20))
    for b in ("100410", "100411"):
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id=b, confirmed_by=CONFIRMER)
    sent = _sent(build_queue(rerun(world, datetime(2026, 9, 20)), [], 3))
    record_decision(world.ws, world.cfg, "strike_remove", REVIEWER, reason="same event", bill_id="100410",
                    confirmed_by=CONFIRMER)
    q = build_queue(rerun(world, datetime(2026, 9, 21)), sent, 3).query("notice.str.startswith('STRIKE')")
    assert sorted(q[["bill_id", "notice"]].values.tolist()) == [["100410", "STRIKE_REMOVED"],
                                                               ["100411", "STRIKE_RENUMBERED"]]
    assert "now Strike 1" in q.set_index("bill_id").at["100411", "subject"]
    q_after = build_queue(rerun(world, datetime(2026, 9, 21)), sent + _sent(q), 3)
    assert q_after.query("notice.str.startswith('STRIKE')").empty


def test_confirmed_strike_survives_bill_leaving_the_export(world):
    world.bill(100420, event_date=date(2026, 8, 20)).bill(100421, event_date=date(2026, 8, 25))
    world.write_and_run(datetime(2026, 9, 20))
    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100420", confirmed_by=CONFIRMER)
    world.bills = [b for b in world.bills if b["Id"] != "100420"]  # dropped from the next export
    world.details = [d for d in world.details if d["Bill Number"] != "100420"]
    res = world.write_and_run(datetime(2026, 9, 21), allow_stale=True)
    s = strikes_for(res, 100420).iloc[0]
    assert s["state"] == "confirmed" and s["status"] == "BASIS_MISSING" and s["ordinal"] == 1
    assert any(r["kind"] == "STRIKE_BASIS_MISSING" for r in res.review)
    assert res.standing.set_index("rso").at["Alpha Club", "confirmed_strikes"] == 1
    build_queue(res, [], 3)  # must not crash on a strike with no requirement row


def test_last_fy_bill_due_in_new_fy_is_still_checked(world, tmp_path, monkeypatch):
    import shutil

    import yaml

    from jfdc.config import REPO_ROOT
    cdir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cdir)
    pol = yaml.safe_load((cdir / "policy.yaml").read_text())
    pol["scope"][28] = {"bill_processes": ["SGA Bills Process FY28"], "budget_processes": []}
    (cdir / "policy.yaml").write_text(yaml.safe_dump(pol))
    monkeypatch.setenv("JFDC_CONFIG_DIR", str(cdir))

    world.bill(100430, event_date=date(2027, 6, 25), submitted="5/1/2027 12:00")  # due 7/9/2027
    world.bill(100431, event_date=date(2027, 5, 1), submitted="4/1/2027 12:00")   # due 5/15: settled in FY27
    res = world.write_and_run(datetime(2027, 7, 20))
    assert status_of(res, 100430) == "OVERDUE"
    assert "100431" not in set(res.requirements["bill_id"])
    assert strikes_for(res, 100430).iloc[0]["fy"] == 27  # C5: counts in the event's FY


def test_onedrive_conflict_copy_blocks_writes_and_runs(world):
    from jfdc.workspace import SyncConflictError
    world.bill(100440, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    (world.ws.root / "ledger" / "decisions-LAPTOP-7F3.jsonl").write_text("{}\n")
    with pytest.raises(SyncConflictError):
        rerun(world, datetime(2026, 9, 20))
    with pytest.raises(SyncConflictError):
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id="100440", confirmed_by=CONFIRMER)


# Sync-safe store: one file per entry
def test_store_writes_one_file_per_entry_and_ids_are_unique(world):
    world.bill(100500, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    for b in ("100500", "100500"):
        record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id=b, confirmed_by=CONFIRMER)
    ws = world.ws
    assert len(list(ws.ledger_dir.glob("*.json"))) == 2
    assert not ws.legacy_ledger.exists() and not ws.legacy_manifest.exists()
    ids = [u.upload_id for u in ws.uploads()]
    assert len(ids) == len(set(ids)) and len(list(ws.manifest_dir.glob("*.json"))) == len(ids)


def test_legacy_jsonl_logs_are_still_read_first(world):
    import json
    world.bill(100510, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    ws = world.ws
    legacy = {"id": "legacy1", "type": "strike_confirm", "actor": REVIEWER, "at": "2026-09-01T00:00:00",
              "reason": "", "bill_id": "100510", "confirmed_by": CONFIRMER}
    ws.legacy_ledger.write_text(json.dumps(legacy) + "\n")
    record_decision(world.ws, world.cfg, "strike_waive", REVIEWER, reason="appeal", bill_id="100510",
                    confirmed_by=CONFIRMER)
    assert [d["type"] for d in ws.decisions()] == ["strike_confirm", "strike_waive"]
    assert strikes_for(rerun(world, datetime(2026, 9, 20)), 100510).iloc[0]["state"] == "waived"


def test_half_synced_entry_blocks_instead_of_being_skipped(world):
    from jfdc.workspace import SyncConflictError
    world.bill(100520, event_date=EV)
    world.write_and_run(datetime(2026, 9, 20))
    (world.ws.ledger_dir / "20260920T000000000000Z_deadbeef.json").write_text('{"id": "x", "ty')
    with pytest.raises(SyncConflictError, match="still be syncing"):
        rerun(world, datetime(2026, 9, 20))
