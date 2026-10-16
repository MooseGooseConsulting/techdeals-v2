# PR #19 consolidation decisions and verification

This is the bounded consolidation of the organization and review-import work,
based on canonical main `4517f952299855a25a4f5cc3df745ae6d6073b8b`.
[The project goal](../../project-goal.md) governs the design. Existing production
and v2 schemas are implementations to assess, not authorities.

## Retain

- Import PR #3 terminology, #5 source inventory and #6 audit evidence, with
  provenance and historical-evidence limits. These documents are inputs to the
  experiment, not proof of working application answers.
- PR #4's useful schema/package alignment, exact raw-payload envelopes,
  source-URL disposition, explicit fetch provenance, migration preflight,
  available-only CLI query, quarantine reporting, and honest exit statuses.
  The unused old packaged migration files are removed. Legacy databases are
  rejected before DDL and preserved; in-place data conversion is not implemented.
- Standalone extraction result validation: malformed groups, ambiguous blank
  components, missing price meaning, invalid quantities and malformed outcomes
  cannot silently become successful stored interpretations. A missing single
  product label may use its capture title, with that origin recorded. These
  checks establish narrow contracts, not semantic accuracy.
- Saved-result replay bound to both capture checksum and posting offer key;
  positive chunk sizing and mismatch rejection precede writes. Historical
  unbound result files remain evidence and cannot use this replay loader.
- Current experimental view fixes: available and same-currency comparables,
  exclusion of the valued posting from its own lot comps, incomplete unknown
  quantities, normalized whole-lot ask, current group-key readback, zero-line
  extraction accounting, and posting versus line quarantine separation.
- Database ownership constraints tie lines and groups to their extraction's
  posting, and line resolutions to their posting. Deferred supersession checks
  prevent links to another price, resolution, or category series while allowing
  atomic same-key correction. See the rollback regression SQL.
- The already merged goal document (#21), free-model configuration (#22), and
  Doppler environment workflow (#23). No model rejection guard or allowlist
  test is retained. Parser defaults remain free; no local `.env` is loaded.

## Remove or defer

| Material | Decision and reason |
|---|---|
| New `engine/resolve.py` and its example query | Omit from this merge. The proposed product keys merge materially different configurations, and constants 0.6/0.9 are not measured confidence. Fixing nested-line handling or concurrency would not establish useful matching. Prototype remains in git at `efe642e39eb28c1b6482ee5b2dd6f2ecbe5945f1`; issue #17 owns a justified replacement. Tests specific to this omitted implementation are omitted with it. |
| `v_group_ram`, `v_ddr4_gb_rate`, `v_partout` | Defer registration. Their comparison cohorts, currency, availability, purchased quantities and rate assumptions are unproved. Exact proposal retained in [deferred-partout-proposal.sql](deferred-partout-proposal.sql); issue #16 owns re-entry. Existing `v_line_ram` remains. |
| New paid-model repair output and ledger additions | Omit. Existing historical pilots remain clearly historical. These extra outputs do not validate the configured free model or faithful replay. |
| Runtime model enforcement and policy guard tests | Remove as explicitly rejected by the owner. Document policy and commit free defaults; preserve existing override interfaces. |
| Line-priced replay remapping | Defer under [issue #20](https://github.com/MooseGooseConsulting/techdeals-v2/issues/20). The [reproduction](replay-evidence/line-replay-reproduction.md) shows prices disappearing after fresh line IDs. Group-key readback is repaired; no guessed ordinal remap is introduced. The active standalone writer emits group prices. Line-priced replay is not a supported claim. |
| Globally extending posting identity with collection member ID/type | Reject the proposed blanket fix. Collection members can be projections of the same captured page. Splitting them changes capture identity without a demonstrated discriminator contract. Distinct same-URL/time artifacts remain an issue #17 identity design question. |

Import PR #4 is superseded by this bounded canonical change once #19 lands;
merging the older import branch independently would duplicate its schema work.
Closing it does not declare its deferred line replay or valuation work solved.
Both repositories remain active.

## Verification on 2026-10-16

- `uv run --extra dev pytest -q tests engine/test_repairs.py`: 97 passed.
- Late #22 cost feedback is valid: an unknown override rate now stays NULL in
  the ledger and database batch and prints as unknown, rather than a fabricated
  zero. Free defaults and overrides remain; no paid rates or rejection guard
  are added. #23's request to inject an extraction key assumes a functioning
  packaged command; that command explicitly exits 2 before any model call.
  README now makes this boundary clear instead of presenting it as a working
  extraction recipe.
- Ruff on `src` and `tests`, `uv lock --check`, schema byte parity and
  `git diff --check`: passed. No dependency versions or lint thresholds lowered.
- Existing Neon project `winter-brook-99288103`, temporary branch
  `pr-review-20261016` (`br-morning-lab-b4rc55s8`), new isolated database
  `pr19_completion_20261016`: all 256 baseline SQL statements applied.
- `schema/smoke_test.sql`, supersession, integrity and view feedback regressions
  passed in rollback transactions. Diagnostic query SQL executed; final counts
  remained zero. This verifies schema and synthetic regressions, not real-source
  acquisition or complete parsing/application answers.

No live model call, production write, deployment or source schedule was part of
this consolidation. None of the 263 normalized artifacts proves original fetch
time. Strict intake leaves those artifacts unchanged and reports them skipped;
that still does not provide the queryable incomplete-evidence path the goal
requires. Issues #16–#20 retain valuation, semantic correctness, availability and
identity work. The next design task is to select one capture-to-consumer path
and prove varied annotated examples through it before production incorporation.

Independent review: Standards found no documented-rule violation and noted
repeated provenance handling as a maintainability consideration. Spec found no
new blocking defect in the bounded scope; it confirmed incomplete-time queryable
intake and packaged extraction are unfinished project-goal gates. Individual
[review dispositions](pr19-review-disposition.md) distinguish repaired feedback,
removed implementations and explicit deferrals.
