# Parsing diagnostic, 2026-10-15

Historical diagnostic at revision `88ff05e9b33dd71a86d80874169f15549c7d0ece`
in the former personal repository. It supplies concrete failure examples for
[issue #17](https://github.com/MooseGooseConsulting/techdeals-v2/issues/17), not a
current implementation status or acceptance result.

## Evidence and scope

- `inputs.json`: 24 input IDs, corpus paths, titles and SHA-256 checksums of
  canonical JSON (`sort_keys=True`, `ensure_ascii=False`, separators `,` and
  `:`), rather than raw file bytes. Selection seed: 20261015.
- `results.json`: the eight returned validated results, sixteen failed input
  IDs, model/prompt metadata, and all three batch ledger rows.

Inputs were 16 server captures, three Reddit fixture posts, four Shopify
products and one GovDeals lot fixture. The standalone engine ran three batches
of eight with `nvidia/nemotron-3.5-lightning:free`, prompt `batch-v2`,
`--max-tokens 32000 --skip-db --parser-version review-free-20261015`.
Seven inputs were extracted, one quarantined and sixteen failed in two upstream
idle timeouts. No database writes occurred. Raw full provider response bytes
were not retained. The Reddit/GovDeals fixtures do not establish live-source
coverage. Source update/auction dates in these wrappers do not establish actual
fetch times, freshness or price history.

## Purchase-meaning failures in the saved results

| Input ID | Source or purchase scope | Saved interpretation |
|---|---|---|
| `287125775104` | Six HPE 600GB drives; two differently specified NICs | Quantity six with per-drive capacity 3600GB; both NICs collapsed into quantity two carrying only the first NIC's attributes |
| `389465023988` | Processor and memory explicitly absent | Empty Processors and Memory component lines still included |
| `800121149027`, `366575148211` | Price note says one motherboard-and-CPU bundle | Each component marked separately purchasable |

These examples establish errors in saved interpretation. They do not establish
which offers were persisted or shown by an application consumer.

## Scorer limitation

The existing five-field scorer reports 100% on its applicable returned cells:
CPU model 5/5, total RAM 3/3, price 7/7, chassis 5/5, listing status 7/7.
It omits the sixteen failed inputs and excludes quarantined cells; it does not
check per-drive capacity, distinct NICs, absent components or purchaseability.
Those percentages therefore do not measure overall parsing correctness.

The score table is derived output and can be regenerated without a model call:

```bash
python3 engine/score_pilot.py \
  --results docs/research/2026-10-15-parsing-review/results.json \
  --humans corpus/fixture-zero/servers_read_v2.csv
```

At the reviewed revision, local synthetic probes also demonstrated invented
USD/ask defaults, silent component drops, constant resolver confidence, sub-floor
retry batches and successful exit after complete failure. Those historical
helper findings are already represented in issue #17 and the relevant repair
PR/tests; they are not additional real-model observations.
