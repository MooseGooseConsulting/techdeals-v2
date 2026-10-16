# TechDeals parsing and application review

Reviewed checkout: `88ff05e9b33dd71a86d80874169f15549c7d0ece`.

The primary question is whether the complete interpretation -> storage -> identity -> query path preserves purchase meaning and returns useful market analysis. Model selection and JSON validity are supporting checks, not acceptance.

## Findings tied to usefulness

1. **Comparability is not established by identity.** `engine/resolve.py:70` gives servers with the same CPU and chassis the same key and confidence 0.9 even with different installed memory and storage. Such a key cannot alone establish price equivalence. A local probe compared 128GB/1.2TB with 512GB/7.68TB and obtained identical keys.
2. **Named queries do not fully enforce their own spec.** `engine/query_cheapest.sql:10` labels results 32GB DDR4 RDIMM but checks only capacity and DDR4; it does not constrain module kind to RDIMM.
3. **Facts can be invented after the model returns.** `engine/extract.py:945` converts an invalid price kind to ask and missing currency to USD. The prompt explicitly tells the model to preserve unknown currency. A local probe yielded USD/ask without a basis note from null currency/invalid kind.
4. **Decomposition can silently lose contents.** `_repair_lines` discards unrecoverable blank lines and blank children while keeping the listing. These drops have no per-line disposition. The repair script explicitly expects a blank line to disappear; passing that check is not proof all listed contents survive.
5. **The success denominator omits failures.** `score_pilot.py` iterates returned results and ignores `failed`; field hit rates exclude quarantined entries. A one-success/one-failure probe reports 100% price/status and one scored result. This must be paired with a complete input denominator and semantic coverage.
6. **The normal application command does no extraction.** `uv run techdeals extract` prints not yet fully implemented and succeeds. The standalone engine, packaged parser, schema runner and default acceptance SQL are separate paths. The packaged parser has no per-result capture ID, relies on result order, and has a different model default.
7. **Failure handling does not enforce its claims.** A fake truncated two-entry batch makes calls sized [2,1,1,1,1]. Malformed truncated JSON raises before split-retry can see truncation metadata. A simulated complete extraction failure exits 0 with zero results and two failures.
8. **Valuation assumptions remain unvalidated.** ADR 0002 records unavailable asks, no currency filtering, one-comparable minimum pricing and broad DDR4 pooling. These affect the actual market answer even when parsing is perfect.

## What existing checks establish

`uv run --extra dev pytest -q`: 15 passed. These cover models, capture-contract helpers, file presence/nonempty text and an empty extraction call. No real nonempty LLM extraction, database roundtrip or useful query answer is verified by these tests. `test_schema_files_are_valid_sql` does not execute SQL.

`python3 engine/test_repairs.py`: 13 checks passed against constructed inputs. These cover selected helper behavior, not parser or application acceptance.

Separate corpus-specific SQL acceptance scripts and previous pilot reports exist. They are stronger than the default Python checks, but their historical runs used DeepSeek. They do not establish the current full application path or comprehensive real-world accuracy.

## Evidence needed next

Use independently checked captured listings with expected purchase groups, component roles, stated quantities, prices/bounds/kinds/currencies, installed-versus-supported specs and availability. Include configured variants, mixed lots, model-number quantity traps, unavailable entries, ambiguity, wanted posts and internal cost records. Preserve each input, exact prompt/model output, validation transformations, resulting stored rows, and query answers. Assert which offers are comparable, which are actually buyable, and what remains unknown. Count every input and every missing or altered fact. Verify replay, reordering, recapture and stock/price transitions through readback. A fixed diagnostic sample alone is insufficient.

## Live diagnostic scope

24 existing captures; deterministic seed 20261015; 16 server captures, three Reddit fixture posts, four Shopify products, one GovDeals lot fixture. Three batches of eight using the current standalone engine with --skip-db. Results, batch ledger, input paths/checksums and local probes are alongside this report. No database writes. This is diagnostic evidence, not acceptance.

## Completed live diagnostic and semantic readback

24 inputs produced 8 validated results (7 extracted and 1 quarantined) and 16 call failures from two upstream idle timeouts. No database writes. The existing scorer reports 100% on its applicable five fields, omitting failed inputs and excluding quarantined cells. This is not 100% parsing accuracy.

For listing `287125775104`, the source description states `(6) HPE 600GB SAS` drives. The result instead has a Hard Drives line with quantity 6 and `storage_capacity_gb=3600`. The identity resolver would use that capacity as one drive's capacity, yielding a 3600GB identity instead of 600GB. The same result merges two distinct network adapters into one line with quantity 2, retaining the first adapter's attributes. For listing `389465023988`, the description explicitly says Processor None and Memory None, but the extraction includes empty Processors and Memory lines. These are concrete purchase-meaning failures that the five-field scorer does not measure.

Resolver confidence values are constants in branches (0.9 or 0.6), not calibrated probabilities or measured correctness. A server identity using CPU plus chassis ignores installed memory and storage. Treating that identity as a comparable configuration would be unsupported.

## Additional bundle interpretation discrepancy

Results `800121149027` and `366575148211` describe each displayed price as buying one motherboard-and-CPU bundle, but mark both component lines `separately_purchasable: true`. Those flags contradict the stated purchase scope. They require checking against the source and correcting through the full writer/query path; these saved JSON results do not demonstrate that separate offers were actually published. The five-field scorer does not check purchaseability.

## Timestamp provenance limitation found in PR review

The existing source wrappers copy Shopify `updated_at`, Atom `<updated>` and GovDeals auction-end dates into a generic `timestamp`. The standalone engine interprets that field as fetched_at and economic observation time. These wrappers and the diagnostic fixtures therefore do not establish genuine fetch or price-observation dates. Their text remains useful for parsing diagnostics, but their recorded dates must not establish freshness or price history. The source-collection plan now requires this provenance to be corrected or marked unknown before claiming source or temporal coverage.
