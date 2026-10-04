# Harborview Source of Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ingestion, identity-resolution, and conflict-flagging system that turns Harborview's four messy source files into a queryable, trustworthy entity graph with an explicit human-review surface.

**Architecture:** A SQLite-backed entity/edge graph (`entities`, `edges`, `flags` tables) populated by four per-source adapters. A resolver enforces source authority and two-signal corroboration while building two materialized tables — Combined A (HR+Licenses) and Combined B (Payroll+Schedule) — each driving its own approval state machine (SST approval, Payroll approval) through a small gate/flag rule engine. A CLI is the ingestion and human-review surface.

**Tech Stack:** Python, `pandas`, `pdfplumber`, `rapidfuzz`, `sqlite3` (stdlib), `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-04-harborview-sot-design.md` — this plan implements that spec section by section; task notes reference section numbers (`§N`).

## Global Constraints

- Only the HR roster adapter may originate a new `Employee` entity; Licenses/Payroll/Schedule may only attach facts to an existing one (§3).
- Only the Licenses adapter may originate a new `License` entity; `license_number` is enforced unique and is a natural key, not the entity's primary key (§3).
- Ingestion never blocks: an unresolved fact is stored as `pending`/unlinked, never dropped (§3).
- Canonical display name on an Employee is always HR roster's name, independent of corroboration outcome (§7).
- License validity gate has no precedence or leniency once triggered: `blocked` is `blocked`, full stop (§7, §8).
- Every combination stage requires two independent signals to corroborate; a mismatch names the specific signal that disagreed and shows both values, not a generic ambiguity message (§3).
- No flag or merge is ever destructive; a merge is reversible by detaching the source fact (§3, §9).
- No timezone conversion — all schedule times are in one assumed timezone (§5).

## Review Focus

- **Facility written three different ways** (`"Harborview Bayside"` in HR, `"BYS"` in Payroll, a free-text page header in the Schedule PDF) must resolve to the same `Facility` entity, not just string-equality-fail into a flag every time. (Task 10)
- **Two employees with genuinely similar names at different facilities** (e.g. two Reyeses) must be disambiguated by the role-code corroboration signal, not silently merged into one entity. (Task 9)
- **A License row whose `license_number` has no matching HR employee at all** is an orphan on the License side, not just a Payroll/Schedule-side case — the spec's examples are all employee-side orphans, but the same gap exists in the other direction. (Task 5)
- **An auto-merge later found to be wrong** must actually be reversible end-to-end — detaching the source fact must restore it as its own candidate entity, not just flip a status flag. (Task 11)
- **The same file (or a corrected re-export of it) ingested twice** must not create duplicate entities, edges, or flags — the spec's re-entrant/cascade model implies this but never states it as its own rule, and a live judging session is exactly the situation where a file gets re-fed. (Task 13)

---

## Task 1: Database schema & graph accessor

**Files:**
- Create: `sot/db.py`
- Create: `sot/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `db.init_db(path: str) -> sqlite3.Connection`
- Produces: `graph.Entity` (dataclass: `id: str`, `type: str`, `attrs: dict`)
- Produces: `graph.create_entity(conn, type: str, attrs: dict) -> str`
- Produces: `graph.get_entity(conn, entity_id: str) -> Entity | None`
- Produces: `graph.update_entity_attrs(conn, entity_id: str, attrs: dict) -> None` (shallow-merges `attrs` into existing)
- Produces: `graph.find_entity(conn, type: str, **attr_filters) -> Entity | None` (exact-match lookup over JSON attrs)
- Produces: `graph.create_edge(conn, from_id: str, to_id: str, type: str, attrs: dict | None = None) -> None`
- Produces: `graph.neighbors(conn, entity_id: str, edge_type: str) -> list[Entity]`
- Produces: `graph.remove_edge(conn, from_id: str, to_id: str, type: str) -> None`

- [ ] **Step 1: Write failing tests for entity CRUD and neighbor lookup**

```python
def test_create_and_get_entity(conn):
    eid = create_entity(conn, "Employee", {"first_name": "Sofia"})
    e = get_entity(conn, eid)
    assert e.type == "Employee"
    assert e.attrs["first_name"] == "Sofia"

def test_update_entity_attrs_merges(conn):
    eid = create_entity(conn, "Employee", {"first_name": "Sofia"})
    update_entity_attrs(conn, eid, {"status": "active"})
    e = get_entity(conn, eid)
    assert e.attrs == {"first_name": "Sofia", "status": "active"}

def test_find_entity_by_attr(conn):
    create_entity(conn, "License", {"license_number": "RN-551203"})
    found = find_entity(conn, "License", license_number="RN-551203")
    assert found is not None

def test_neighbors_by_edge_type(conn):
    emp = create_entity(conn, "Employee", {})
    lic = create_entity(conn, "License", {"license_number": "RN-551203"})
    create_edge(conn, emp, lic, "holds_license")
    result = neighbors(conn, emp, "holds_license")
    assert len(result) == 1 and result[0].id == lic

def test_remove_edge(conn):
    emp = create_entity(conn, "Employee", {})
    lic = create_entity(conn, "License", {})
    create_edge(conn, emp, lic, "holds_license")
    remove_edge(conn, emp, lic, "holds_license")
    assert neighbors(conn, emp, "holds_license") == []
```

A `conn` pytest fixture in `tests/conftest.py` calls `init_db(":memory:")`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph.py -v`
Expected: FAIL (module `sot.graph` not found / functions undefined)

- [ ] **Step 3: Implement `sot/db.py` and `sot/graph.py`**

`init_db` creates three tables if absent: `entities(id TEXT PRIMARY KEY, type TEXT, attrs TEXT, created_at TEXT, updated_at TEXT)`, `edges(from_id TEXT, to_id TEXT, type TEXT, attrs TEXT, created_at TEXT)`, and the `flags` table from Task 2 (create it here too, since both tables are schema, not logic — Task 2 only adds the Python helpers around it). `attrs` is a JSON-serialized `TEXT` column (SQLite has no native JSONB; this is the direct SQLite equivalent of the spec's `attrs JSONB`, and the schema shape is unchanged if ported to Postgres later). `id` values are `str(uuid.uuid4())`. `find_entity` filters by loading candidates of the given `type` and comparing decoded `attrs` in Python (no JSON path querying needed at this data volume).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/db.py sot/graph.py tests/test_graph.py tests/conftest.py
git commit -m "feat: add entity/edge graph storage over SQLite"
```

---

## Task 2: Core models, flags store, rule engine

**Files:**
- Create: `sot/models.py`
- Create: `sot/flags.py`
- Create: `sot/rules.py`
- Test: `tests/test_flags.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `graph.Entity`, `graph.get_entity`, `graph.update_entity_attrs` (Task 1)
- Produces: `models.ENTITY_TYPES`, `models.EDGE_TYPES`, `models.FLAG_TYPES` (the eight flag type strings from spec §9), `models.SST_STATUSES = ("pending", "active", "blocked")`, `models.PAYROLL_STATUSES = ("approved", "held", "rejected")`
- Produces: `flags.Flag` (dataclass: `id, entity_id, flag_type, severity, reason, detail: dict, status, resolved_by, resolution, resolved_at, created_at`)
- Produces: `flags.create_flag(conn, entity_id: str, flag_type: str, severity: str, reason: str, detail: dict | None = None) -> str`
- Produces: `flags.open_flags_grouped_by_entity(conn) -> dict[str, list[Flag]]` (§11 entity-centric review)
- Produces: `flags.resolve_flag(conn, flag_id: str, resolved_by: str, resolution: str) -> None`
- Produces: `rules.Rule` (dataclass: `id: str`, `applies_to: str`, `type: Literal["gate","flag"]`, `check: Callable[[Entity, Connection], bool]`, `on_fail: dict`). `on_fail` always carries `flag_type: str`, `severity: str`, `reason: str` (a failing rule of either type always produces a flag, so these three are what `create_flag` needs); a `gate` rule's `on_fail` additionally carries `set_status: str`.
- Produces: `rules.evaluate(conn, entity: Entity, rule_list: list[Rule]) -> None` — on failure, always calls `flags.create_flag(conn, entity.id, on_fail["flag_type"], on_fail["severity"], on_fail["reason"])`; additionally calls `graph.update_entity_attrs(conn, entity.id, {"status": on_fail["set_status"]})` when `rule.type == "gate"`.

- [ ] **Step 1: Write failing tests**

```python
def test_create_flag_and_group_by_entity(conn):
    eid = create_entity(conn, "Employee", {})
    create_flag(conn, eid, "identity_ambiguity", "high", "name mismatch")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid in grouped
    assert grouped[eid][0].flag_type == "identity_ambiguity"
    assert grouped[eid][0].status == "open"

def test_resolve_flag_is_additive_not_overwrite(conn):
    eid = create_entity(conn, "Employee", {})
    fid = create_flag(conn, eid, "identity_ambiguity", "high", "name mismatch")
    resolve_flag(conn, fid, resolved_by="reviewer1", resolution="confirmed same person")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid not in grouped  # no longer open
    # original flag row still exists with its resolution recorded
    all_flags = get_all_flags_for_entity(conn, eid)  # test-only helper, or query directly
    assert all_flags[0].resolution == "confirmed same person"

def test_gate_rule_sets_status_on_failure(conn):
    eid = create_entity(conn, "Employee", {"license_expired": True})
    rule = Rule(id="r1", applies_to="Employee", type="gate",
                check=lambda e, c: not e.attrs["license_expired"],
                on_fail={"set_status": "blocked", "flag_type": "license_needs_check",
                         "severity": "high", "reason": "license expired"})
    evaluate(conn, get_entity(conn, eid), [rule])
    assert get_entity(conn, eid).attrs["status"] == "blocked"

def test_flag_rule_creates_flag_on_failure(conn):
    eid = create_entity(conn, "Employee", {"role": "RN", "license_type": "CNA"})
    rule = Rule(id="r2", applies_to="Employee", type="flag",
                check=lambda e, c: e.attrs["role"] == e.attrs["license_type"],
                on_fail={"flag_type": "attribute_disagreement", "severity": "medium",
                         "reason": "role does not match license type"})
    evaluate(conn, get_entity(conn, eid), [rule])
    grouped = open_flags_grouped_by_entity(conn)
    assert eid in grouped

def test_gate_rule_also_creates_a_flag(conn):
    eid = create_entity(conn, "Employee", {"license_expired": True})
    rule = Rule(id="r4", applies_to="Employee", type="gate",
                check=lambda e, c: not e.attrs["license_expired"],
                on_fail={"set_status": "blocked", "flag_type": "license_needs_check",
                         "severity": "high", "reason": "license expired"})
    evaluate(conn, get_entity(conn, eid), [rule])
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[eid][0].flag_type == "license_needs_check"

def test_rule_skipped_when_applies_to_does_not_match(conn):
    eid = create_entity(conn, "Facility", {})
    rule = Rule(id="r3", applies_to="Employee", type="flag",
                check=lambda e, c: False,  # would always fail if run
                on_fail={"flag_type": "attribute_disagreement", "severity": "low", "reason": "n/a"})
    evaluate(conn, get_entity(conn, eid), [rule])
    assert eid not in open_flags_grouped_by_entity(conn)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_flags.py tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/models.py`, `sot/flags.py`, `sot/rules.py`**

`flags` table (created in Task 1's `init_db`, or added here if not yet present — confirm against Task 1's schema rather than redefining it): `id, entity_id, flag_type, severity, reason, detail TEXT, status, resolved_by, resolution, resolved_at, created_at`. `open_flags_grouped_by_entity` selects `status='open'` and groups in Python with `itertools.groupby` or a plain dict accumulation. `evaluate` loops `rule_list`, skips rules whose `applies_to != entity.type`, calls `rule.check(entity, conn)`, and on a falsy result calls `create_flag(conn, entity.id, on_fail["flag_type"], on_fail["severity"], on_fail["reason"])` always, plus `update_entity_attrs(conn, entity.id, {"status": on_fail["set_status"]})` when `rule.type == "gate"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_flags.py tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/models.py sot/flags.py sot/rules.py tests/test_flags.py tests/test_rules.py
git commit -m "feat: add flags store and gate/flag rule engine"
```

---

## Task 3: HR roster adapter

**Files:**
- Create: `sot/adapters/__init__.py`
- Create: `sot/adapters/hr.py`
- Test: `tests/test_hr_adapter.py`
- Test fixtures: `tests/fixtures/hr_roster.csv`, `tests/fixtures/hr_roster_duplicate_id.csv`, `tests/fixtures/hr_roster_future_hire.csv`, `tests/fixtures/hr_roster_past_expiration.csv`

**Interfaces:**
- Consumes: `graph.create_entity`, `graph.find_entity` (Task 1); `flags.create_flag` (Task 2)
- Produces: `hr.IngestResult` (dataclass: `created: int`, `flagged: int`)
- Produces: `hr.ingest_hr_roster(conn, csv_path: str) -> IngestResult`

- [ ] **Step 1: Write failing tests**

```python
def test_ingest_creates_employee_entities(conn, tmp_hr_csv):
    result = ingest_hr_roster(conn, tmp_hr_csv)
    assert result.created == 2  # fixture has 2 rows
    e = find_entity(conn, "Employee", employee_id="E201")
    assert e.attrs["first_name"] == "Sofia"

def test_duplicate_employee_id_flagged_as_data_source_anomaly(conn):
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_duplicate_id.csv")
    grouped = open_flags_grouped_by_entity(conn)
    reasons = [f.flag_type for flags in grouped.values() for f in flags]
    assert "data_source_anomaly" in reasons

def test_future_hire_date_flagged(conn):
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_future_hire.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)

def test_license_expiration_in_past_flagged(conn):
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_past_expiration.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)
```

`tests/fixtures/hr_roster.csv` uses the two example rows from the spec's source brief (E201 Sofia Reyes, E202 Marcus Bell). The three invalid fixtures are single-row variants of it with one field violated each.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hr_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/adapters/hr.py`**

`ingest_hr_roster` reads the CSV with `pandas.read_csv`, runs the three §4 sanity checks per row (duplicate `employee_id` within the file, `license_expiration` not in the past, `hire_date` ≤ today — each violation calls `flags.create_flag(conn, entity_id, "data_source_anomaly", "medium", <specific reason text>)`, where `entity_id` is created even for a flagged row, since per Global Constraints nothing is dropped), then creates an `Employee` entity per row via `create_entity(conn, "Employee", {...all CSV columns..., "status": "pending"})`. A row whose `employee_id` collides with one already created in this same file still gets its own entity (duplicates are a data anomaly to surface, not a reason to silently drop the second row).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hr_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/adapters/hr.py tests/test_hr_adapter.py tests/fixtures/hr_roster*.csv
git commit -m "feat: add HR roster adapter with sanity checks"
```

---

## Task 4: Licenses adapter

**Files:**
- Create: `sot/adapters/licenses.py`
- Test: `tests/test_licenses_adapter.py`
- Test fixtures: `tests/fixtures/licenses.csv`, `tests/fixtures/licenses_past_expiration.csv`, `tests/fixtures/licenses_future_verified.csv`, `tests/fixtures/licenses_duplicate_number.csv`

**Interfaces:**
- Consumes: `graph.create_entity`, `graph.find_entity` (Task 1); `flags.create_flag` (Task 2)
- Produces: `licenses.ingest_licenses(conn, csv_path: str) -> hr.IngestResult` (imports `IngestResult` from `sot.adapters.hr`, where Task 3 defines it — the one place it's defined; every other adapter imports from there rather than redefining it)

- [ ] **Step 1: Write failing tests**

```python
def test_ingest_creates_license_entities(conn, tmp_licenses_csv):
    result = ingest_licenses(conn, tmp_licenses_csv)
    assert result.created == 2
    lic = find_entity(conn, "License", license_number="RN-551203")
    assert lic.attrs["license_type"] == "RN"

def test_expiration_in_past_flagged(conn):
    ingest_licenses(conn, "tests/fixtures/licenses_past_expiration.csv")
    assert any(f.flag_type == "data_source_anomaly"
               for fs in open_flags_grouped_by_entity(conn).values() for f in fs)

def test_last_verified_in_future_flagged(conn):
    ingest_licenses(conn, "tests/fixtures/licenses_future_verified.csv")
    assert any(f.flag_type == "data_source_anomaly"
               for fs in open_flags_grouped_by_entity(conn).values() for f in fs)

def test_duplicate_license_number_flagged(conn):
    ingest_licenses(conn, "tests/fixtures/licenses_duplicate_number.csv")
    assert any(f.flag_type == "data_source_anomaly"
               for fs in open_flags_grouped_by_entity(conn).values() for f in fs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_licenses_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/adapters/licenses.py`**

Mirrors Task 3's structure: `pandas.read_csv`, run §4 Licenses sanity checks (`expiration_date` in the future, `last_verified` in the past, `license_number` unique within the file), create a `License` entity per row regardless of flags.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_licenses_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/adapters/licenses.py tests/test_licenses_adapter.py tests/fixtures/licenses*.csv
git commit -m "feat: add Licenses adapter with sanity checks"
```

---

## Task 5: Combined A resolver — corroboration, precedence, SST gate

**Files:**
- Create: `sot/resolver.py` (Combined-A half only; Task 9 adds the Combined-B half to the same file)
- Create: `sot/combiner.py` (Combined-A half; Task 10 adds Combined-B)
- Test: `tests/test_resolver_combined_a.py`

**Interfaces:**
- Consumes: `graph.find_entity`, `graph.create_edge`, `graph.neighbors`, `graph.update_entity_attrs` (Task 1); `flags.create_flag` (Task 2); `rules.Rule`, `rules.evaluate` (Task 2); `models.SST_STATUSES` (Task 2)
- Produces: `resolver.attach_license(conn, employee_id: str) -> None` — finds the Employee's `license_number`, looks up the matching `License` entity via `find_entity`, creates a `holds_license` edge, and runs corroboration (below). If no `License` entity has that `license_number`, raises a `referential_orphan` flag on the Employee and does not create the edge.
- Produces: `resolver.corroborate_combined_a(conn, employee_id: str, license_id: str) -> None` — compares HR's `first_name`+`last_name` against the License's `name_on_license`; on disagreement, raises `identity_ambiguity` naming the signal (`"name"`) and both values.
- Produces: `combiner.build_combined_a(conn, employee_id: str) -> None` — applies the §7 precedence rules (soonest expiration date, canonical name = HR) by writing them onto the Employee's `attrs` (`resolved_expiration`, `display_name`), then runs the gate/flag rule list (below) via `rules.evaluate`.
- Produces: `combiner.COMBINED_A_RULES: list[Rule]` — three rules:
  - `license_needs_check` (gate): `check` is `resolved_expiration >= today`; `on_fail={"set_status": "blocked", "flag_type": "license_needs_check", "severity": "high", "reason": f"license expired {resolved_expiration}"}`.
  - `role_matches_license` (flag): HR `job_title` prefix vs. License `license_type` (e.g. `"Registered Nurse"` → `"RN"`, `"Certified Nursing Assistant"` → `"CNA"`, via a small static dict); `on_fail={"flag_type": "attribute_disagreement", "severity": "medium", "reason": "job_title does not match license_type"}`.
  - `license_staleness` (flag, §9's `staleness` type): the linked License's `last_verified` older than a 180-day policy window (a concrete default — the spec names the flag but not a threshold, so this is the value being pinned); `on_fail={"flag_type": "staleness", "severity": "low", "reason": f"license last verified {last_verified}, over 180 days ago"}`.

- [ ] **Step 1: Write failing tests**

```python
def test_attach_license_creates_edge_on_number_match(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "license_number": "RN-551203"})
    create_entity(conn, "License", {"license_number": "RN-551203", "name_on_license": "REYES, SOFIA",
                                     "expiration_date": "2027-05-31", "license_type": "RN"})
    attach_license(conn, emp)
    assert len(neighbors(conn, emp, "holds_license")) == 1

def test_license_not_found_raises_referential_orphan(conn):
    emp = create_entity(conn, "Employee", {"license_number": "RN-999999"})
    attach_license(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[emp][0].flag_type == "referential_orphan"

def test_corroboration_name_mismatch_flags_identity_ambiguity(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "license_number": "RN-551203"})
    lic = create_entity(conn, "License", {"license_number": "RN-551203", "name_on_license": "BELL, MARCUS"})
    corroborate_combined_a(conn, emp, lic)
    grouped = open_flags_grouped_by_entity(conn)
    f = grouped[emp][0]
    assert f.flag_type == "identity_ambiguity"
    assert "name" in f.reason

def test_combined_a_uses_soonest_expiration(conn):
    emp = create_entity(conn, "Employee", {"license_expiration": "2027-05-31"})
    lic = create_entity(conn, "License", {"expiration_date": "2026-12-31"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["resolved_expiration"] == "2026-12-31"

def test_combined_a_sets_display_name_from_hr(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes"})
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["display_name"] == "Sofia Reyes"

def test_blocked_when_resolved_expiration_in_past(conn, frozen_today):
    emp = create_entity(conn, "Employee", {"license_expiration": "2020-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2020-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["status"] == "blocked"
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[emp][0].flag_type == "license_needs_check"

def test_role_license_mismatch_flagged(conn):
    emp = create_entity(conn, "Employee", {"job_title": "Registered Nurse"})
    lic = create_entity(conn, "License", {"license_type": "CNA", "expiration_date": "2099-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "attribute_disagreement" for f in grouped[emp])

def test_stale_last_verified_flagged(conn, frozen_today):
    emp = create_entity(conn, "Employee", {"job_title": "Registered Nurse", "license_expiration": "2099-01-01"})
    lic = create_entity(conn, "License", {"license_type": "RN", "expiration_date": "2099-01-01",
                                           "last_verified": "2020-01-01"})  # far past the 180-day window
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "staleness" for f in grouped[emp])
```

(`frozen_today` is a `conftest.py` fixture freezing "today" via `freezegun` or a small monkeypatch, so expiration-date comparisons are deterministic.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resolver_combined_a.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/resolver.py` (Combined-A functions) and `sot/combiner.py` (Combined-A functions)**

`attach_license` reads the Employee's `license_number` attr, calls `find_entity(conn, "License", license_number=...)`; if found, creates the edge and calls `corroborate_combined_a`; if not, raises the orphan flag. `build_combined_a` reads the Employee's and its linked License's attrs, picks `min(hr_expiration, license_expiration)` as `resolved_expiration`, sets `display_name = f"{first_name} {last_name}"`, writes both via `update_entity_attrs`, then calls `rules.evaluate(conn, get_entity(conn, employee_id), COMBINED_A_RULES)` once per rule in the list (Task 2's `evaluate` signature already takes the whole list and handles flag+status creation itself — no changes to Task 2's code needed here).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resolver_combined_a.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/resolver.py sot/combiner.py sot/rules.py tests/test_resolver_combined_a.py tests/conftest.py
git commit -m "feat: add Combined A resolver with corroboration, precedence, and SST gate"
```

---

## Task 6: Payroll adapter

**Files:**
- Create: `sot/adapters/payroll.py`
- Test: `tests/test_payroll_adapter.py`
- Test fixtures: `tests/fixtures/payroll.csv`, `tests/fixtures/payroll_future_period.csv`

**Interfaces:**
- Consumes: `graph.create_entity` (Task 1); `flags.create_flag` (Task 2)
- Produces: `payroll.ingest_payroll(conn, csv_path: str) -> hr.IngestResult`

- [ ] **Step 1: Write failing tests**

```python
def test_ingest_creates_payroll_record_entities(conn, tmp_payroll_csv):
    result = ingest_payroll(conn, tmp_payroll_csv)
    assert result.created == 2
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs["employee_name"] == "REYES, SOFIA"

def test_future_period_flagged(conn):
    ingest_payroll(conn, "tests/fixtures/payroll_future_period.csv")
    assert any(f.flag_type == "data_source_anomaly"
               for fs in open_flags_grouped_by_entity(conn).values() for f in fs)

def test_payroll_record_starts_unlinked(conn, tmp_payroll_csv):
    ingest_payroll(conn, tmp_payroll_csv)
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs.get("employee_id") is None  # not yet attached to an Employee
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_payroll_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/adapters/payroll.py`**

Same shape as Tasks 3–4: `pandas.read_csv`, §4 sanity check (`period_start`/`period_end` both in the past), create a `PayrollRecord` entity per row (not an Employee — per Global Constraints, Payroll is attach-only; linking to an Employee happens in Task 9, this task only ingests and stores the raw fact).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_payroll_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/adapters/payroll.py tests/test_payroll_adapter.py tests/fixtures/payroll*.csv
git commit -m "feat: add Payroll adapter (attach-only facts)"
```

---

## Task 7: Schedule adapter — PDF extraction & facility resolution

**Files:**
- Create: `sot/adapters/schedule.py`
- Test: `tests/test_schedule_extraction.py`
- Test fixture: `tests/fixtures/schedule_sample.pdf`, `tests/fixtures/schedule_unknown_facility.pdf` (generate both with a short `tests/fixtures/make_schedule_pdfs.py` script using `reportlab`, run once to produce the committed PDF fixtures — see note in Step 3)

**Interfaces:**
- Consumes: `graph.find_entity`, `graph.create_entity` (Task 1); `flags.create_flag` (Task 2)
- Produces: `schedule.PageTable` (dataclass: `facility_name: str | None`, `rows: list[dict]`, `raw_text: str`)
- Produces: `schedule.extract_pages(pdf_path: str) -> list[PageTable]` — one `PageTable` per PDF page, `facility_name` is the matched Facility name found in the page text or `None` if none resolves.
- Produces: `schedule.store_schedule_batch(conn, page: PageTable) -> None` — if `page.facility_name` resolves to a known `Facility` entity (via `find_entity(conn, "Facility", name=...)`), stores each row as a `ShiftAssignment` entity with `attrs["facility_id"]` set and `attrs["batch_status"] = "linked"`; if it does not resolve, still stores each row as a `ShiftAssignment` entity (raw capture, per Global Constraints) but with `attrs["batch_status"] = "held"` and raises one `identity_ambiguity`-adjacent flag — use `data_source_anomaly` with a reason naming the unresolved facility text, since this is a sanity-stage problem with the page itself, not a cross-source conflict — on the first row of that page (one flag per held page, not one per row, to avoid flooding the review queue with duplicates of the same underlying problem).

- [ ] **Step 1: Write failing tests**

```python
def test_extract_pages_finds_known_facility(conn, seeded_facilities):
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    assert pages[0].facility_name == "Harborview Bayside"
    assert len(pages[0].rows) > 0

def test_unresolvable_facility_holds_batch(conn, seeded_facilities):
    pages = extract_pages("tests/fixtures/schedule_unknown_facility.pdf")
    store_schedule_batch(conn, pages[0])
    shifts = [e for e in all_entities_of_type(conn, "ShiftAssignment")]
    assert all(s.attrs["batch_status"] == "held" for s in shifts)
    grouped = open_flags_grouped_by_entity(conn)
    anomaly_flags = [f for fs in grouped.values() for f in fs if f.flag_type == "data_source_anomaly"]
    assert len(anomaly_flags) == 1  # one flag for the whole page, not per row

def test_known_facility_links_batch(conn, seeded_facilities):
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    store_schedule_batch(conn, pages[0])
    shifts = [e for e in all_entities_of_type(conn, "ShiftAssignment")]
    assert all(s.attrs["batch_status"] == "linked" for s in shifts)
```

`seeded_facilities` is a `conftest.py` fixture that creates `Facility` entities for "Harborview Bayside" and "Harborview Riverdale" before the test body runs. `all_entities_of_type` is a small test-only helper added to `tests/conftest.py` (`SELECT * FROM entities WHERE type = ?`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schedule_extraction.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/adapters/schedule.py` and the PDF fixtures**

Use `pdfplumber.open(pdf_path)`, iterate `page.extract_text()` to find a facility name (match against known `Facility` entity names, case-insensitively, anywhere in the page's text) and `page.extract_table()` for the staff/day grid. Build `tests/fixtures/make_schedule_pdfs.py` as a one-off script (using `reportlab`'s `SimpleDocTemplate` and `Table`) that renders the two example rows from the spec's brief (Sofia Reyes / Marc Bell) into a page headed "Harborview Bayside", and a second fixture headed with a facility name that matches nothing (e.g. "Unit 7"); run it once locally to produce the two committed PDF files — the script itself is not part of the shipped package, only its output is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schedule_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/adapters/schedule.py tests/test_schedule_extraction.py tests/fixtures/schedule_sample.pdf tests/fixtures/schedule_unknown_facility.pdf tests/fixtures/make_schedule_pdfs.py tests/conftest.py
git commit -m "feat: add Schedule PDF extraction with facility batch-hold gating"
```

---

## Task 8: Schedule adapter — shift time conversion & daily hours

**Files:**
- Modify: `sot/adapters/schedule.py`
- Test: `tests/test_schedule_hours.py`

**Interfaces:**
- Consumes: `schedule.PageTable` (Task 7)
- Produces: `schedule.parse_shift_cell(cell_text: str) -> tuple[str, str] | None` — returns `(start_24h, end_24h)` as `"HH:MM"` strings, or `None` for `"OFF"`.
- Produces: `schedule.compute_daily_hours(start_24h: str, end_24h: str) -> float` — handles overnight wraparound (e.g. `"23:00"`–`"07:00"` → `8.0`).
- Produces: `schedule.annotate_daily_hours(page: PageTable) -> PageTable` — returns a new `PageTable` whose `rows` each gain an `hours_by_day: dict[str, float]` key, computed from the existing day columns; a day with `"OFF"` contributes `0.0`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("cell,expected", [
    ("7a-3p", ("07:00", "15:00")),
    ("3p-11p", ("15:00", "23:00")),
    ("11p-7a", ("23:00", "07:00")),
    ("7a-7p", ("07:00", "19:00")),
    ("OFF", None),
])
def test_parse_shift_cell(cell, expected):
    assert parse_shift_cell(cell) == expected

@pytest.mark.parametrize("start,end,expected", [
    ("07:00", "15:00", 8.0),
    ("23:00", "07:00", 8.0),   # overnight wraparound
    ("07:00", "19:00", 12.0),
])
def test_compute_daily_hours(start, end, expected):
    assert compute_daily_hours(start, end) == expected

def test_annotate_daily_hours_handles_off():
    page = PageTable(facility_name="Harborview Bayside",
                      rows=[{"staff": "Marcus Bell", "role": "CNA",
                             "Mon 09/14": "3p-11p", "Tue 09/15": "OFF"}],
                      raw_text="")
    annotated = annotate_daily_hours(page)
    hours = annotated.rows[0]["hours_by_day"]
    assert hours["Mon 09/14"] == 8.0
    assert hours["Tue 09/15"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schedule_hours.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the three functions in `sot/adapters/schedule.py`**

`parse_shift_cell` splits on `-`, converts each half from `"7a"`/`"3p"`/`"11p"` style to 24h via a small am/pm parse (strip trailing `a`/`p`, `int(hour)`, `+12` if `p` and hour != 12). `compute_daily_hours` converts both to minutes-since-midnight and takes `(end - start) % (24*60) / 60`, which naturally handles overnight wraparound. Cross-check against the page's legend note (if present in `raw_text`, e.g. `"7a-3p... are 8 hours"`) only as a sanity assertion in a log/flag, not a hard requirement — the computed duration is authoritative per §5.3, the legend is a secondary sanity signal.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schedule_hours.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/adapters/schedule.py tests/test_schedule_hours.py
git commit -m "feat: add shift time conversion and daily hours computation"
```

---

## Task 9: Combined B resolver — identity against Combined A

**Files:**
- Modify: `sot/resolver.py`
- Test: `tests/test_resolver_combined_b.py`

**Interfaces:**
- Consumes: `graph.find_entity`, `graph.create_edge`, `graph.update_entity_attrs` (Task 1); `flags.create_flag` (Task 2); `rapidfuzz.fuzz.token_sort_ratio` (external)
- Produces: `resolver.resolve_payroll_employee(conn, payroll_record_id: str) -> str | None` — fuzzy-matches the record's `employee_name` + facility against `active`/`pending` Employee entities built by Task 5; returns the matched `employee_id` or `None`.
- Produces: `resolver.resolve_schedule_employee(conn, shift_assignment_id: str) -> str | None` — same, using the `ShiftAssignment`'s `staff` name, scoped to its linked `facility_id`.
- Produces: `resolver.corroborate_combined_b(conn, employee_id: str, role_code_a: str, role_code_b: str) -> bool` — direct equality check (Payroll `job_code` vs. Schedule `Role`); on mismatch raises `identity_ambiguity` naming `"role_code"` and both values, returns `False`; returns `True` on match.
- Produces: `resolver.attach_payroll_or_shift_fact(conn, fact_entity_id: str, fact_type: Literal["PayrollRecord","ShiftAssignment"]) -> None` — orchestrates: resolve → if `None`, flag `referential_orphan` and leave `attrs["employee_id"]` unset (stays pending); if matched, set `attrs["employee_id"]`, create the `paid_for`/`worked_shift` edge, and run `corroborate_combined_b` when a role-code pair is available for this fact.

- [ ] **Step 1: Write failing tests**

```python
def test_resolve_payroll_employee_fuzzy_match(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA",
                                                "facility_code": "BYS"})
    matched = resolve_payroll_employee(conn, pr)
    assert matched == emp

def test_similar_names_different_facility_not_confused(conn):
    reyes_bayside = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                                       "facility": "Harborview Bayside", "status": "active"})
    reyes_riverdale = create_entity(conn, "Employee", {"first_name": "Sara", "last_name": "Reyes",
                                                         "facility": "Harborview Riverdale", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA", "facility_code": "BYS"})
    assert resolve_payroll_employee(conn, pr) == reyes_bayside

def test_no_match_returns_none(conn):
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "NOBODY, NOONE", "facility_code": "BYS"})
    assert resolve_payroll_employee(conn, pr) is None

def test_role_code_mismatch_flags_identity_ambiguity(conn):
    emp = create_entity(conn, "Employee", {})
    corroborate_combined_b(conn, emp, "RN", "CNA")
    grouped = open_flags_grouped_by_entity(conn)
    assert "role_code" in grouped[emp][0].reason

def test_attach_payroll_fact_sets_pending_on_no_match(conn):
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "NOBODY, NOONE", "facility_code": "BYS"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs.get("employee_id") is None
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[pr][0].flag_type == "referential_orphan"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resolver_combined_b.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the Combined-B functions in `sot/resolver.py`**

`resolve_payroll_employee`/`resolve_schedule_employee` pull all `Employee` entities (any status — a payroll fact can arrive before SST approval finishes), filter to the same facility (normalize `facility_code`/`facility_name` via the lookup table from Task 10's facility normalization — if Task 10 hasn't run yet in implementation order, inline a minimal `{"BYS": "Harborview Bayside", "RVD": "Harborview Riverdale"}` map here and have Task 10 reuse it rather than duplicating it), score each candidate's `"{first_name} {last_name}"` against the fact's name with `rapidfuzz.fuzz.token_sort_ratio` (handles the `"LASTNAME, FIRSTNAME"` vs. `"Firstname Lastname"` order difference), and return the top match if its score clears a threshold (e.g. 85), else `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resolver_combined_b.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/resolver.py tests/test_resolver_combined_b.py
git commit -m "feat: add Combined B resolver with fuzzy match and role-code corroboration"
```

---

## Task 10: Cross-table validation, Payroll approval, cascade

**Files:**
- Modify: `sot/combiner.py`
- Create: `sot/facilities.py` (the normalization lookup, shared by Task 9 and here)
- Test: `tests/test_combined_b_validation.py`
- Test: `tests/test_cascade.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9
- Produces: `facilities.normalize_facility(raw: str) -> str | None` — maps `"BYS"`, `"Harborview Bayside"`, and page-header text to a single canonical facility name (or `None` if unrecognized); used by Task 9's resolver and here.
- Produces: `combiner.build_combined_b(conn, fact_entity_id: str, fact_type: Literal["PayrollRecord","ShiftAssignment"]) -> None` — if `attrs["employee_id"]` is unset, does nothing (already flagged as orphan by Task 9). Otherwise: checks facility agreement via `normalize_facility`, checks hours consistency (`PayrollRecord.hours_paid` vs. the sum of that employee's `ShiftAssignment.hours_by_day` for the same period) raising `business_rule_violation` on mismatch, and computes Payroll approval status per §8:
  - employee's `resolved_expiration` (Task 5) is after the whole pay period → `approved`
  - employee `status == "blocked"` for the whole period → `held`, flag `license_needs_check` reason already present from Task 5, no new flag needed here
  - period start is before and period end is after `resolved_expiration` (straddles the lapse) → `held`, flag `partial_period_license_lapse`
- Produces: `combiner.cascade_from_employee(conn, employee_id: str) -> None` — after `build_combined_a` changes an Employee's status, re-fetches every `PayrollRecord`/`ShiftAssignment` linked via `paid_for`/`worked_shift` whose `attrs["payroll_status"]` is `held` or unset, and re-runs `build_combined_b` on each.

- [ ] **Step 1: Write failing tests**

```python
def test_normalize_facility_matches_code_and_name():
    assert normalize_facility("BYS") == "Harborview Bayside"
    assert normalize_facility("Harborview Bayside") == "Harborview Bayside"
    assert normalize_facility("Unit 7") is None

def test_facility_mismatch_flags_business_rule_violation(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "active",
                                            "resolved_expiration": "2099-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "RVD",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "business_rule_violation" for f in grouped[pr])

def test_hours_mismatch_flagged(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "active",
                                            "resolved_expiration": "2099-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 50})
    create_entity(conn, "ShiftAssignment", {"employee_id": emp,
                                             "hours_by_day": {"Mon": 8, "Tue": 8}})  # 16, not 50
    build_combined_b(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "business_rule_violation" for f in grouped[pr])

def test_fully_blocked_period_is_held(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2020-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"

def test_mid_week_lapse_flagged_partial(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2026-09-17"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "partial_period_license_lapse" for f in grouped[pr])

def test_cascade_unblocks_held_payroll_on_license_renewal(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2020-01-01",
                                            "license_expiration": "2020-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2020-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"

    # license renewed
    update_entity_attrs(conn, lic, {"expiration_date": "2099-01-01"})
    update_entity_attrs(conn, emp, {"license_expiration": "2099-01-01"})
    build_combined_a(conn, emp)
    cascade_from_employee(conn, emp)

    assert get_entity(conn, pr).attrs["payroll_status"] == "approved"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_combined_b_validation.py tests/test_cascade.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/facilities.py` and the two `combiner.py` functions**

`normalize_facility` is a static dict plus a case-insensitive substring check against known canonical names. `build_combined_b` reads the fact and its linked Employee via `attrs["employee_id"]`, runs the three checks described in the Interfaces block in order (facility, hours, then the three-way period/expiration comparison for `payroll_status`), writing `payroll_status` via `update_entity_attrs`. `cascade_from_employee` queries edges of type `paid_for`/`worked_shift` pointing away from the employee (reuse `graph.neighbors` with the employee as `from_id`, or add a symmetric lookup if the edge direction stored in Task 9 points the other way — keep edge direction consistent with whatever Task 9 chose, since this task's query depends on it) and calls `build_combined_b` on each.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_combined_b_validation.py tests/test_cascade.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/facilities.py sot/combiner.py tests/test_combined_b_validation.py tests/test_cascade.py
git commit -m "feat: add cross-table validation, Payroll approval, and cascade re-check"
```

---

## Task 11: Merge reversal (unmerge)

**Files:**
- Modify: `sot/resolver.py`
- Test: `tests/test_unmerge.py`

**Interfaces:**
- Consumes: `graph.remove_edge`, `graph.create_entity`, `graph.get_entity` (Task 1); `flags.resolve_flag` (Task 2)
- Produces: `resolver.unmerge(conn, from_id: str, to_id: str, edge_type: str) -> str` — removes the edge, copies the detached fact's own attrs into a brand-new standalone entity of the appropriate type (inferred from `edge_type`: `paid_for`→`PayrollRecord`, `worked_shift`→`ShiftAssignment`, `holds_license`→`License`), clears the stale `employee_id`/linkage attrs on the original fact entity if present, and returns the new entity's id. The original two entities are never deleted.

- [ ] **Step 1: Write failing tests**

```python
def test_unmerge_detaches_without_deleting_either_entity(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "hours_paid": 36})
    create_edge(conn, emp, pr, "paid_for")

    new_id = unmerge(conn, emp, pr, "paid_for")

    assert get_entity(conn, emp) is not None
    assert get_entity(conn, pr) is not None
    assert neighbors(conn, emp, "paid_for") == []
    assert get_entity(conn, new_id).attrs["hours_paid"] == 36

def test_unmerge_clears_employee_id_on_original_fact(conn):
    emp = create_entity(conn, "Employee", {})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp})
    create_edge(conn, emp, pr, "paid_for")
    unmerge(conn, emp, pr, "paid_for")
    assert get_entity(conn, pr).attrs.get("employee_id") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_unmerge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `resolver.unmerge`**

Map `edge_type` to the target entity type with a small dict (`{"paid_for": "PayrollRecord", "worked_shift": "ShiftAssignment", "holds_license": "License"}`). Copy `get_entity(conn, to_id).attrs` minus the `employee_id` key into a `create_entity(conn, <mapped_type>, <copied attrs>)` call, call `graph.remove_edge`, then `update_entity_attrs(conn, to_id, {"employee_id": None})` on the original fact entity so it reads as unlinked again, matching how Tasks 3/6/9 represent "not yet attached."

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_unmerge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/resolver.py tests/test_unmerge.py
git commit -m "feat: add reversible unmerge for mistaken identity links"
```

---

## Task 12: CLI

**Files:**
- Create: `sot/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: all adapters (Tasks 3, 4, 6, 7+8), `resolver` (Tasks 5, 9, 11), `combiner` (Tasks 5, 10), `flags.open_flags_grouped_by_entity` (Task 2)
- Produces: `cli.ingest(conn, file_path: str) -> None` — dispatches on file extension (`.csv` with a filename/header sniff to pick HR vs. Payroll vs. Licenses; `.pdf` → schedule), running the matching adapter and then (for the sources that attach to an Employee) the corresponding resolver + combiner calls.
- Produces: `cli.list_open_flags(conn) -> str` — formats `open_flags_grouped_by_entity` into one block of text per entity.
- Produces: `cli.show_employee(conn, name: str) -> str` — fuzzy-looks up an Employee by name, prints its SST status, linked License, and any linked Payroll/Schedule facts with their Payroll approval status.
- Produces: `cli.resolve_flag_cmd(conn, flag_id: str, resolved_by: str, resolution: str) -> None` — thin wrapper over `flags.resolve_flag`.
- Produces: a `if __name__ == "__main__":` block using `argparse` with subcommands `ingest <path>`, `flags`, `employee <name>`, `resolve <flag_id> <resolved_by> <resolution>`.

- [ ] **Step 1: Write failing tests**

```python
def test_ingest_dispatches_hr_csv_by_header(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    assert find_entity(conn, "Employee", employee_id="E201") is not None

def test_ingest_dispatches_licenses_csv_by_header(conn, tmp_licenses_csv):
    ingest(conn, tmp_licenses_csv)
    assert find_entity(conn, "License", license_number="RN-551203") is not None

def test_ingest_payroll_runs_resolver_and_combiner(conn, tmp_hr_csv, tmp_payroll_csv):
    ingest(conn, tmp_hr_csv)
    ingest(conn, tmp_payroll_csv)
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs.get("payroll_status") is not None  # Combined B ran, not left unresolved

def test_list_open_flags_groups_by_entity(conn, tmp_hr_csv):
    ingest(conn, "tests/fixtures/hr_roster_duplicate_id.csv")
    output = list_open_flags(conn)
    assert "data_source_anomaly" in output

def test_show_employee_reports_status(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    output = show_employee(conn, "Sofia Reyes")
    assert "status" in output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `sot/cli.py`**

CSV dispatch: read the header row only; match against the known column sets from the spec (`employee_id,first_name,...` → HR; `license_number,name_on_license,...` → Licenses; `payroll_id,employee_name,...` → Payroll). PDF dispatch: always Schedule, calling Task 7/8's `extract_pages` → `annotate_daily_hours` → `store_schedule_batch` per page. After any adapter that produces Employee-linked facts (Licenses, Payroll, Schedule), call the matching resolver `attach_*`/`resolve_*` function and then `build_combined_a`/`build_combined_b` for each newly touched entity — this is the orchestration glue the adapters themselves don't do, since Tasks 3–9 were written to be independently testable without assuming a particular caller.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sot/cli.py tests/test_cli.py
git commit -m "feat: add CLI for ingest, flag review, and employee lookup"
```

---

## Task 13: End-to-end fixtures, idempotency, and full-pipeline test

**Files:**
- Create: `tests/test_end_to_end.py`
- Test fixtures: reuse all fixtures from Tasks 3, 4, 6, 7, 8; add `tests/fixtures/hr_roster_corrected.csv` (same `employee_id`s as `hr_roster.csv`, one field changed, for the idempotency test)

**Interfaces:**
- Consumes: `cli.ingest` (Task 12) and all adapters/resolver/combiner functions as a black box

- [ ] **Step 1: Write failing tests**

```python
def test_full_pipeline_four_sources_resolve_cleanly(conn):
    for f in ["tests/fixtures/hr_roster.csv", "tests/fixtures/licenses.csv",
              "tests/fixtures/payroll.csv", "tests/fixtures/schedule_sample.pdf"]:
        ingest(conn, f)
    emp = find_entity(conn, "Employee", employee_id="E201")
    assert emp.attrs["status"] in ("active", "pending", "blocked")  # resolved to *some* real status, not crashed
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs["payroll_status"] is not None

def test_reingesting_same_hr_file_does_not_duplicate_employee(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    ingest(conn, tmp_hr_csv)  # same file, fed twice
    all_e201 = [e for e in all_entities_of_type(conn, "Employee") if e.attrs.get("employee_id") == "E201"]
    assert len(all_e201) == 1

def test_corrected_reexport_updates_not_duplicates(conn):
    ingest(conn, "tests/fixtures/hr_roster.csv")
    ingest(conn, "tests/fixtures/hr_roster_corrected.csv")
    all_e201 = [e for e in all_entities_of_type(conn, "Employee") if e.attrs.get("employee_id") == "E201"]
    assert len(all_e201) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_end_to_end.py -v`
Expected: FAIL (the idempotency tests fail first — no task so far checks for an existing `employee_id` before creating)

- [ ] **Step 3: Make the HR and Licenses adapters idempotent on their natural key**

Modify `sot/adapters/hr.py`'s per-row logic (Task 3) to call `find_entity(conn, "Employee", employee_id=row["employee_id"])` before `create_entity`; if found, `update_entity_attrs` instead of creating a new entity (this is an update to Task 3's file, done here because the need for it — the idempotency requirement — surfaces at the full-pipeline level, not from Task 3's own fixtures). Apply the same pattern to `sot/adapters/licenses.py`'s `license_number` lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tasks' tests, no regressions)

- [ ] **Step 6: Commit**

```bash
git add tests/test_end_to_end.py tests/fixtures/hr_roster_corrected.csv sot/adapters/hr.py sot/adapters/licenses.py
git commit -m "feat: make HR/Licenses ingestion idempotent; add end-to-end pipeline test"
```
