## Per-field hit rates

| field | applicable | hit | miss | hit rate |
|---|---|---|---|---|
| cpu_model | 5 | 5 | 0 | 100% |
| ram_total_gb | 3 | 3 | 0 | 100% |
| price_usd | 7 | 7 | 0 | 100% |
| chassis_model | 5 | 5 | 0 | 100% |
| listing_status | 7 | 7 | 0 | 100% |

Outcome split over 8 scored results: 7 extracted, 1 quarantined/no-info.

## Per-listing score table

| item_id | cpu_model | ram_total_gb | price_usd | chassis_model | listing_status |
|---|---|---|---|---|---|
| 175685579251 | quarantined | na | quarantined | na | quarantined |
| 327384872371 | hit | hit | hit | hit | hit |
| 306444479932 | na | na | hit | hit | hit |
| 287125775104 | hit | hit | hit | hit | hit |
| 336710692561 | hit | hit | hit | hit | hit |
| 389465023988 | na | na | hit | hit | hit |
| 800121149027 | hit | na | hit | na | hit |
| 366575148211 | hit | na | hit | na | hit |

## Misses (with raw title)

  (cpu_model: +1 quarantined-listing cells, see below)
  (price_usd: +1 quarantined-listing cells, see below)
  (listing_status: +1 quarantined-listing cells, see below)

## Quarantined-listing cells (human read them; capture was a dead page)

- **cpu_model** `175685579251` human=`EPYC 7413` engine=unparseable — AMD EPYC 7413+ Supermicro H12SSL-I 24 cores 48 threads 2.65GHZ combination
- **price_usd** `175685579251` human=`1392.0` engine=unparseable — AMD EPYC 7413+ Supermicro H12SSL-I 24 cores 48 threads 2.65GHZ combination
- **listing_status** `175685579251` human=`live` engine=unparseable — AMD EPYC 7413+ Supermicro H12SSL-I 24 cores 48 threads 2.65GHZ combination
(no misses on applicable fields)

## Not-applicable notes (engine answered where human read nothing)

- **chassis_model** `800121149027` engine=`H12SSL-i` (human left blank) — Supermicro H12SSL-i Motherboard + AMD EPYC 7532 3.3GHz CPU Processor Combos
