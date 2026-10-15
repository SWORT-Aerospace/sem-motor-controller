# CSIA post-hoc analysis: debounce confound - SYNTHETIC, EXPLORATORY

> Added **after** the pre-registered held-out evaluation (`csia_evaluation_synthetic.md`), to separate the effect of a 3-tick debounce from the rest of the method. The frozen files are not modified. Results are exploratory: any adapter change motivated by them must be evaluated on a new held-out set.

| monitor | false-alarm episodes / h | false attributions / h | missed / faults | correctly attributed | misattributed | detection latency median / p90 s |
|---|---|---|---|---|---|---|
| CSIA | 19.66 (114) | 2.41 | 16 / 70 | 48 | 9 | 4.2 / 21.9 |
| CSIA+deb3 | 0.00 (0) | 0.00 | 18 / 70 | 47 | 6 | 6.0 / 22.0 |
| V3v | 0.00 (0) | 0.00 | 18 / 70 | 35 | 0 | 6.0 / 23.3 |
| V3v-deb1 | 19.66 (114) | 2.41 | 16 / 70 | 35 | 1 | 4.2 / 21.9 |

Reading: compare CSIA with CSIA+deb3 (debounce added to CSIA) and V3v with V3v-deb1 (debounce removed from the residual vote). The rows for CSIA and V3v reproduce the pre-registered run on the same scenarios.
