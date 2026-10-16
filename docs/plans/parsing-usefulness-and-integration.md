# Parsing usefulness, repository consolidation, and production integration

Status: draft for owner review, 2026-10-15. Planning remains separate from implementation and deployment. The former personal
repository has been transferred into the organization as `techdeals-v2-review-import`;
production has not been changed. PR completion is in progress.

## Purpose and authority

TechDeals must turn heterogeneous source evidence into useful hardware buying
answers: what can be bought, what configuration is included, what is comparable,
what it costs now and over time, what a lot contains and may be worth, and what
remains unknown. Valid JSON, stored rows, green checks, and heuristic numbers do
not establish that these answers are correct.

The owner-authored [production North Star](https://github.com/MooseGooseConsulting/TechdealsHandoff/blob/main/docs/NORTH_STAR.md)
defines the product. [BRIEF.md](../../BRIEF.md) defines the v2 experiment. This
document sequences work under those authorities; it does not create a new
product scope or authorize replacing the production system.

## Repository topology and consolidation

The table below records the starting repository snapshot; PR counts and heads
are historical, not a live status feed. Publication and completion are being
recorded separately. Three repositories must be distinguished:

| Repository | Verified state on 2026-10-15 | Role and consolidation status |
|---|---|---|
| [MooseGooseConsulting/techdeals-v2-review-import](https://github.com/MooseGooseConsulting/techdeals-v2-review-import) | Former personal repo, transferred with the same repository ID and PR/issue history; main `60eec34a0e227095c29ef5c1f554c4996d913ad3`; reviewed extraction branch `88ff05e9b33dd71a86d80874169f15549c7d0ece`; 6 open PRs and 3 open issues | Contains work and review history that must be preserved |
| [MooseGooseConsulting/techdeals-v2](https://github.com/MooseGooseConsulting/techdeals-v2) | Separate repo; main `68e106c1ae7e8ba4d4d2bbd67bacc7a8659dd61d`; 13 merged PRs; open PR #11 | Already contains the measured engine via #12 and an explicit removal of the competing adapter attempt via #14 |
| [MooseGooseConsulting/TechdealsHandoff](https://github.com/MooseGooseConsulting/TechdealsHandoff) | Production project; remote main `1ac8f887db62420a2c2dc2de2ed41597ee7802c6` | Eventual consumer of proven improvements; live deployment state is a separate check |

The owner requested organization ownership and completion of all open PRs. The
existing organization repo remains canonical. The personal repo was transferred
to `MooseGooseConsulting/techdeals-v2-review-import`, preserving its repository ID,
PRs, issues and review history without displacing the existing organization repo.
Bring reviewed missing work into the canonical repo through a consolidation PR.
Preserve original source links and record which commit/PR supplies each change.
Keep both histories; do not delete either repo or force-push one over the other.
Both repositories remain active. The owner explicitly rejected archiving during
ongoing work; no archival is planned or authorized by this task.
Verify reviewer applications actually run on current heads, rather than inferring
coverage from organization ownership. Consolidation completion and production
integration remain separate outcomes.

The local comparison already shows both shared measured-engine work and
different later changes. A wholesale personal-to-organization merge would also
replace organization-side contract validation/tests and CLI wiring. Those
changes require explicit review, not mechanical conflict resolution. Existing
organization CLI wiring must itself be checked against #14's module removals.

## Step 1: review and disposition all existing PRs before new implementation

The PR table records the initial review heads. The plan itself is canonical
[PR #15](https://github.com/MooseGooseConsulting/techdeals-v2/pull/15), reviewed as
a documentation change alongside the listed implementation PRs.

Review current heads, all current review threads, review summaries, issue
comments containing findings, and relevant checks. Distinguish resolved/outdated
feedback from still-valid defects. Validate comments against source and actual
evidence; do not blindly apply suggestions or resolve threads on intent alone.
Publication and merges are coordinated under the organization; refresh current
heads and checks immediately before each merge.

| Work | Snapshot head | Review evidence and proposed disposition |
|---|---|---|
| Personal [#1](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/1), lock maintenance | `4dfe91d5b17bd402823d9fc68298cc9aa7970ef0` | No inline threads; approved review. Compare with org #11; retain one applicable dependency change, not duplicate PRs |
| Personal [#3](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/3), terminology | `cacc36863074dca262ee7671f37f6d5198a1a2b7` | Prior requested-change thread is resolved/outdated. Verify latest wording distinguishes listings from line/group offer rows; preserve useful terminology change |
| Personal [#4](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/4), schema/application alignment | `747568636d4953a040215f976def7462518f8d4e` | No reviews returned. Review implementation before reuse: copied authoritative SQL must not become another independently drifting schema; alignment does not establish semantic correctness or a working extraction command |
| Personal [#5](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/5), source plan | `c9098aed3ebc6ad50f511b7836d252b402531eb1` | Four unresolved current threads: executable intake boundary, capture-first sequencing, original capture provenance, version-preserving replay. Local candidate corrections prepared; publication in progress under review-import |
| Personal [#6](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/6), audit | `8f50d8b58df3659d570d7c49e8e60b003a904146` | Three unresolved current threads: document title, eBay distinct-offer query, raw-result versus writer-quarantine claim. General review also flags invalid PGOPTIONS shell setup. Local candidate corrections prepared, including incorrect key-input description; query changes are not production-reproduced yet |
| Personal [#7](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/pull/7), free endpoint | `88ff05e9b33dd71a86d80874169f15549c7d0ece` | No inline threads; reviewer requests availability/quality evidence. Keep cost policy as a narrow constraint; it is not parsing acceptance. Determine every callable path that needs that policy |
| Organization [#11](https://github.com/MooseGooseConsulting/techdeals-v2/pull/11), lock maintenance | `85b662132dada4df59841743e9f23f07abeac3a5` | No unresolved inline threads; CodeRabbit approved and Devin reported no issues. Compare final lock against chosen baseline and validate normally |

Also inspect personal `feat/ingestion-loop` at
`06e61e3b7014e363f319dc97f2421c08d8c259b2`, which has no open PR in the inventory.
It claims an integrated offline/LLM pipeline and database checks, but changes the
older schema/application path. Compare it with organization #10/#14 and #4 before
retaining anything. Its commit description is reported work, not verified outcome.

Exit: every PR/branch has a documented keep/revise/supersede disposition, valid
feedback has a concrete patch and validation, and review evidence is preserved.
Do not equate thread count zero with a complete review.

## Step 2: establish the failures against real application questions

Build a bounded evidence set from existing source captures first. Record which
inputs are authentic captures, authored fixtures, or synthetic failure probes;
never use an authored fixture to claim live source coverage. Add independently
checked expectations, with supporting source excerpts, for:

| Question/case | Required observable result |
|---|---|
| Configured server with six 600GB drives | Six drives, 600GB per drive; aggregate capacity remains a separate derivation; the price covers the stated purchasable configuration |
| Two different NICs in one server | Distinct component facts and counts survive extraction, storage, and readback |
| Barebones with CPU/RAM explicitly absent | Absence survives; no installed CPU/RAM component is manufactured |
| Same CPU/chassis, different installed configurations | Family relation may remain, but price-comparable configurations are not silently merged |
| Model/fan numbers such as RX 7900 or Windforce 3X | They do not become purchase quantities or price divisors |
| Lot price versus each price; mixed lot; selectable upgrades | Correct purchase groups, amount scope and bounds; no base ask attached to upgraded contents or arbitrary component allocation |
| Cheapest 32GB DDR4 RDIMM | Capacity, module type and other stated compatibility constraints enforced; buyable offers and quantities shown with source evidence |
| Unavailable, unknown-stock, foreign-currency and no-price evidence | Honest state preserved; default buyable results exclude unavailable/unknown inventory; currencies are separated; useful non-offer evidence remains retrievable |
| Price/stock changes and parser replay/reordering | One source offer's history remains traceable; no duplicated purchases, relabeled history, or fabricated events |
| Wanted post, consumer item, internal cost, auction bid | Correct disposition/kind; none silently becomes a current merchant ask |

Read back answers through the application consumer boundary, not only a model
JSON file. Account for every input and every dropped/changed component. Separate
coverage, semantic correctness, and deliberate abstention. Report field accuracy
with its denominator; failed inputs must remain in the coverage denominator.

Use fixtures, small explicit assertions and SQL folded into each slice. No
separate generic evaluation-framework project. There is no numerical accuracy
threshold chosen here that could substitute for correct buying answers.

Exit: checked examples and expected answers reproduce known failures before
repair. Unknown/unverified cases are explicit, not relabeled passes.

## Required field review: usefulness, meaning, lineage, and actual behavior

Before selecting a replacement schema or claiming an implementation slice ready,
review every field that slice stores, derives, selects, compares, or displays.
The [field inventory and review contract](field-review.md) starts with all 86
table columns in the reviewed standalone schema and names its 12 views. This is
an inventory, not 86 approvals. Existing SQL comments are claims to verify, not
proof that a column serves its purpose.

Reconcile the inventory with the chosen canonical revision, the competing
packaged schema, actual scratch database catalog, production contracts and
affected API/UI output. Include individual JSON attribute keys and generated
fields: approving `lines.attributes` or `payload` as a container does not approve
every value inside it. Unknown raw fields may be retained without promoting
them into queryable facts.

For every field, record:

1. **Use:** the concrete buying query, evidence/replay requirement, relationship
   invariant or operational decision that needs it, and its actual consumer.
   A generic Q1/Q4 tag or speculative future use is insufficient.
2. **Meaning:** subject and row granularity, units, per-unit versus aggregate
   scope, fact versus source claim versus derivation versus judgment, allowed
   values, missing versus absent versus zero, time semantics, and conflict policy.
3. **Lineage:** actual producer/writer, source field/excerpt and observation
   context, normalization/repair/default rules, derivation inputs and version,
   and which consumers depend on it. Technical IDs need referential/continuity
   evidence rather than a seller quote; derivations need traceable inputs.
4. **Proof:** independently checked real examples, deliberate negative cases,
   database enforcement where applicable, stored readback and the actual query
   answer. Include transformations and replay/recapture so one correct output
   cannot conceal a later corrupted meaning.
5. **Disposition:** keep, rename/split, derive, retain as unselected evidence,
   replace, or remove, with a specific reason. Mark evidence status separately
   as unreviewed, defect reproduced, candidate repair, verified for stated scope,
   or unknown/blocked. Never fill missing proof with arbitrary confidence.

Review both sides: can a field support the intended answer, and can it make a
wrong answer look valid? For example, six 600GB drives must not become six
3600GB products; a stored numeric capacity passes a type check in both cases.
The query-level proof must exclude the wrong product/offer as well as return
the right one. Part-out tests must verify that quantity is applied exactly once
and that partial known values are not presented as a complete valuation.

Every migration and contract change must reconcile the field inventory. On a
scratch database built from the chosen migrations, enumerate tables, views and
their columns from the Postgres catalog and compare with the ledger; inspect
JSON keys and generated API contracts too. Add a focused automated discrepancy
check as part of that slice, rather than treating this Markdown inventory as
enforcement. A newly added field or changed definition requires updated purpose,
lineage and assertions. A renamed column does not silently inherit its old proof.

Exit: every field on the slice's active read/write path has a justified
disposition and evidence of correct behavior for the stated scope. Unverified
fields remain explicitly unselected/unresolved and cannot decide comparability,
current inventory, valuation or recommendation. Raw evidence and technical
accounting remain available. Review completeness and functional completeness are
reported separately; this process does not claim universal real-world accuracy.

## Step 3: retain or rebuild modules against those examples

Choose one executable capture-to-query path and one authoritative schema source.
Reuse sound append-only/provenance mechanisms after verifying them. Replace code
whose contract cannot express the source meaning; do not rebuild every scraper
or application simply because an experimental resolver is wrong.

Implement in this order, each as a reviewable slice with before/after evidence:

1. Preserve purchase meaning: component versus bundle, per-item versus aggregate
   capacity, installed versus supported/absent facts, variants and price scope.
2. Preserve uncertainty: remove arbitrary numerical confidence from decisions;
   retain rule/method, matched facts, missing discriminators, conflicts and review
   state. Any future probabilistic score requires a defined event and measured
   calibration. Keep unknown currency/kind unknown; record every rejected or
   repaired component without silent deletion.
3. Define category-specific identity and comparability from price-determining
   facts. Preserve family, product, variant, configuration, offer and capture as
   different concepts where the evidence requires them. Incomplete identity must
   not prevent evidence intake or explicit unresolved query results.
4. Reconcile intake, extraction, loading, replay, errors, schema and consumer
   queries through the selected path. Missing IDs, duplicate IDs, reordering,
   invalid output, truncation, transport failure and restarts must have truthful
   dispositions. A completed process with no useful results must not signal a
   successful extraction. Preserve request/output and transformation provenance
   sufficient to inspect failures without retaining secrets.
5. Fix current-inventory/read-query semantics and named spec predicates. Keep
   buyable offers separate from historical/reference sightings; preserve both.

Exit: the bounded examples return their expected stored facts and application
answers, with failures and uncertainty visible. Passing these examples establishes
the slice, not general correctness across all hardware.

## Step 4: broaden evidence and validate valuation separately

After the capture-to-query path works, execute the corrected source-collection
plan in source slices. Inventory coverage across the twelve North Star categories;
prove category-neutral behavior and additional category-specific facts with real
inputs before claiming support. Keep the full source inventory, including
[production issue #226](https://github.com/MooseGooseConsulting/TechdealsHandoff/issues/226),
even when execution is staged. Record precise access/coverage gaps.

Use second-date captures for actual stock/price transitions and unchanged pages;
use replay and deliberately reordered extraction outputs for continuity checks.
Do not require weeks of waiting when preserved real dated captures can establish
a case, and do not invent changes or provenance to manufacture a demonstration.

Only with sufficient real standalone component evidence perform
[personal issue #2](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/issues/2): test exact
matching, DDR4 pooling, count/spread/outlier rules, currency and historical versus
buyable reference use. Update ADR 0002 from results. Part-out output stays
explicitly partial/unsupported until the relevant assumptions and coverage are
demonstrated; do not treat a partial component subtotal as the server's value.

## Issue map and missing tracking

| Existing issue | Place in this plan | Required completion evidence |
|---|---|---|
| Personal [#8](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/issues/8) | Steps 2–3 | Full interpretation-to-query behavior; scope must include application usefulness, not only model tuning |
| Personal [#9](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/issues/9) | Step 3 and production repair track | Default current offers, historical/reference separation, unknown states, repeated stock changes, preserved evidence |
| Personal [#2](https://github.com/MooseGooseConsulting/techdeals-v2-review-import/issues/2) | Step 4, after its explicit data prerequisite | Empirical valuation record and ADR update reviewed in a PR |
| Production [#226](https://github.com/MooseGooseConsulting/TechdealsHandoff/issues/226) | Step 4 source inventory | Actual source acquisition/intake/query proof or explicit owner deferral; a plan does not close it |

The three former personal issues have been transferred with history into the
canonical tracker: #2 → [#16](https://github.com/MooseGooseConsulting/techdeals-v2/issues/16),
#8 → [#17](https://github.com/MooseGooseConsulting/techdeals-v2/issues/17), and
#9 → [#18](https://github.com/MooseGooseConsulting/techdeals-v2/issues/18).
Original issue URLs redirect to their destinations. Reconcile further tracking
with those issues as part of consolidation. Add missing implementation tracking for semantic failures, truthful
measurement, application/schema alignment, identity/comparability, continuity,
and production repairs after checking for existing equivalents. This document's
checkpoints are proposed work, not evidence that issues were created or changed.

## Whether and when to incorporate into the production project

Recommendation: incorporate proven, bounded improvements incrementally. Do not
wait for all v2 research to finish before correcting a confirmed production
defect. Do not import the entire v2 schema/resolver or its apparent confidence as
an assumed replacement. Existing production contracts, auction behavior,
category projections and API consumers must be explicitly accounted for.

| Change class | When it belongs in TechdealsHandoff | Before runtime application |
|---|---|---|
| Audit/acceptance evidence and narrow production fixes, e.g. unavailable deal filtering or fabricated GPU price handling | As soon as the responsible production path is localized and the actual failure is reproduced; can proceed alongside v2 work | Review the fix; prove corrected application readback and historical-data impact; do not only hide incorrect stored interpretations |
| Shared parsing or purchase representation improvements | After the relevant Step 2–3 cases pass through the selected path and an explicit mapping to the production writer/consumer contract exists | Integrate on isolated data first; compare old/new outputs on the same real captures; preserve differences and uncertainty |
| New source routes | After existing-capture pipeline proof and a verified source pilot | Follow the owning repo's source index, flow docs, cost/access policy and scheduling procedure |
| Identity, schema or historical-data migration | After configuration equivalence, history continuity and affected API/category contracts are proven | Additive migration/rehearsal where feasible; counts, source lineage, read parity, correction/supersession and rollback proof |
| Part-out valuation or recommendations | After empirical assumptions and applicable component coverage are established | Label estimate, scope, missing components and evidence; judgments stay separate from facts |

Code incorporation, merging, deployment, data correction, collector scheduling
and retiring old writers are distinct actions. Each integration slice must name
its target repo/branch, affected consumers and data, before/after evidence,
remaining gaps, runtime ownership and rollback method. This drafting task does
not authorize production deployment or data changes. Before such actions, obtain
the required concrete approval under the active user instructions and owning
repository workflow. Do not add a repeated approval step to actions the owner
has already explicitly authorized.

For the first integration slice, compare both paths on the same retained source
evidence without changing current user-visible results. Advance to a bounded
runtime rollout only when its correctness and preservation checks pass. Verify
the deployed revision and actual query result after rollout; revert or stop on
unexplained semantic regressions. Retire an old path only after its successor
and affected history/consumers are verified.

## Evidence and current progress

This draft follows a 2026-10-15 setup review. The local 15 Python checks and 13
repair assertions passed but do not establish parsing or application correctness.
A 24-input live diagnostic at `88ff05e` returned seven extracted results, one
quarantine and sixteen request failures. The five-field scorer reported 100% on
its applicable returned cells while missing the drive-capacity and NIC errors.
No database writes occurred, so persistence/query consequences are source-traced
findings, not claims of reproduced stored output.

Supporting review, input checksums, live results and local failure probes are in
`docs/research/2026-10-15-parsing-review/` alongside this plan. Raw full provider
response bytes were not retained by the current client. The source report and
review-comment snapshots are historical evidence, not current merge/readiness
claims; refresh exact heads before publication or mutation.

Current work completed: repository/PR/issue inventory, reviewer feedback triage,
two isolated local documentation-repair candidates, and this draft. Pending:
full PR implementation review, corrected publication and consolidation,
independent verification of the proposed sequence, then Step 2. Nothing here
claims the repair candidates were pushed, PRs merged, or production improved.
