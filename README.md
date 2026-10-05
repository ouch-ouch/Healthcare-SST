# Harborview Source of Truth

A central source of truth for Harborview Care Group — ingests four messy,
disagreeing data sources (HR roster, payroll, licenses, staff schedule) into
an entity graph, resolves identity across sources, and surfaces everything
wrong, inconsistent, or needing a human as a flag.

Full design rationale: [`docs/superpowers/specs/2026-10-04-harborview-sot-design.md`](docs/superpowers/specs/2026-10-04-harborview-sot-design.md).
Implementation plan: [`docs/superpowers/plans/2026-10-04-harborview-sot.md`](docs/superpowers/plans/2026-10-04-harborview-sot.md).

## Quickstart (judges — one command)

```bash
./start.sh
```

This sets up the environment on first run (creates a venv, installs
dependencies — safe to re-run, it skips setup if already done), starts the
web UI, and opens it in your browser at `http://127.0.0.1:5050`.

From there:

1. **Ingest a file** — upload any of the four source files (3 CSVs + the
   schedule PDF), in any order. Re-uploading a corrected file updates
   rather than duplicates.
2. **Open flags** — every inconsistency the system found, grouped by the
   person/record it's about, with a plain-language reason.
3. **Look up an employee** — search by name to see their status, linked
   license, and linked payroll/schedule records.
4. **Resolve a flag** — record a decision once you've reviewed one (copy
   its id from the flags list above).

Stop the server with `Ctrl+C`. To start over with a clean database, delete
`harborview.db` before running `./start.sh` again.

## Command line

The same functionality is available from the terminal, useful for
scripting or re-ingesting without a browser:

```bash
.venv/bin/python -m sot.cli --db harborview.db ingest /path/to/hr_roster.csv
.venv/bin/python -m sot.cli --db harborview.db ingest /path/to/licenses.csv
.venv/bin/python -m sot.cli --db harborview.db ingest /path/to/payroll.csv
.venv/bin/python -m sot.cli --db harborview.db ingest /path/to/schedule.pdf

.venv/bin/python -m sot.cli --db harborview.db flags
.venv/bin/python -m sot.cli --db harborview.db employee "Sofia Reyes"
.venv/bin/python -m sot.cli --db harborview.db resolve <flag_id> <your_name> "<what you decided>"
```

## Manual setup

If you'd rather not use `start.sh`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py        # web UI at http://127.0.0.1:5050
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Architecture

Four source files, two pairs. **HR + Licenses** combine into **Combined A**
(the authoritative roster: who's employed, what license they hold, whether
that license is currently valid). **Payroll + Schedule** combine into
**Combined B** (what they were actually paid and actually scheduled for),
which is then cross-checked against Combined A. Every disagreement anywhere
in this pipeline becomes a flag — grouped by entity, never silently dropped.

```
 1. HR roster (CSV)                3. Licenses (CSV)
 origin of Employee                origin of License
 (only source that can             (only source that can
  create a new employee)            create a new license)
        │                                  │
        └────────────────┬─────────────────┘
                          ▼
              ┌───────────────────────┐
              │      COMBINED A       │   resolver.attach_license
              │   (HR + Licenses)     │   + combiner.build_combined_a
              └───────────────────────┘
                          │
          • exact match on license_number
          • corroborate: HR name  vs  License's name_on_license
          • precedence: soonest(HR expiration, License expiration) wins
          • canonical display_name = HR's name, always
                          │
                          ▼
              ┌───────────────────────┐
              │   GATE / FLAG RULES   │   combiner.COMBINED_A_RULES
              └───────────────────────┘
          • license_needs_check   (gate)  → Employee.status:
                                             pending / active / blocked
          • role_matches_license  (flag)  → job_title vs. license_type
          • license_staleness     (flag)  → last_verified too old
                          │
                          ▼
            Employee.status, Employee.resolved_expiration
                          │
                          │  (read by Combined B below)
                          ▼
 2. Payroll (CSV)                  4. Staff Schedule (PDF)
 attaches to an Employee           attaches to an Employee
 (never originates one)            (never originates one;
                                     one PDF page = one facility)
        │                                  │
        └────────────────┬─────────────────┘
                          ▼
              ┌───────────────────────┐
              │      COMBINED B       │   resolver.attach_payroll_or_shift_fact
              │  (Payroll + Schedule) │
              └───────────────────────┘
                          │
          • fuzzy name match, scoped by facility, against Combined A's employees
          • corroborate: Payroll job_code  vs  Schedule Role
                          │
                          ▼
              ┌───────────────────────┐
              │  CROSS-VALIDATION vs. │   combiner.build_combined_b
              │     COMBINED A        │
              └───────────────────────┘
          • facility agreement (HR facility vs. payroll/schedule facility)
          • hours check: hours_paid  vs.  sum(ShiftAssignment.hours_by_day)
          • payroll_status:
              approved                         (license covers the whole period)
              held                             (license expired before the period)
              held + partial_period_license_lapse  (license expired mid-period)
                          │
                          ▼
              ┌───────────────────────┐
              │      flags table      │   one row per issue, grouped by
              │   (the review queue)  │   entity, plain-language reason
              └───────────────────────┘
                          ▲
                          │
          cascade_from_employee: when Combined A changes for someone
          (e.g. a license gets renewed), their already-linked Combined B
          facts are automatically re-checked — a renewal can clear a
          `held` payroll record without a new file being ingested.
```

**How it actually runs:** every call to `ingest()` (CLI or web UI) does one
adapter pass, then a full idempotent rescan — link whatever can now be
linked, rebuild Combined A for every employee, rebuild Combined B for every
linked fact. Order of file upload never matters; an employee without a
license yet just stays unlinked (flagged, never dropped) until the Licenses
file shows up, at which point the next ingest call's rescan picks it up
automatically.

**Why two combined tables instead of one big join:** HR+Licenses answer "is
this person valid to work" — a question about the person. Payroll+Schedule
answer "does what they were paid match what they actually did" — a question
about a specific pay period. Keeping them separate is what makes the
mid-period-license-lapse case expressible: an employee can be correctly
`blocked` as of a date while a specific payroll record for an earlier,
still-valid period stays `approved`.
