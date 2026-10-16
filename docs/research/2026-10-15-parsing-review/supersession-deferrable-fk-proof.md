# Same-key supersession constraint proof

## Finding

PR #19 review thread `PRRT_kwDOVF5ne86tDK5z` correctly identified a deadlock in
the documented correction sequence. `categories_live_name_key` and
`price_observations_replay_dedupe` only allow one live key. Inserting a same-key
replacement first violates that index; updating the old row first violates the
immediate self-referential `superseded_by` foreign key. `supersede_only()` does
not independently require that the target row already exist; it requires only
a one-time pointer change to a strictly later UUID.

## Supported correction transaction

Keep both partial unique indexes non-deferrable. Make only the self-referential
`superseded_by` foreign keys `DEFERRABLE INITIALLY IMMEDIATE`. A writer generates
a later UUID, defers the relevant FK, points the old live row at that UUID,
inserts the replacement with the same unique key and that explicit UUID, then
sets the FK immediate before commit. This frees the old live-key index entry
before the replacement insert while still rejecting an omitted replacement.
No `btree_gist` extension or exclusion constraint is needed.

The SQL regression [supersession_regression.sql](../../../tests/supersession_regression.sql)
proves both the missing-target rejection and same-name replacement in a single
rollback-only transaction. The schema smoke test additionally proves a
price-observation correction with the same `offer_key`, `observed_at`, and
`price_kind`.

## Verification evidence

- Before the fix, a rollback-only transaction on Neon `pr4_final_validation`
  returned `same_name_insert=blocked by categories_live_name_key` and
  `update_before_target=blocked by immediate self-FK`.
- The schema and full smoke test passed on isolated Neon branch
  `pr19-supersession-verify` (`br-jolly-term-b4vj47xb`), database
  `pr19_supersession_validation`, created from parent `main`
  (`br-tiny-rain-b4ynpurt`). The smoke transaction ended in `ROLLBACK`; follow-up
  counts were zero for postings, price observations, and categories.
- Both self-FKs are reported deferrable; `btree_gist` is absent on the test
  database. The branch expires 2026-10-23 03:26:15 UTC.
- Local validation: 40 tests pass, changed Python test passes Ruff, schema and
  smoke-test copies are byte-identical, and `git diff --check` passes.
