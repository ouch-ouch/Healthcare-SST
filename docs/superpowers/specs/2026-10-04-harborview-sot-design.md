# Harborview Source of Truth — Design Spec

**Date:** 2026-10-04
**Context:** Pulse Foundry hiring hackathon. Challenge: build a central source of truth (SoT) for Harborview Care Group, a fictional operator of two skilled nursing facilities (Bayside, Riverdale), ingesting four messy, disagreeing data sources (HR roster, payroll, licenses, staff schedule) and surfacing anything wrong, inconsistent, or needing a human. Unseen real files are fed in live during judging. Design should also generalize to a different Pulse Foundry client/industry.

## 1. Goals / non-goals

**Goals**
- Resolve the same real-world entity (employee, facility, license) across four differently-formatted sources.
- Never lose or silently drop ingested data, even when it can't yet be resolved or trusted.
- Surface every inconsistency as a flag with a plain-language reason, not a silent failure.
- Enforce real business/safety constraints (e.g., no pay without a verified license) as hard gates, distinct from advisory flags.
- Keep the schema and rule mechanism additive, so a different industry's entities/rules can be added without migrating existing ones.

**Non-goals**
- Not building the downstream applications that consume the SoT (referral routing, state reporting UI) — only the SoT and evidence it would support them.
- Not handling multi-timezone facilities, OCR for scanned PDFs, or real-time/streaming ingestion — none are implied by the brief.

## 2. Data model

Entity graph, stored relationally (SQLite for the hackathon; schema ports unchanged to Postgres if real multi-client concurrency is ever needed):

```
entities (id UUID PK, type TEXT, attrs JSONB, created_at, updated_at)
edges    (from_id UUID, to_id UUID, type TEXT, attrs JSONB, created_at)
```

Entity types: `Employee`, `Facility`, `License`, `PayrollRecord`, `ShiftAssignment`.
Edge types: `employed_at`, `holds_license`, `paid_for`, `worked_shift`.

No dedicated graph database engine. Every rule in this system is a 1–2 hop lookup from an entity to its direct neighbors (e.g. Employee → License); nothing requires unbounded-depth traversal or transitive inference, so a native graph engine (Neo4j, etc.) buys traversal performance this system never exercises, while costing a second piece of infrastructure and weaker support for the tabular/aggregate reporting the business problems actually need (e.g. the quarterly state staffing report).

No OWL/RDF/reasoner. All checks are direct comparisons between already-linked records (single-hop), not facts derived by chaining relationships. A reasoner would be solving a problem this system doesn't have.

## 3. Identity resolution

- **Only HR roster can originate a new `Employee` entity.** Licenses, Payroll, and Schedule facts can only attach to an Employee that already exists — mirrors the real constraint that a person can't be paid or scheduled without being a registered employee.
- **License is the only source permitted to originate a `License` entity**, with its `license_number` enforced unique (natural key). A separate internal UUID is the entity's actual primary key — `license_number` is an external business key, not guaranteed stable as a PK.
- **Resolution order**: HR + Licenses first (exact match: `license_number`), then Payroll (fuzzy name + facility), then Schedule (weakest signal: name only), each resolving against the entity set the prior step confirmed — not all four sources matched against each other simultaneously.
- **Matching**: exact key match first; `rapidfuzz`, scoped to facility, for fuzzy name matching. Matches below a confidence threshold are not auto-merged — they raise an `identity ambiguity` flag.
- **Corroboration**: at both combination stages, identity is confirmed by two *independent* signals that must agree, not one:
  - **Combined A (HR + Licenses)**: `license_number` (HR's field vs. the registry's own) **and** name (HR `first_name`+`last_name` vs. License `name_on_license`).
  - **Combined B (Payroll + Schedule)**, resolved against Combined A: name (Payroll's `LASTNAME, FIRSTNAME` vs. Schedule's `Firstname Lastname`, fuzzy) **and** role code (Payroll `job_code` vs. Schedule `Role` — same vocabulary, e.g. `RN`/`CNA`, so this is a direct equality check, no mapping needed).
  - If both signals agree → confident match, no flag. If they disagree, the flag names *which* signal broke and shows both values — "license number matched but the name on the license says someone else" is a materially different, more urgent problem than "same person, name just formatted differently," and collapsing both into a generic ambiguity flag would hide that distinction.
  - A borderline-but-passing corroboration (e.g. a fuzzy name score just above threshold) is tagged on the entity as resolution confidence, carried forward per §11.
- **Facts that don't resolve are never dropped.** An unmatched Payroll/Schedule row is stored as a `pending`, unlinked fact. Ingestion is never blocked waiting for identity resolution; only the *linking* of a fact to a confirmed entity is conditional.

## 4. Per-file sanity checks (before any cross-source matching)

Run immediately on each file, independent of resolution. Violations raise a `data_source_anomaly` flag (a source-system data-quality signal, not a cross-reference conflict) and do not block the row from being stored.

- **HR roster**: no duplicate `employee_id` within the file · `license_expiration` not in the past · `hire_date` ≤ today.
- **Payroll**: `period_start` and `period_end` both in the past.
- **Licenses**: `expiration_date` in the future · `last_verified` in the past · `license_number` unique across the file.

## 5. Staff Schedule transform (separate pipeline)

The schedule PDF needs a full transform, not just validation, before it can be compared to anything else:

1. Extract the facility name from each page's text; one page = one facility (structural guarantee). If a page's facility doesn't resolve to a known Facility entity, **the entire page's batch is held** — hard block, no auto-resolution, human-in-the-loop required to confirm before anything on that page proceeds. (The raw extracted rows are still stored; only linking into the graph is gated — same "store always, link conditionally" principle, applied at page granularity because facility is the partition key for everything else on the page.)
2. Convert shift cell text to 24-hour format. No timezone conversion — all times are assumed to be in the same single timezone; this is a deliberate simplification, not an oversight (no facility described in the brief implies multiple timezones).
3. Compute total hours per person per day as a new column, parsed from the actual cell text (not hardcoded to the two example shift codes) and cross-checked against the legend note at the bottom of the page as an additional sanity signal.
4. `OFF` → 0 hours, explicit.

## 6. Combined tables

Two materialized views over the entity graph, rebuilt incrementally per affected person as facts change:

- **Combined A (HR + Licenses)**: the authoritative roster. Identity-resolved, with precedence rules applied (§7). Drives **SST approval** (§8).
- **Combined B (Payroll + Schedule)**: resolved against Combined A (never against raw HR), carrying computed hours. Drives **Payroll approval** (§8), cross-checked against Combined A.

**Trigger model**: a new/changed HR or License fact re-runs Combined A construction and gate/flag rules for that person only. A new/changed Payroll or Schedule fact re-runs Combined B for that person only. A Combined A status change (e.g. a license renewal) cascades: re-checks any `held`/`pending` Combined B rows for that person, so resolution can unblock previously-held payroll without a new file arriving.

## 7. Precedence rules (Combined A)

Precedence only applies where two sources disagree on a single fact that must resolve to one canonical value. Discrepancies with no "correct" answer (e.g. `hours_paid` vs. computed schedule hours) are never auto-resolved — they stay as business-rule-violation flags for a human.

| Fact | Rule |
|---|---|
| License expiration date | Use the **soonest** (most conservative) of HR's `license_expiration` and the registry's `expiration_date`. |
| Facility assignment | Cross-check HR `facility`, Payroll `facility_code`, and the Schedule page's facility. Unresolved → hard block per §5, no precedence, HITL required. |
| License number | Treated as a natural unique key (§3) — collisions are a sanity violation, not a precedence question. |
| License validity gate | **No precedence, no leniency once triggered** — once the soonest expiration date is past, the employee is blocked, full stop; no source can override it. |
| Canonical display name | **HR roster's name is canonical**, always — it's the identity-originating source (§3). This is the default stored value, independent of corroboration: a Stage 1 corroboration mismatch against the License's `name_on_license` still raises its own `identity_ambiguity` flag (§3, §9) for human review, it just doesn't block HR's name from being the one stored on the entity. |

## 8. The two fronts: SST approval vs. Payroll approval

Two separate, cascading statuses, not one:

- **SST approval** (Employee-level, from Combined A): `pending → active → blocked`. Governs whether the *person* is clean in the source of truth — identity resolved, license currently valid. Nothing about a specific pay period enters here.
- **Payroll approval** (entry-level, from Combined B, checked against Combined A): `approved / held / rejected`. Governs whether *this specific pay-period entry* can be paid. Requires the employee to be SST-`active` for the entire period **and** entry-specific checks (hours consistency, facility match) to pass.

**Mid-week lapse edge case**: if a license expires partway through a pay period, the Employee's SST status correctly flips to `blocked` as of the lapse date, but the corresponding Payroll entry is not simply rejected — it goes to `held` with a distinct `partial_period_license_lapse` flag, since some days in that period were legitimately worked under a valid license. A human decides how that period is actually paid.

## 9. Flag taxonomy

Every flag carries: entity/row references, severity, a **generated plain-language reason** (not just a type code), status, and — once acted on — who/what resolved it, how, and when. Nothing is ever silently overwritten; resolution actions are additive, and a merge/link can always be reversed by detaching the source fact, since raw facts are never destroyed.

| Type | Raised by | Typically resolved by |
|---|---|---|
| `data_source_anomaly` | per-file sanity checks (§4) | review — usually a source-system issue |
| `identity_ambiguity` | resolver low-confidence match, or a corroboration mismatch (§3) — names the specific signal that disagreed, with both values | human confirms, rejects, or corrects |
| `attribute_disagreement` | Combined A build, no precedence defined for that field | human, or a future precedence policy |
| `referential_orphan` | Combined B fact with no match in Combined A | waits on HR, or manual link |
| `business_rule_violation` | cross-table checks (e.g. hours mismatch) | human judgment — no single correct value exists |
| `staleness` | License `last_verified` aged past policy window | re-verification requested |
| `license_needs_check` | gate rule, expiration past soonest-date | license renewal / correction |
| `partial_period_license_lapse` | Payroll approval, period straddles a lapse | human decides how the period is paid |

## 10. Rule engine

A single registry of rule objects (`applies_to`, `type: gate|flag`, `check(entity, graph)`, `on_fail`), evaluated by a small in-process dispatcher (~10 lines) that runs whenever an entity's relevant neighborhood changes. Not a service, not scheduled, not serverless — a function call inside the same ingestion step. `gate` rules can change an entity's status field; `flag` rules only ever write to the `flags` table.

## 11. Conflict/review surface

No message queue, no Kafka. The `flags` table (filtered on `status = 'open'`) *is* the review queue — this is batch file ingestion with a human-review loop, not a continuous multi-consumer event stream, so streaming infrastructure solves a problem this system doesn't have. A CLI (`ingest`, `flags --open`, `employee <name>`, `resolve <flag_id> <decision>`) is the human-facing surface for the hackathon; a web UI is a stretch addition only if time remains.

**Review is entity-centric, not flag-centric.** `flags --open` groups every open flag by `entity_id` rather than listing rows in isolation — a reviewer looking at Sofia Reyes sees her license status, Stage 1/2 corroboration confidence, and any Stage 3 (Combined A vs. B) conflicts together, in one bundle, rather than paging through unrelated flag rows one at a time. This is a query/presentation grouping over the same `flags` table, not a new storage concept.

**Resolution confidence carries forward.** A borderline-but-passing corroboration at Stage 1 or 2 (§3) is tagged on the entity. When a later Stage 3 conflict fires against that entity (e.g. an hours mismatch), the flag surfaces that upstream context alongside it — e.g. *"hours mismatch — note: this employee's payroll↔schedule identity match was borderline-confidence."* This turns "is this a data error, or did we actually combine two different people?" from a guess into a visible signal at review time.

## 12. Stack

Python, `pandas` (CSV), `pdfplumber` (schedule PDF table extraction), `rapidfuzz` (fuzzy name matching), SQLite (two-table entity/edge schema, portable to Postgres unchanged if real concurrent multi-client writes are ever needed).

## 13. Testing

Per-fixture self-checks, not a test framework: one fixture set per source file covering each documented edge case (duplicate `employee_id`, future `hire_date`, `OFF` shift, mid-week license lapse, unresolvable facility page) run through the full pipeline, asserting the expected flag/status outcome. The resolver's fuzzy matching is tested against realistic messy name variants, not mocked — it's the piece most likely to be wrong in a way that matters live.

## 14. Explicitly rejected

| Idea | Why |
|---|---|
| OWL/RDF + reasoner | No multi-hop inference needed anywhere; every check is a direct comparison. |
| Blocking all ingestion until conflicts resolve | A single stuck review flag would freeze every future file indefinitely. |
| Any source originating a new Employee | Breaks the real constraint: no pay or scheduling without being a registered employee first. |
| Dedicated graph database engine | Buys unbounded-depth traversal nothing here needs; weaker at the tabular reporting the business problems require. |
| Kafka / event streaming | Solves continuous multi-consumer streams; this is batch file ingestion with a review queue, which a DB table already gives. |
| Rules DSL / no-code rule editor | More code than the problem needs today; a typed list of rule objects is simpler to write, read, and test. |
| Timezone-aware conversion | No multi-timezone facility implied by the brief; single-timezone 24h conversion is sufficient. |
