Nominal bit rate 500 kbit/s; total utilisation 13.7 % (semmc frames 12.3 %), CHUDS frames modelled conservatively.

| id | message | ours | period ms | C us | WCRT ms | note |
|---|---|---|---|---|---|---|
| 0x000 | chuds_stop (sporadic, assumed min 100 ms) | no | 100 | 270 | 1.78 | assumed |
| 0x108 | chuds_body_state | no | 100 | 270 | 2.05 | period assumed |
| 0x210 | chuds_front_aux | no | 100 | 350 | 2.40 | audit: 100 ms |
| 0x220 | chuds_back_aux | no | 100 | 350 | 2.75 | audit: 100 ms |
| 0x230 | chuds_joulemeter | no | 500 | 510 | 3.02 | audit: 500 ms |
| 0x300 | ctrl_fault | yes | 1000 | 270 | 3.29 |  |
| 0x308 | sup_torque_req | yes | 20 | 270 | 3.56 | provisional |
| 0x309 | sup_limits | yes | 100 | 270 | 3.83 |  |
| 0x30A | sup_hello | yes | 500 | 270 | 4.10 |  |
| 0x310 | ctrl_status | yes | 20 | 270 | 4.37 |  |
| 0x311 | ctrl_cmd_trace | yes | 20 | 270 | 4.64 |  |
| 0x312 | driver_controls | yes | 20 | 270 | 4.91 |  |
| 0x313 | ctrl_session | yes | 500 | 270 | 5.18 |  |
| 0x318 | ctrl_motion | yes | 10 | 270 | 5.45 |  |
| 0x319 | ctrl_currents | yes | 10 | 270 | 5.72 |  |
| 0x320 | ctrl_energy | yes | 100 | 270 | 5.99 |  |
| 0x321 | ctrl_thermal | yes | 100 | 270 | 6.26 |  |
| 0x322 | ctrl_validity | yes | 100 | 270 | 6.53 |  |
| 0x328 | csia_advisory | yes | 100 | 270 | 6.80 |  |
| 0x330 | ctrl_identity | yes | 1000 | 270 | 6.80 |  |
