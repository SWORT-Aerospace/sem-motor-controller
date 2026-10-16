# Property-test soaks (HOST SIMULATION)

`firmware/tests/test_core_properties.c`: adversarial supervisor traffic (silence, duplicates, older frames, bit errors, wrong tags, NaN, cached samples, companion stalls, restarts, bus-off) and a random driver (throttle, brake, cancel, dead-man, mode and arm switches, fault reset) with controller reboots, through the real CAN binding and the host plant. Properties P1 to P8 are checked after every 1 ms slow step (header of the test file). ctest runs 6 x 12 s and 24 x 12 s on every build.

Soaks run on the freshness and session code of commit `1d4c265` (host build with ASan/UBSan):

| Command | Seeds x simulated s | Slow steps | ECO steps (entries) | Recovery checks | Checks | Failures |
|---|---|---|---|---|---|---|
| `./build/test_core_properties 100 30` | 100 x 30 (base 0x1234567) | 3 000 000 | 641 109 (1632) | 1 257 928 | 13 733 755 | 0 |
| `./build/test_core_properties 300 30 0x5EED2026` | 300 x 30 (new base) | 9 000 000 | 1 926 382 (4775) | 3 721 412 | 41 237 961 | 0 |

Injected in the 300 x 30 soak: normal 381009 silence 17361 duplicate 10705 older 10756 corrupt 6829 wrong_tag 6575 nan 3155 cached 7035 stall 2160 restart 1060 bus_off 630 reboot 774.

Sensitivity: with the freshness code of `c46faa8` the 24 x 12 s ctest configuration reports 2464 failed checks (P8 recovery and P5 renewal); with the session-tag derivation of `c46faa8` the 6 x 12 s configuration reports 4 failed P5 checks (renewal by frames from before a bus-off).
