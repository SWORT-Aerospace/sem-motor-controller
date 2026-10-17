# Development pilot (not the final evaluation)

Development split only; thresholds from the calibration split. D's byte budget is matched to F's mean: 31338 B.

## Scheduler A

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 6 | 0 | 0 | 0 | 3 | 0 | 1 | 0 | 22.9 |
| HT | 10 | 1 | 0 | 0 | 0 | 0 | 6 | 3 | 0 | -0.9 |
| HL | 20 | 10 | 0 | 0 | 0 | 6 | 1 | 3 | 0 | 26.4 |
| HU | 10 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 11.7 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 0 | |

## Scheduler B

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 7 | 0 | 0 | 0 | 1 | 0 | 2 | 185124 | 22.8 |
| HT | 10 | 1 | 0 | 0 | 0 | 0 | 5 | 4 | 176288 | 0.6 |
| HL | 20 | 9 | 0 | 0 | 0 | 9 | 0 | 2 | 185095 | 18.2 |
| HU | 10 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 178535 | 11.7 |
| H0 | 20 | false alarms 10, with a wrong supported cause 0 | | | | | | | 185113 | |

## Scheduler C

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 1 | 0 | 1 | 109823 | 28.3 |
| HT | 10 | 0 | 0 | 0 | 0 | 0 | 6 | 4 | 43937 | 4.1 |
| HL | 20 | 14 | 0 | 0 | 0 | 4 | 1 | 1 | 102994 | 31.4 |
| HU | 10 | 6 | 0 | 0 | 0 | 0 | 3 | 0 | 76919 | 17.2 |
| H0 | 20 | false alarms 7, with a wrong supported cause 0 | | | | | | | 38456 | |

## Scheduler D

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 6 | 0 | 0 | 0 | 2 | 0 | 2 | 24081 | 22.9 |
| HT | 10 | 1 | 0 | 0 | 0 | 1 | 5 | 3 | 26978 | 0.6 |
| HL | 20 | 11 | 0 | 0 | 0 | 5 | 1 | 3 | 25537 | 25.6 |
| HU | 10 | 1 | 0 | 0 | 0 | 0 | 3 | 0 | 26492 | 11.7 |
| H0 | 20 | false alarms 9, with a wrong supported cause 0 | | | | | | | 26973 | |

## Scheduler E

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 1 | 0 | 0 | 1 | 0 | 0 | 35274 | 10.8 |
| HT | 10 | 2 | 0 | 0 | 0 | 2 | 4 | 2 | 26930 | 13.3 |
| HL | 20 | 12 | 0 | 0 | 0 | 7 | 1 | 0 | 38273 | 16.5 |
| HU | 10 | 7 | 1 | 0 | 0 | 0 | 2 | 0 | 36939 | 22.3 |
| H0 | 20 | false alarms 10, with a wrong supported cause 0 | | | | | | | 33300 | |

## Scheduler F

| Truth | n | correct | wrong | unresolved_incl | unresolved_excl | no_fit | missed | undecided | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|
| HB | 10 | 8 | 0 | 0 | 0 | 1 | 0 | 1 | 33566 | 10.8 |
| HT | 10 | 2 | 0 | 0 | 0 | 2 | 4 | 2 | 24677 | 13.1 |
| HL | 20 | 12 | 0 | 0 | 0 | 7 | 1 | 0 | 34638 | 16.5 |
| HU | 10 | 7 | 1 | 0 | 0 | 0 | 2 | 0 | 35604 | 22.3 |
| H0 | 20 | false alarms 10, with a wrong supported cause 0 | | | | | | | 28124 | |

