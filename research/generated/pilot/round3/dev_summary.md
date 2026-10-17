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
| HB | 10 | 9 | 0 | 0 | 0 | 1 | 0 | 0 | 184964 | 22.7 |
| HT | 10 | 3 | 0 | 0 | 0 | 0 | 7 | 0 | 184906 | 18.5 |
| HL | 20 | 13 | 0 | 0 | 0 | 6 | 1 | 0 | 184937 | 21.7 |
| HU | 10 | 3 | 1 | 0 | 0 | 0 | 6 | 0 | 184954 | 22.8 |
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
| HT | 10 | 1 | 0 | 0 | 0 | 0 | 9 | 0 | 33130 | 58.3 |
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

