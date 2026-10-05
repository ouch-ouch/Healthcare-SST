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

## Architecture, in one paragraph

Four source adapters parse HR/Licenses/Payroll CSVs and the Schedule PDF
into a SQLite-backed entity/edge graph. A resolver links them by identity
(exact keys first, then fuzzy name matching with two-signal corroboration),
enforcing that only HR can originate a new employee and only the license
registry can originate a new license. A small gate/flag rule engine
validates the result — license expiration, role/license agreement, payroll
vs. schedule hours — and every violation becomes a flag with a
plain-language reason, grouped by entity for review. Nothing is ever
silently dropped or overwritten; ingestion always proceeds, linking is what
gets gated.
