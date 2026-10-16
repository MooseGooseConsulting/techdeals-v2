# Field usefulness and correctness review

Status: review contract and initial inventory, 2026-10-15. The inventory is based
on the personal standalone schema at `88ff05e9b33dd71a86d80874169f15549c7d0ece`.
It is not the reconciled canonical or production schema, and none of these rows
has been granted semantic acceptance by generating this inventory.

## A completed review record

Each field needs a record with: exact repo/revision and field path; disposition;
meaning, subject and granularity; unit and price/quantity scope; missing/absent/
zero/conflict behavior; a concrete consumer or integrity purpose; actual writer;
source evidence or derivation inputs; all transformations/defaults; positive and
negative examples; stored and application readback; and verification status and
limits. Link shared rules where fields follow one contract, but keep each field
accounted for. Do not copy generic purpose text into 86 rows and call that a review.

Use these statuses independently of the design disposition: **unreviewed**,
**defect reproduced**, **candidate repair**, **verified for named scope**, and
**unknown/blocked**. Test existence is separate from a passing check and from a
correct result. SQL column comments below are declared intent, not established use.

## High-risk fields to review first

| Field or meaning | Required decision and proof |
|---|---|
| `lines.attributes.storage_capacity_gb` and `lines.stated_quantity` | Define per-drive capacity separately from aggregate capacity. Actual diagnostic: six 600GB drives produced quantity 6/capacity 3600; check identity and valuation do not amplify the mistake |
| Distinct NIC attributes and component membership | Preserve each different adapter and its count; do not overwrite the second adapter with the first adapter's attributes or flatten them into one apparent product |
| Installed CPU/RAM and explicit absence | A statement that CPU/RAM are absent must not create installed components. Keep supported capability distinct from installed configuration |
| `resolutions.product_key` | Define the identity level and discriminators required for actual comparison; same CPU/chassis alone cannot establish equal installed configuration |
| `resolutions.confidence` | Current 0.6/0.9 literals do not measure correctness. Propose removal from decision-making; record method, evidence, missing facts and uncertainty instead. Audit every consumer before migration |
| `price_observations.amount`, `quantity`, `price_basis` | State exactly what the amount buys. Verify each-price, homogeneous lot, configured bundle and ambiguity; apply quantity once and avoid allocation across heterogeneous contents |
| `price_observations.price_kind`, `currency` | Missing/invalid values cannot silently become ask/USD. Preserve original evidence and uncertainty; reject cross-currency minima without explicit analysis |
| Availability `state`, timestamps and freshness | Distinguish observed availability, unknown, explicit unavailability and observation age; a previously available snapshot does not prove availability now |
| `postings.offer_key`, observation `offer_key`, `sale_groups.position` | Separate capture identity, logical source offer and purchase configuration. Prove group reorder and repeat dated capture do not attach history to a different purchase or split the intended series invisibly |
| Raw capture timestamps, `created_at`, `observed_at` | Fetch, import receipt, extraction creation, listing publication and economic observation are different events; defaults must not fabricate one from another |
| `categories.spec`, query predicates | Prove the named spec matches the actual predicate; include near-match negatives such as RDIMM versus UDIMM |
| `unit_price`, reference minima, RAM rates, part-out totals | Verify units, quantity scope, stock/freshness, currency, comparability, sample support and missing components. Numeric output alone is not useful valuation |
| `extraction_batches.cost_usd`, counts, reach states | Distinguish router-reported usage, estimated cost, unknown cost, attempted/returned/accepted/stored counts. Do not label a script exit or a partial parse fully functional |
| `lines.attributes`, `categories.spec`, raw `payload` containers | Inventory the attribute keys and contracts that affect decisions; a JSON object type does not validate semantics. Preserve unregistered raw fields without silently promoting them |

## Scope reconciliation still required

The inventory below contains all 86 table-column declarations recognized in the
11 standalone CREATE TABLE blocks. The discovery was checked against the source
block count; it is a static inventory, not a SQL parser or executed catalog check.
The separate packaged schema, chosen organization revision, production schema,
individual view output fields, generated API contracts and actual JSON keys still
need reconciliation. Their absence from this initial table is explicit unfinished
review work, not permission to ignore them.

On the isolated verification database, enumerate columns from `pg_attribute`,
`pg_class` and `pg_namespace` (exclude system/dropped attributes), including views
and materialized/foreign relations in the owned schema. Compare names and types
with the ledger. Enumerate actual JSON attribute keys, registered definitions and
producer/consumer keys as well; compare API generation and frontend bindings.
Machine-discovered presence starts a review record; it does not approve it.

## Standalone view inventory

Each view needs a record for every output field, including inherited fields,
renamed aliases, aggregation rules and null/empty-set behavior. Verify row
multiplicity and join scope as well as individual values.

- `v_current_extractions` — output fields and semantic review pending.
- `v_cheapest_available` — output fields and semantic review pending.
- `v_category_prices` — output fields and semantic review pending.
- `v_price_history` — output fields and semantic review pending.
- `v_product_reference_price` — output fields and semantic review pending.
- `v_lot_worth` — output fields and semantic review pending.
- `v_accounting` — output fields and semantic review pending.
- `v_stale_quarantine` — output fields and semantic review pending.
- `v_line_ram` — output fields and semantic review pending.
- `v_group_ram` — output fields and semantic review pending.
- `v_ddr4_gb_rate` — output fields and semantic review pending.
- `v_partout` — output fields and semantic review pending.

## Standalone table columns

### `extraction_batches`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q4: identity of the batch for cost accounting. | Unreviewed |
| `model` | `text` | Serves Q4: which model ran the batch; batch-economics accounting. | Unreviewed |
| `prompt_version` | `text` | Serves Q4: reproducibility of extractions (replay safety relies on knowing which prompt produced which lines). | Unreviewed |
| `cost_usd` | `numeric` | Serves Q4: cost per batch (NULL when unknown, 0 for free endpoints). | Unreviewed |
| `listing_count` | `integer` | Serves Q4: makes batch discipline auditable (dozens per call, not one). | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: accounting timeline. | Unreviewed |

### `postings`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q4: every capture lands as exactly one posting row — nothing silently dropped. | Unreviewed |
| `offer_key` | `text` | Serves Q4 (and replay-safety for Q1-Q3): sha256 of the natural key (source \| url \| fetched_at), stable across parser replays so re-ingesting a capture never invents a second posting (BRIEF §3 acceptance 5, 8). | Unreviewed |
| `source` | `text` | Serves Q4: provenance — where it was seen (source name). | Unreviewed |
| `url` | `text` | Serves Q4: provenance — where it was seen (URL). | Unreviewed |
| `fetched_at` | `timestamptz` | Serves Q2: provenance — when it was seen; anchors every price/availability time series. | Unreviewed |
| `checksum` | `text` | Serves Q4: provenance — integrity checksum of the payload, so corrupted re-captures are detectable. | Unreviewed |
| `payload` | `jsonb` | Serves Q4: the raw capture kept intact so missed/mis-parsed/quarantined postings can be re-extracted (BRIEF §6 query 4: "parse failures surfaced with their payload intact"). | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: when the posting row was written (ingest time, distinct from fetch time). | Unreviewed |

### `extractions`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q4: identity of the parse pass; views read the newest extraction per posting. | Unreviewed |
| `posting_id` | `uuid` | Serves Q4: which capture was parsed. | Unreviewed |
| `batch_id` | `uuid` | Serves Q4: links the parse to its LLM batch for batch-economics accounting; NULL only for parses that ran outside a batch. | Unreviewed |
| `parser_name` | `text` | Serves Q4: which parser produced the lines — replay safety requires identifying the producer. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: ordering of parse passes; newest wins in the read views. | Unreviewed |

### `lines`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q1-Q3: identity of the decomposed item. | Unreviewed |
| `posting_id` | `uuid` | Serves Q4: provenance — which capture this line was decomposed from. | Unreviewed |
| `extraction_id` | `uuid` | Serves Q4 (protects Q1-Q3): which parse pass produced this line; a replay appends new lines, never mutates old ones (BRIEF §3 acceptance 8). | Unreviewed |
| `parent_line_id` | `uuid` | Serves Q3: nested contents — components of a server line or manifest rows of a lot line. | Unreviewed |
| `ordinal` | `integer` | Serves Q3 (and offer-key stability): position of the line within its parent; stable across replays, so writers hash it into the natural key behind offer_key. | Unreviewed |
| `label` | `text` | Serves Q1, Q3: the seller's stated name/description, verbatim as parsed. | Unreviewed |
| `stated_quantity` | `numeric` | Serves Q1 (the N units behind a price) and Q3 (lot decomposition: the 50-DIMM lot is one line with stated_quantity 50). NULL when the count is not stated — the engine also marks those lines attributes.quantity_stated = false; NULL is never a silent stand-in for 1 (unresolved counts must stay visible, BRIEF §6 "no silent allocation" spirit). | Unreviewed |
| `separately_purchasable` | `boolean` | Serves Q1: whether the line can be bought on its own or only inside a sale group. | Unreviewed |
| `attributes` | `jsonb` | Serves Q1: extracted spec attributes (the indexed substrate for "spec S" and for dynamic categories — data, not DDL); also feeds Q3 valuation comps. | Unreviewed |

### `sale_groups`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q1, Q3: identity of the purchasable bundle. | Unreviewed |
| `posting_id` | `uuid` | Serves Q4: provenance of the group. | Unreviewed |
| `extraction_id` | `uuid` | Serves Q4: which parse pass produced the group (replay safety). | Unreviewed |
| `position` | `integer` | Serves Q1 (offer-key stability): the group's zero-based position within its extraction pass — the stable half of the offer natural key behind offer_key (sha256(posting natural key \| '\|g' \|\| position)), so replays hash the same logical offer regardless of parser-version group ids. | Unreviewed |
| `label` | `text` | Serves Q1, Q3: what the purchase shape is, as stated by the seller/parser. | Unreviewed |

### `sale_group_terms`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q1, Q3: identity of the membership term. | Unreviewed |
| `sale_group_id` | `uuid` | Serves Q1, Q3: the purchase this term belongs to. | Unreviewed |
| `line_id` | `uuid` | Serves Q1, Q3: the included line. | Unreviewed |
| `line_quantity` | `numeric` | Serves Q1, Q3: how many of the line's stated units are in this purchase (e.g. all 16 DIMMs, or 4 of the 8 drives). NULL when the share itself is not stated — it is never defaulted. DB-enforced guards: UNIQUE(sale_group_id, line_id) (one term per line per group, so splitting an allocation across terms cannot dodge the cap) plus the insert guard capping line_quantity at stated_quantity, and rejecting a stated share for a line whose own count is unstated — allocation cannot be silently inflated. | Unreviewed |

### `price_observations`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q2: ledger identity; time-ordered by uuidv7. | Unreviewed |
| `offer_key` | `text` | Serves Q1, Q2: replay-stable identity of the offer priced — sha256(posting offer_key \| '\|' \| subject_path), enforced by the observation_offer_key_guard trigger. Same natural key as the availability ledger, so price and availability join on subject identity. | Unreviewed |
| `subject_path` | `text` | Serves Q1, Q2 (offer-key stability): the subject's stable position path in the capture — 'g<group index>' for a sale group, 'g<group index>.<ordinal>[.<ordinal>...]' for a line. Ordinal shifts across parser versions change the path, so a shifted line cannot silently alias the old offer; replays with stable structure hash identically. | Unreviewed |
| `posting_id` | `uuid` | Serves Q2, Q4: provenance — which capture the price was observed in. | Unreviewed |
| `subject_kind` | `text` | Serves Q1-Q3: whether the subject is a line or a sale group. | Unreviewed |
| `line_id` | `uuid` | Serves Q1-Q3: the priced line when subject_kind = line. | Unreviewed |
| `sale_group_id` | `uuid` | Serves Q1, Q3: the priced bundle when subject_kind = sale_group (e.g. the lot ask). | Unreviewed |
| `observed_at` | `timestamptz` | Serves Q2: the time-series axis — when this price was in effect. | Unreviewed |
| `price_kind` | `text` | Serves Q2 (and the acceptance rule behind Q3): ask/bid/sold/cost_basis/reference are separate series, never conflated (BRIEF §3 acceptance 3). | Unreviewed |
| `price_basis` | `text` | Serves Q3: how the amount relates to units — explicit_unit, homogeneous_division, bound_only, allocated. A lot total is never divided into unit prices without homogeneous_division or allocated (BRIEF §3 acceptance 3, §6 guardrail). | Unreviewed |
| `amount` | `numeric` | Serves Q1-Q3: the observed amount, covering `quantity` units. NULL only for bound_only rows. | Unreviewed |
| `currency` | `text` | Serves Q1-Q3: currency of the amount. | Unreviewed |
| `quantity` | `numeric` | Serves Q1, Q3: how many units `amount` covers — NULL when the unit count is not stated (never silently defaulted to 1); per-unit prices are derived in views and are NULL when quantity is unknown. | Unreviewed |
| `bound_low` | `numeric` | Serves Q3: lower bound for bound_only rows — ambiguous cases are reported as bounds, never silently allocated; bound_only requires at least one bound (DB CHECK). | Unreviewed |
| `bound_high` | `numeric` | Serves Q3: upper bound for bound_only rows. | Unreviewed |
| `basis_note` | `text` | Serves Q3: the recorded basis of any apportionment (what was divided/allocated, and by what rationale). | Unreviewed |
| `superseded_by` | `uuid` | Serves Q2: corrections point forward to the superseding observation, set once via the supersede_only update (superseder must be a strictly later row; single supersession enforced by unique index) — history is never rewritten. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q2, Q4: ingest time of the observation. | Unreviewed |

### `availability_observations`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q1, Q2: ledger identity. | Unreviewed |
| `offer_key` | `text` | Serves Q1: same replay-stable offer identity as price_observations — sha256(posting offer_key \| '\|' \| subject_path), trigger-enforced — so price and availability share subject identity. | Unreviewed |
| `subject_path` | `text` | Serves Q1 (offer-key stability): the subject's stable position path in the capture, same vocabulary as price_observations.subject_path. | Unreviewed |
| `posting_id` | `uuid` | Serves Q2, Q4: provenance of the check. | Unreviewed |
| `subject_kind` | `text` | Serves Q1: line or sale group. | Unreviewed |
| `line_id` | `uuid` | Serves Q1: the line whose purchasability was checked. | Unreviewed |
| `sale_group_id` | `uuid` | Serves Q1: the sale group whose purchasability was checked. | Unreviewed |
| `observed_at` | `timestamptz` | Serves Q2: when the check happened. | Unreviewed |
| `state` | `text` | Serves Q1, Q4: available/unavailable/unknown — unknown keeps failed checks visible instead of silently dropping them. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: ingest time. | Unreviewed |

### `resolutions`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q4: identity of the resolution pass result. | Unreviewed |
| `posting_id` | `uuid` | Serves Q4: provenance — which posting the resolution belongs to. | Unreviewed |
| `line_id` | `uuid` | Serves Q1, Q3: the line resolved; NULL for posting-level resolutions. | Unreviewed |
| `product_key` | `text` | Serves Q1, Q2, Q3: stable identity of the proposed product — what history and comps are grouped on. | Unreviewed |
| `product_name` | `text` | Serves Q1, Q2: human-readable product identity. | Unreviewed |
| `confidence` | `numeric` | Serves Q1, Q4: lets consumers weigh answers; scoring never blocks a posting from being visible. | Unreviewed |
| `method` | `text` | Serves Q4: which scorer/model produced the match (re-runnable, reproducible). | Unreviewed |
| `superseded_by` | `uuid` | Serves Q4: a later pass supersedes — set once, only pointing at a strictly later row; nothing is rewritten or deleted. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: ordering of resolution passes. | Unreviewed |

### `quarantine_events`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q4: event identity; quarantine->release is an appended event, not an update. | Unreviewed |
| `posting_id` | `uuid` | Serves Q4: which capture was quarantined. | Unreviewed |
| `line_id` | `uuid` | Serves Q4: a single out-of-scope line within an otherwise kept posting; NULL for posting-level quarantine. | Unreviewed |
| `state` | `text` | Serves Q4: quarantined/released — the latest event per subject is its state. | Unreviewed |
| `reason` | `text` | Serves Q4: why — wanted_post, out_of_scope_consumer, not_inventory, dead_page, duplicate, parse_failed, transport_failed (batch call could not reach the model), batch_call_failed (model/gateway rejected the call), price_ambiguous (stated price not confidently storable), quantity_conflict (stated unit count contradicts the group's terms), ... (documented vocabulary; deliberately not a CHECK so new reasons are data, not migrations). | Unreviewed |
| `detail` | `text` | Serves Q4: free-text explanation; the payload stays intact on the posting for re-extraction. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: when the state changed. | Unreviewed |

### `categories`

| Column | Declared type | Declared intent from SQL comment | Review status |
|---|---|---|---|
| `id` | `uuid` | Serves Q1: identity of the named spec. | Unreviewed |
| `name` | `text` | Serves Q1: the category name consumers query by (e.g. 32GB DDR4 RDIMM); unique among LIVE rows only, so corrections can reuse the name. | Unreviewed |
| `spec` | `jsonb` | Serves Q1: jsonb attribute predicate (containment) that a line must satisfy to be in the category. | Unreviewed |
| `superseded_by` | `uuid` | Serves Q1, Q4: set once on the replaced row, pointing at its later replacement (supersede_only update); a superseded category is history, not a live spec. | Unreviewed |
| `created_at` | `timestamptz` | Serves Q4: when the category was added. | Unreviewed |

