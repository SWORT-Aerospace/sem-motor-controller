# Development pilot (not the final evaluation)

Development split only; thresholds from the calibration split. D's byte budget is matched to F's mean: 36245 B.

## Scheduler A

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 22.9 |
| HT | 10 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | nan |
| HL | 20 | 19 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 26.4 |
| HU | 10 | 2 | 1 | 0 | 0 | 0 | 7 | 0 | 0 | 33.6 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 0 | |

## Scheduler B

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 184964 | 22.8 |
| HT | 10 | 3 | 0 | 0 | 0 | 0 | 7 | 0 | 184906 | 25.6 |
| HL | 20 | 17 | 0 | 0 | 0 | 2 | 1 | 0 | 184937 | 24.2 |
| HU | 10 | 3 | 1 | 0 | 0 | 0 | 6 | 0 | 184954 | 26.3 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 184936 | |

## Scheduler C

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 115378 | 28.3 |
| HT | 10 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 11527 | nan |
| HL | 20 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 115463 | 32.0 |
| HU | 10 | 6 | 0 | 0 | 0 | 0 | 4 | 0 | 77460 | 33.7 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 5782 | |

## Scheduler D

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 32104 | 22.9 |
| HT | 10 | 1 | 0 | 0 | 0 | 0 | 9 | 0 | 33593 | 69.3 |
| HL | 20 | 19 | 0 | 0 | 0 | 0 | 1 | 0 | 29899 | 26.4 |
| HU | 10 | 2 | 1 | 0 | 0 | 0 | 7 | 0 | 34346 | 33.6 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 31807 | |

## Scheduler E

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 38051 | 11.0 |
| HT | 10 | 7 | 0 | 0 | 0 | 0 | 3 | 0 | 39158 | 33.0 |
| HL | 20 | 18 | 0 | 0 | 0 | 1 | 1 | 0 | 43461 | 13.0 |
| HU | 10 | 5 | 2 | 0 | 0 | 0 | 3 | 0 | 47003 | 41.9 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 34743 | |

## Scheduler F

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 36903 | 10.9 |
| HT | 10 | 7 | 0 | 0 | 0 | 0 | 3 | 0 | 34552 | 33.0 |
| HL | 20 | 19 | 0 | 0 | 0 | 1 | 0 | 0 | 42331 | 13.3 |
| HU | 10 | 5 | 2 | 0 | 0 | 0 | 3 | 0 | 40890 | 41.9 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 28357 | |

## Scheduler F_noamb

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 9 | 0 | 0 | 0 | 1 | 0 | 0 | 55344 | 36.9 |
| HT | 10 | 8 | 0 | 0 | 0 | 0 | 2 | 0 | 54020 | 56.3 |
| HL | 20 | 17 | 0 | 0 | 0 | 2 | 1 | 0 | 65370 | 39.6 |
| HU | 10 | 7 | 0 | 0 | 0 | 0 | 3 | 0 | 52335 | 42.9 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 50156 | |

## Scheduler F_notiming

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 36903 | 10.9 |
| HT | 10 | 0 | 0 | 0 | 0 | 7 | 3 | 0 | 40983 | 67.5 |
| HL | 20 | 18 | 0 | 0 | 0 | 1 | 1 | 0 | 42506 | 12.6 |
| HU | 10 | 5 | 2 | 0 | 0 | 0 | 3 | 0 | 43664 | 41.9 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 28357 | |

## Scheduler F_doublecount

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 36903 | 10.9 |
| HT | 10 | 7 | 0 | 0 | 0 | 0 | 3 | 0 | 34552 | 33.0 |
| HL | 20 | 19 | 0 | 0 | 0 | 1 | 0 | 0 | 41634 | 13.2 |
| HU | 10 | 5 | 2 | 0 | 0 | 0 | 3 | 0 | 40890 | 41.9 |
| H0 | 20 | false alarms 1, with a wrong supported cause 0 | | | | | | | 28357 | |

## Paired differences over fault episodes (bootstrap 95 % intervals; development data)

| Comparison | difference | interval | n |
|---|---|---|---|
| F-A/correct | +0.175 | [+0.050, +0.325] | 40 |
| F-A/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-A/bytes | +39029.100 | [+34613.204, +43567.452] | 40 |
| F-A/matched | coverage 0.72: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.175 [+0.050, +0.300] | | 40 |
| F-B/correct | +0.150 | [+0.000, +0.300] | 40 |
| F-B/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-B/bytes | -145906.700 | [-150313.728, -141372.129] | 40 |
| F-B/matched | coverage 0.75: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.150 [+0.000, +0.300] | | 40 |
| F-C/correct | +0.150 | [+0.025, +0.300] | 40 |
| F-C/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-C/bytes | -50428.625 | [-64288.776, -34324.910] | 40 |
| F-C/matched | coverage 0.75: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.150 [+0.025, +0.275] | | 40 |
| F-D/correct | +0.150 | [+0.025, +0.300] | 40 |
| F-D/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-D/bytes | +7655.000 | [+2956.576, +12436.503] | 40 |
| F-D/matched | coverage 0.75: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.150 [+0.025, +0.275] | | 40 |
| F-E/correct | +0.025 | [+0.000, +0.075] | 40 |
| F-E/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-E/bytes | -2003.875 | [-4212.718, -208.914] | 40 |
| F-E/matched | coverage 0.88: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.025 [+0.000, +0.075] | | 40 |
| F-F_noamb/correct | +0.050 | [-0.075, +0.175] | 40 |
| F-F_noamb/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-F_noamb/bytes | -20996.925 | [-25093.570, -16891.381] | 40 |
| F-F_noamb/matched | coverage 0.85: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.050 [-0.075, +0.175] | | 40 |
| F-F_notiming/correct | +0.200 | [+0.075, +0.325] | 40 |
| F-F_notiming/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-F_notiming/bytes | -1695.300 | [-3855.600, -87.600] | 40 |
| F-F_notiming/matched | coverage 0.70: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.200 [+0.075, +0.325] | | 40 |
| F-F_doublecount/correct | +0.000 | [+0.000, +0.000] | 40 |
| F-F_doublecount/wrong | +0.000 | [+0.000, +0.000] | 40 |
| F-F_doublecount/bytes | +348.100 | [-160.850, +1049.075] | 40 |
| F-F_doublecount/matched | coverage 0.90: risk +0.000 [+0.000, +0.000]; coverage at risk 0.05: +0.000 [+0.000, +0.000] | | 40 |

## Engines on identical records (45 to 70 s of each episode)

| Engine | true cause | outcomes |
|---|---|---|
| CSIA2 | H0 | clean 20 |
| CSIA2 | HB | missed 10 |
| CSIA2 | HL | missed 20 |
| CSIA2 | HT | missed 10 |
| CSIA2 | HU | other 10 |
| MHT/frames | H0 | false_alarm 20 |
| MHT/frames | HB | correct 10 |
| MHT/frames | HL | correct 19, unresolved_incl 1 |
| MHT/frames | HT | correct 9, unresolved_incl 1 |
| MHT/frames | HU | other 10 |
| MHT/summary | H0 | false_alarm 20 |
| MHT/summary | HB | correct 10 |
| MHT/summary | HL | correct 20 |
| MHT/summary | HT | unresolved_incl 9, wrong 1 |
| MHT/summary | HU | other 8, wrong 2 |
| R3v | H0 | clean 20 |
| R3v | HB | missed 10 |
| R3v | HL | missed 20 |
| R3v | HT | missed 10 |
| R3v | HU | other 10 |
| aligned/frames | H0 | clean 20 |
| aligned/frames | HB | correct 4, no_fit 3, unresolved_incl 2, wrong 1 |
| aligned/frames | HL | correct 16, no_fit 4 |
| aligned/frames | HT | correct 4, missed 2, no_fit 3, unresolved_incl 1 |
| aligned/frames | HU | correct 6, other 2, wrong 2 |
| aligned/summary | H0 | clean 17, false_alarm 3 |
| aligned/summary | HB | no_fit 2, unresolved_incl 8 |
| aligned/summary | HL | correct 14, missed 2, no_fit 4 |
| aligned/summary | HT | missed 9, unresolved_incl 1 |
| aligned/summary | HU | correct 1, other 8, wrong 1 |
| reference/frames | H0 | clean 20 |
| reference/frames | HB | correct 10 |
| reference/frames | HL | correct 20 |
| reference/frames | HT | correct 9, missed 1 |
| reference/frames | HU | correct 9, other 1 |
| reference/summary | H0 | clean 20 |
| reference/summary | HB | correct 10 |
| reference/summary | HL | correct 19, missed 1 |
| reference/summary | HT | missed 9, no_fit 1 |
| reference/summary | HU | correct 1, other 8, wrong 1 |
