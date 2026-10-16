# Parsing review evidence, 2026-10-15

Diagnostic evidence for the [draft execution plan](../../plans/parsing-usefulness-and-integration.md). Reviewed revision: `88ff05e9b33dd71a86d80874169f15549c7d0ece` in Coldaine/techdeals-v2.

- `review.md`: setup and semantic findings, including completed diagnostic.
- `inputs.json`: 24 selected inputs with paths relative to that checkout and SHA-256 checksums of canonical JSON payloads, not raw file bytes. Selection seed: 20261015.
- `results.json` and `batch_ledger.jsonl`: saved validated results and request outcomes. Raw full provider responses were not retained.
- `probes.json`: local constructed failure probes, separate from real model results.
- `server-scores.md`: original five-field scorer output, preserved to demonstrate its incomplete denominator and semantic coverage. Its 100% fields are not acceptance.
- `live-summary.json`: all-input outcome counts.
- `consolidation-status.md`: local integration decisions, reviewed head
  provenance, deferred replay finding, and validation boundaries.
- `replay-evidence/line-replay-reproduction.md` and `.sql`: rollback-only
  proof of the current line-priced observation replay gap and why an ordinal-
  only remap is unsafe.

Command: standalone `engine/extract.py`, explicit selected files, `--batch-size 8 --max-tokens 32000 --skip-db --parser-version review-free-20261015`; output directory redirected to a temporary review directory. Model: `nvidia/nemotron-3.5-lightning:free`; prompt: `batch-v2`. No DB load, SQL readback, production mutation, or billing verification. The script exited zero despite sixteen request failures. The three Reddit inputs and GovDeals input include fixture evidence; do not count them as independently verified live-source coverage.

Reproduce the scorer from the reviewed checkout:

```bash
python3 engine/score_pilot.py \
  --results docs/research/2026-10-15-parsing-review/results.json \
  --humans corpus/fixture-zero/servers_read_v2.csv
```
