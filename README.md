# JFDC Compliance Engine

Checks SGA-funded events against **SAF Policy §9.5** (post-event recaps) for the Georgia Tech Joint Finance
Data Committee. It reads the Engage export and the Recap Form responses, matches each funded event to its
recap, proposes strikes, and produces a daily report, a dashboard and draft emails. People make every final call.

**[Start](#start)** · **[Daily use](#daily-use)** · **[Dashboard](#dashboard)** · **[Rules](#rules)** · **[For developers](#for-developers)** · **[Docs](#docs)**

---

## Start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
jfdc demo                                              # try it on fictional data first
```

To use real data, sync the JFDC folder from SharePoint (**Sync**, then **Always keep on this device**) and
point the engine at it:

```bash
export JFDC_DATA_DIR="$HOME/Library/CloudStorage/<your OneDrive>/JFDC/data"   # add to ~/.zshrc
jfdc init
```

The Chair then copies `config/roles.example.yaml` to `roles.yaml` in that folder and lists who is an admin,
reviewer or confirmer.

## Daily use

```bash
jfdc ingest JFC_Data_Sheet.xlsx Post_Event_Recap_Form.xlsx --by you@gatech.edu --as-of 2026-11-10T09:00
jfdc run
jfdc dashboard
```

`--as-of` is when you downloaded the files (Eastern time). A run refuses recap data more than 24 hours old.
Work through the dashboard's **To review** tab, send the **Strike Confirmation** sheet to a confirmer, and
send the drafted emails after the Chair approves. The full routine is in [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

<details>
<summary>All commands</summary>

| Command | What it does |
|---|---|
| `jfdc init` | Create the data folder |
| `jfdc ingest FILES --by EMAIL --as-of TIME` | Check and store downloaded files (detects which file is which) |
| `jfdc status` | List what has been ingested |
| `jfdc run` | Build the report, dashboard and draft emails |
| `jfdc dashboard` | Open the latest dashboard |
| `jfdc decide TYPE key=value ... --actor EMAIL --reason "..."` | Record a decision (match, alias, exemption, strike, appeal) |
| `jfdc import-confirmations FILE.xlsx --actor EMAIL` | Load a filled-in Strike Confirmation sheet |
| `jfdc mark-sent RUN_ID --actor EMAIL` | Record that a run's emails went out |
| `jfdc demo` | Build a workspace from fictional data and open its dashboard |

</details>

## Dashboard

Each run writes `dashboard.html` next to the Excel report. It opens in any browser and needs no server or
internet connection.

| Tab | Use it to |
|---|---|
| Overview | See what needs action today, and how fresh the data is |
| RSOs | Check an RSO's standing |
| Bills | Find any bill by number, RSO, title or submitter; filter by status |
| Strikes | See strikes waiting for a confirmer, and confirmed ones |
| Appeals | Decide open appeals (admins) |
| To review | Work through matches, names and dates the engine won't decide alone |
| Guide | Statuses and rules in plain language |

The dashboard contains student names and emails. Keep it in the JFDC folder; don't post or forward it.

## Rules

- **A false strike is worse than a missed one.** When unsure, the engine sends the item to review instead.
- Recaps are due **14 days** after the event's last day. The engine *proposes* strikes; a strike only counts
  once a confirmer signs off. Strikes reset July 1.
- RSOs can **appeal** within 30 days of a strike email. An admin decides; the strike stays in force meanwhile.
  See [`docs/APPEALS.md`](docs/APPEALS.md).
- Policy numbers live in [`config/policy.yaml`](config/policy.yaml). Change them there, not in code.

<details>
<summary>Data security</summary>

- **Never commit real data.** `.gitignore` blocks spreadsheets, PDFs, emails and run folders, and CI fails if one is committed.
- Raw uploads are stored read-only and hashed. Decisions are append-only, one file each, so OneDrive syncs them without conflicts.
- Text typed into forms is treated as data: it can't become a spreadsheet formula, a dashboard script or an email recipient.
- The dashboard runs under a strict content security policy and makes no network requests.
- Roles are checked against `roles.yaml`, but `--actor` is typed in, so the decision log is an audit trail, not
  a login. Limit write access to the data folder in SharePoint.

</details>

## For developers

```bash
python -m pytest        # must pass before a PR merges; tests use fictional data only
ruff check src tests
```

<details>
<summary>How it's built</summary>

```
ingest (validate, hash, store) -> consolidate -> link recaps to bills -> evaluate (statuses, strikes, appeals)
  -> decisions from the ledger -> report.xlsx, dashboard.html, email drafts -> Chair approves -> JVPF
```

| Path | What |
|---|---|
| `campuslabs-scraper.js` | Browser scraper for bill details ([`docs/SCRAPER.md`](docs/SCRAPER.md)) |
| `src/jfdc/ingest/` | Readers for each source file |
| `src/jfdc/link.py` | Recap to bill matching |
| `src/jfdc/rules/` | Recap statuses, strikes, appeals, flags |
| `src/jfdc/ledger.py` | Permission-checked, append-only decisions |
| `src/jfdc/report.py`, `dashboard.py`, `notify.py` | Excel report, dashboard data, email drafts |
| `templates/` | Dashboard page and email wording (edit freely) |
| `config/` | Policy numbers and source column names |

</details>

## Docs

| | |
|---|---|
| [`RUNBOOK.md`](docs/RUNBOOK.md) | The daily routine, step by step |
| [`POLICY_MAPPING.md`](docs/POLICY_MAPPING.md) | Which rule does what, by policy section |
| [`APPEALS.md`](docs/APPEALS.md) | Strike appeals and the Appeal Form |
| [`PENDING_CHANGES.md`](docs/PENDING_CHANGES.md) | Changes we're waiting on from Engage, the Forms and the JFC sheet |
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full design and decisions |
| [`SCRAPER.md`](docs/SCRAPER.md) | Using the bill-details scraper |
