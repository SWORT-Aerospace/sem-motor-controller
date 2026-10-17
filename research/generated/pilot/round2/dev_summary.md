# Development pilot (not the final evaluation)

Development split only; thresholds from the calibration split. D's byte budget is matched to F's mean: 36117 B.

## Scheduler A

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 23.0 |
| HT | 10 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | nan |
| HL | 20 | 10 | 0 | 0 | 0 | 7 | 3 | 0 | 0 | 26.4 |
| HU | 10 | 3 | 1 | 0 | 0 | 0 | 6 | 0 | 0 | 22.4 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 0 | |

## Scheduler B

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 2 | 0 | 0 | 198361 | 22.8 |
| HT | 10 | 3 | 0 | 0 | 0 | 0 | 7 | 0 | 196167 | 18.6 |
| HL | 20 | 12 | 0 | 0 | 0 | 8 | 0 | 0 | 190624 | 19.3 |
| HU | 10 | 5 | 1 | 0 | 0 | 0 | 4 | 0 | 191789 | 16.1 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 198417 | |

## Scheduler C

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 1 | 1 | 0 | 118820 | 28.3 |
| HT | 10 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 48376 | nan |
| HL | 20 | 14 | 0 | 0 | 0 | 4 | 2 | 0 | 107488 | 31.5 |
| HU | 10 | 6 | 0 | 0 | 0 | 0 | 4 | 0 | 89341 | 21.4 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 47313 | |

## Scheduler D

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 2 | 0 | 0 | 30998 | 23.0 |
| HT | 10 | 2 | 0 | 0 | 0 | 1 | 7 | 0 | 33477 | 29.4 |
| HL | 20 | 12 | 0 | 0 | 0 | 6 | 2 | 0 | 30133 | 25.3 |
| HU | 10 | 4 | 0 | 0 | 0 | 0 | 6 | 0 | 34419 | 15.9 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 32318 | |

## Scheduler E

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 9 | 0 | 0 | 0 | 1 | 0 | 0 | 37416 | 10.8 |
| HT | 10 | 3 | 0 | 0 | 0 | 2 | 5 | 0 | 32467 | 40.4 |
| HL | 20 | 14 | 0 | 0 | 0 | 6 | 0 | 0 | 39902 | 15.8 |
| HU | 10 | 8 | 1 | 0 | 0 | 0 | 1 | 0 | 45251 | 34.5 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 34498 | |

## Scheduler F

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 9 | 0 | 0 | 0 | 1 | 0 | 0 | 37219 | 10.8 |
| HT | 10 | 1 | 0 | 0 | 0 | 1 | 8 | 0 | 33346 | 26.1 |
| HL | 20 | 14 | 0 | 0 | 0 | 6 | 0 | 0 | 36511 | 15.8 |
| HU | 10 | 8 | 1 | 0 | 0 | 0 | 1 | 0 | 47102 | 34.5 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 31066 | |

