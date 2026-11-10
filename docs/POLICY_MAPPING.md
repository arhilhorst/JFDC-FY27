# Policy → rule → code

| Rule ID | SAF Policy | Meaning | Creates strike? | Code |
|---|---|---|---|---|
| `R-9.5.1-OVERDUE` | §9.5.1 / §9.5.2 | No recap, more than 14 days after the event's last day | Proposed (ENFORCED only) | `rules/recap_rule.py` |
| `R-9.5.1-LATE` | §9.5.1 / §9.5.2 | Recap filed after the due date | Proposed (ENFORCED only) | `rules/recap_rule.py` |
| `R-9.5.1-INCOMPLETE` | §9.5.1 | Recap missing bill #, date, location, attendees or proof | Proposed as a **judgment call** (C7) | `rules/recap_rule.py`, `ingest/recap.py` |
| `R-9.5.2-NOT-TRACKED` | §9.5.2 | Recap says attendance wasn't tracked | Proposed | `rules/recap_rule.py` (needs PC-2) |
| `R-9.5-MATCH-REVIEW` | §9.5.3, charter rule 2 | Recap ↔ bill match unsure | No, until resolved | `link.py` |
| `R-9.5-NO-EVENT-DATE` | (data gap) | No event date from bill details or recap | No | `rules/recap_rule.py` |
| `R-9.5.3-MULTI-BILL` | §9.5.3 | One recap covers several bills, or several bills share an event date | No (info). Strikes stay per bill (B4). | `rules/flags.py` |
| `R-9.5.1-DATE-MISMATCH` | §9.5.1 | The bill's event date and the recap's differ by more than a day | No | `rules/flags.py` |
| `R-9.5-ATTESTATION` | §9.5 / bill page question | RSO answered "Yes, all recaps submitted" on a new bill while one was overdue | No (high-severity flag) | `rules/flags.py` |
| `R-9.5-FUNDS-NOT-USED` | Chair decision C2 | Recap says funds weren't used: COMPLETENESS class, no strike | No | `rules/flags.py` |
| `R-9.6-BILLS-CAP` | §9.6 | An RSO's approved FY bills exceed the cap in `policy.yaml` ($40,000, per the JFC sheet; see O4) | No | `rules/flags.py` |

**Strike consequences (§9.5.2)**, in `rules/strikes.py::consequence`:
1. Written warning; Supplemental Bills ineligible until the form is submitted
2. Ineligible; account frozen until form submitted + 30 days (`policy.yaml: strike2_freeze_days_after_submission`)
3. Ineligible; frozen through June 30

Only **confirmed** strikes are numbered (C6). Strikes count in the **FY of the event** (C5) and reset July 1.

**Numbering is by confirmation order** (pending Chair sign-off), with violation date breaking ties within one
import. Confirming an older violation later gives it the *next* number, so a number the RSO was already told never
changes. The only thing that changes a number is a `strike_remove` / `strike_waive` of an earlier strike. Later
strikes then move down, and the RSO gets a `STRIKE_RENUMBERED` correction, not a second strike notice.

**A confirmed strike is never dropped silently.** If its bill stops being evaluated (no longer an event bill,
missing from the export, out of scope), it stays counted as `BASIS_MISSING` and goes to Needs Review until a
confirmer records `strike_remove`. No new strike notice goes out on a strike whose basis is in question.

**FY change:** last FY's bills stay in scope while their recap falls due in the new FY (a 6/25 event is due 7/9).
Add the new FY's `scope:` entry to `policy.yaml` **before July 1** and keep the old one.

> **Policy discrepancy to resolve:** the Engage bill form's B11 section text says custodial fees sit "within
> the **$40,000** cap for funding for SGA Bills", but SAF Policy §9.6 (rev. 9/29/2026) says **$45,000**.
> The JFC Data Sheet's Bills Cap Tracker also uses $40,000, so `policy.yaml` uses **$40,000**. SAF Policy §9.6 should be corrected, or the config changed if the policy wins.
