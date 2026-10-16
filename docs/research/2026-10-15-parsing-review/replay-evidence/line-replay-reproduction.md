# PR 4 line-offer replay reproduction

**Finding:** `PRRT_kwDOVF5Kq86tC-Jh` in `MooseGooseConsulting/techdeals-v2-review-import` PR 4, `src/techdeals/schema/020_views.sql` line 84. The line-offer view joins its latest ask to the current extraction by `line_id`. A replay creates a new line UUID while the identical observation is deduped and stays on the prior UUID, so the offer disappears.

**Before-fix proof:** Executed the rollback-only scenario in `line-replay-reproduction.sql` against Neon project `winter-brook-99288103`, branch `br-morning-lab-b4rc55s8` (`pr-review-20261016`), database `pr4_final_validation`. It created one posting, an old extraction and ordinal-1 line with an ask at path `g0.1`, then a newer extraction with a new UUID for an ordinal-1 line on the same posting. The query returned:

| posting_id | current_line_id | current_read_rows | read_line_id | amount |
| --- | --- | ---: | --- | ---: |
| `01a142b4-c84d-744e-95be-b090e7738fb8` | `01a142b4-c84e-795e-9f1b-3010da64bf6f` | 0 | NULL | NULL |

The tool transaction rolled back to `SAVEPOINT line_replay_repro`. A follow-up count for the reproduction URL returned `leftover_repro_postings = 0`.

**Why no SQL fix was committed:** The schema describes line `subject_path` as `g<group index>.<ordinal>[.<ordinal>...]` (`schema/010_tables.sql`, path shape at lines 306–310 and comment at line 359). `lines` stores `parent_line_id` and `ordinal`; `ordinal` is documented as replay-stable within its parent (`schema/010_tables.sql`, line 155). But there is no field or relation defining how a line's `g<group index>` is derived from its hierarchy. The insert constraint checks path shape, while `observation_offer_key_guard()` checks only the digest of the supplied path; neither checks positional meaning. The `g0.1` smoke example likewise establishes only that this path is accepted for a line with ordinal 1.

The active observation writer in `engine/extract.py` emits `subject_kind = 'sale_group'` and `g<group_index>` paths (around lines 974 and 1129); it does not currently write line-priced observations. A recursive same-posting/ordinal-chain remap would omit the unmodeled group-index segment and could attach an ask to a line at the wrong position. The replay behavior is therefore a valid read-support gap, but a safe remap awaits an explicit and enforced line identity/path contract. This proof does not establish line-priced workflow support or position-independent identity.

No repository files were changed, and no remote actions were taken.
