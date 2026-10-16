# Consolidation candidate status

Status: local integration candidate, based on canonical `main` at
`6160fb4cac816289f15c47df15fd8c5561e20119`. This document records the reviewed
material included so far; it is not a merge, deployment, or semantic-acceptance
claim. The integration branch remains local.

## Included reviewed material

- PR #3 glossary/brief wording at `3ae8d9e`.
- PR #4 schema and intake alignment at `10303de`, with follow-ups `8c497d6`
  and `8a86858` for migration preflight, CLI status, exact payload provenance,
  and incomplete URL handling.
- PR #5 source collection plan at `23c61bf`, including the explicit gate for
  the standalone extractor's unknown-time fallback before any database pilot.
- PR #6 cluster audit evidence at `148e74c`.
- PR #7 model capability handling at `781c6fe`, stricter sale-group validation
  at `73aa641`, required outcome validation at `71c67d4`, and blank component
  label failure handling at `51a530b`.
- Resolver/query adjustments at `0bca9b3`, saved-result provenance handling at
  `acc96fc`, and documentation updates at `9bcd86b`.
- Canonical PR #15 remains in `main`; its newer execution checkpoint and
  263-artifact fetch-time limitation are retained from the canonical base.

The canonical lockfile and lock dependency set remain from `main`. Root and
packaged migrations `000_functions.sql`, `010_tables.sql`, and `020_views.sql`
are kept byte-identical. Canonical tests are retained, and
`tests/acceptance_queries.sql` now targets the posting-first schema.

## Decisions and limits

The capture contract requires a nonempty source listing ID. A missing source URL
is accepted only with explicit `source_url_status: incomplete` metadata. Loaders
accept only timezone-aware `capture_metadata.fetched_at`; source update,
publication, auction-end, and file-modification times do not establish retrieval
time. The current normalized source artifacts lack proven fetch time, so loaders
skip them with notices and preserve their raw artifacts. No fetch date is
invented.

The standalone extractor still contains an `iso_or_now` file-mtime fallback.
The source collection plan now blocks database readback until the helper and
intake/write path can preserve unknown fetch time without producing dated price
or availability observations. The current live diagnostic is evidence only;
it does not establish successful persistence or correct application answers.

A rollback-only Neon reproduction demonstrates that a line-priced observation
can disappear from the current read view after replay assigns a new line UUID.
The proposed ordinal-only remap was rejected because the schema does not define
or enforce how group position maps into a line identity path. Guessing could
attach an observation to the wrong component. The finding is linked to
[canonical issue #20](https://github.com/MooseGooseConsulting/techdeals-v2/issues/20);
the reproduction and limitations are recorded in
[`replay-evidence/line-replay-reproduction.md`](replay-evidence/line-replay-reproduction.md).
Line-priced replay support remains deferred until the identity/path contract is
explicit and enforced.

The proposal to add source collection-member IDs to the global posting key was
also rejected. Collection members that are projections of the same page capture
must remain one posting; splitting them would change capture identity without an
approved discriminator contract. Distinct artifacts that share source, URL, and
capture time remain a broader identity question for issue #17.

## Verification boundary

The combined local suite, lock check, acceptance SQL review, and schema parity
checks establish repository consistency only. They do not establish line-priced
replay correctness, live-source coverage, complete capture-to-query behavior,
semantic quality, or production readiness. Both repositories remain active;
no archive or production change is part of this candidate.

At the current integration checkpoint, 78 tests pass, `uv lock --check` passes,
and root/package migration parity is 3/3. `git diff --check` is clean. Full Ruff
reported the same 148 existing diagnostics as canonical main before integration
(120 E501, 24 E741, 2 I001, 1 W292, 1 F841); no lint suppression or wholesale
prompt reformat was applied. The SQL acceptance files were updated to the
posting-first schema but were not executed against Neon in this worktree.
