# Existing review feedback: local candidate dispositions

Snapshot: 2026-10-15, at the exact heads in the
[draft execution plan](../../plans/parsing-usefulness-and-integration.md).
All six open personal PRs' review threads, review bodies and issue comments were
read, plus organization PR #11. Connection page limits were sufficient for the
returned thread/comment counts; no additional thread pages were indicated.
This is feedback triage, not a complete independent code review of every PR.

No GitHub thread has been resolved and no fix has been pushed. Candidate patches
are preserved beside this document and in isolated local worktrees. Refresh heads
and verify applicability before publishing them to the chosen canonical repo.

| Feedback | Assessment and local response | Verification limit |
|---|---|---|
| [Personal #5: intake contract](https://github.com/Coldaine/techdeals-v2/pull/5#discussion_r4260419571) | Valid. Name the current per-listing JSON engine boundary and explicitly state that RawCapture loaders do not automatically feed it; require adapter-to-engine-to-DB-to-query proof | Documentation correction; does not implement the missing bridge |
| [Personal #5: capture-first pilot](https://github.com/Coldaine/techdeals-v2/pull/5#discussion_r4260467792) | Valid. Prove existing-capture flow first, then run the full named source pilots | Preserves the source inventory; no source acquisition claimed |
| [Personal #5: provenance](https://github.com/Coldaine/techdeals-v2/pull/5#discussion_r4260467827) | Valid ambiguity. Require original URL/fetch time for complete captures, separate import receipt time, preserve missing evidence as incomplete without inventing timestamps | No imported rows changed |
| Personal #5: replay version history | Valid. Require new extraction versions, preserved history, no duplicate postings | No DB replay run performed for this documentation change |
| [Personal #6: intake report title](https://github.com/Coldaine/techdeals-v2/pull/6#discussion_r4261276679) | Valid. Add top-level document title | File inspection and diff check |
| [Personal #6: eBay denominator query](https://github.com/Coldaine/techdeals-v2/pull/6#discussion_r4261276692) | Valid. Count distinct offer IDs and filter eBay source names | SQL inspected against the documented joins; counts were not rerun on production, so no fresh reproduction claimed |
| [Personal #6: lot-quarantine evidence](https://github.com/Coldaine/techdeals-v2/pull/6#discussion_r4277135924) | Partly valid. Saved model JSON does not prove writer quarantine; the separate historical slice report does record it. Distinguish raw model output, historical writer outcome, later repairs and pending current readback | Current stored outcome not reverified |
| Personal #6, CodeAnt general comment: PGOPTIONS shell line | Valid. Quote and export the complete PGOPTIONS value so the displayed shell setup actually applies | Shell assignment syntax checked; no database connection opened |
| Personal #6, additional source check: key-input claim | Incorrect claim found while validating feedback. Currency is not hashed into the posting key. Replace it with the actual source/URL/fetched-at and group-position continuity risks | Source-traced behavior; longitudinal DB test remains pending |

`pr5-review-fixes.patch` applies to personal #5 at `c9098aed`; candidate worktree:
`/home/coldaine/techdeals-v2-review-source`.
`pr6-review-fixes.patch` applies to personal #6 at `8f50d8b`; candidate worktree:
`/home/coldaine/techdeals-v2-review-audit`.

Other open PR findings/status:

- Personal #1 has no inline threads and an approval. Organization #11 also has
  an approval and no unresolved inline threads. They need one chosen dependency
  baseline and normal lock validation, not two blindly merged maintenance PRs.
- Personal #3's prior granularity thread is resolved/outdated. Its earlier
  requested-changes review and CodeAnt summary must be read against the latest
  wording rather than counted as fresh defects.
- Personal #4 has no returned reviews. That is missing review evidence, not
  approval. Its schema copies and application alignment require full review.
- Personal #7 has no inline threads, but CodeAnt's general comment calls for
  endpoint/quality validation and CodeRabbit reports its review was rate limited.
  The diagnostic in this directory is limited and does not satisfy application
  acceptance. Organization review configuration and successful execution remain
  to be checked after repository consolidation.

Draft patch verification: both isolated worktrees pass `git diff --check`;
patches must pass `git apply --reverse --check` against their modified worktrees
and `git apply --check` against their original heads. These are applicability
checks, not proof that documented SQL counts or runtime behavior are correct.
