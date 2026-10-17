# Telemetry candidate parts: checked against requirements (v0.5)

The team named these parts as references: DRV5032, LSM6DSV, ISM330DHCX, DS18B20, AS5600, and the telematics proposal's NUCLEO-U575ZI-Q / STM32U575, NEO-M9N and A7672. **None is selected.** Each is checked here against what the vehicle needs, from the manufacturer's own documents. Procurement status per line: [`PROCUREMENT.md`](PROCUREMENT.md).

## Sources read

Manufacturer and distributor sites were unreachable from the build environment (egress proxy refused ti.com, st.com, analog.com, ams-osram.com, u-blox.com, simcom.com, digikey.com, mouser.com, lcsc.com, octopart.com on 2026-10-16). Every document below is a **copy hosted in a third-party GitHub repository**, read through a normal git clone. Its own text names the manufacturer, document number and revision. None was compared byte-for-byte with the publisher's file. Page numbers are the documents' printed pages.

| Ref | Document (as printed) | Revision, date | Pages | SHA-256 (first 16) | Copy read (repository @ commit, path) |
|---|---|---|---|---|---|
| T1 | TI DRV5032 Ultra-Low-Power Digital-Switch Hall Effect Sensor, SLVSDC7 | F, February 2022 | 40 | `320671f3b8ce36e2` | luisllorentemuro/strokes-per-minute-sensor @ `3de2144`, `drv5032.pdf` |
| T2 | TI DRV5023-Q1 Automotive Digital-Switch Hall Effect Sensor, SLIS163 | G, March 2017 | 33 | `c0b65b912fbd56c2` | JonathanMichaelEdwards/STM32MP157C_SBC @ `ec3dbaa`, `hw/datasheets/Sensors/.../DRV5023BIQDBZTQ1.pdf` |
| T3 | Maxim DS18B20 Programmable Resolution 1-Wire Digital Thermometer, 19-7487 | Rev 5, 9/18 | 20 | `7c8d08062b8520e6` | emilyhammes/emilyhammes.github.io @ `0ddec6f`, `temperaturemonitor/DS18B20.pdf` |
| S1 | ST LSM6DSV datasheet, DS13476 | Rev 5, August 2023 | 189 | `b698bb20b0defb6c` | rc-kid/rckid @ `f0cc805`, `datasheets/lsm6dsv.pdf` |
| S2 | ST LSM6DSV16X datasheet, DS13510 | Rev 4, May 2023 | 198 | `ec53c0e5952fc0c9` | suntyrael/Life_GPS @ `18a6574`, `Doc/LSM6DSV16X_Datasheet.pdf` |
| S3 | ST ISM330DHCX datasheet, DS13012 | Rev 7, November 2020 | 167 | `4ebd304610da62f3` | sparkfun/SparkFun_6DoF_ISM330DHCX_Arduino_Library @ `31c9ca3`, `Documentation/ism330dhcx.pdf` |
| S4 | MEMSIC MC3419 3-Axis Accelerometer, APS-048-0071 | v1.2, 2021/04 | 78 | `1fd7806a1e232c71` | hakam00ra/mc3419 @ `5efa715`, `MC3419Datasheet(APS-048-0071v1.2).pdf` |
| A1 | ams AS5600 12-Bit Programmable Contactless Potentiometer | v1-06, 2018-Jun-20 | 43 | `7a676482eb5730bb` | SeeedDocument/Grove-12-bit-Magnetic-Rotary-Position-Sensor-AS5600 @ `0840ad1`, `res/Magnetic Rotary Position Sensor AS5600 Datasheet.pdf` |
| N1 | ST UM2861 User manual, STM32U5 Nucleo-144 board (MB1549) | Rev 10, March 2025 | 52 | `2ad8e32398e92f2a` | Hydro-backup-Systeem/Hydro_Firmware @ `27045cf`, `references/um2861-stm32u5-nucleo144-board-mb1549-stmicroelectronics.pdf` |
| N2 | ST RM0456 Reference manual, STM32U5 series | Rev 6, January 2025 | 3653 | `52152e414e2ac329` | same repository and commit, `references/rm0456-stm32u5-series-armbased-32bit-mcus-stmicroelectronics.pdf` |
| N3 | ST pin data for STM32U575ZITxQ (XML) | as committed | n/a | `f7dca325efbed32e` | STMicroelectronics/STM32_open_pin_data @ `7d1f151`, `mcu/STM32U575ZITxQ.xml` |
| U1 | u-blox NEO-M9N-00B Data sheet, UBX-19014285 | R07, 27-Mar-2023 | 22 | `1c174c3c9ebdb0f1` | sparkfun/SparkFun_u-Blox_NEO_M9N @ `c38db32`, `Documentation/NEO-M9N-00B_DataSheet_UBX-19014285.pdf` |
| U2 | u-blox NEO-M9N Integration manual, UBX-19014286 | R06, 08-Jul-2021 | 97 | `e1ac1aa84881f6f4` | astromarc/osnmaPython @ `dd91e1d`, `docs/ublox/NEO-M9N_Integrationmanual_UBX-19014286.pdf` |
| L1 | SIMCom A7672X Series Hardware Design | V1.04, 2023-02-13 | 78 | `ff9ac63f2a28a7cd` | GarudaShare/Garuda-Share @ `cf7f838`, `A7672X_Series_Hardware_Design_V1.04.pdf` |
| L2 | SIMCom A76XX Series AT Command Manual | V1.12, 2024-04-25 | 684 | `6ac294edd07d27c0` | Xinyuan-LilyGO/LilyGO-T-A76XX @ `51b988a`, `datasheet/A76XX/A76XX_Series_AT_Command_Manual_V1.12.pdf` |

Notes. N3 is ST's own repository; every other copy is third-party. Older revisions were also seen and agree on the values used: L1 V1.02, the A7672X/A7670X V1.03, A7672S Hardware Design V1.00; L2 V1.09 and V1.06; S2 Rev 2. Not used: copies that are Git LFS objects (the session's git proxy refuses LFS downloads for unattached repositories), including DRV5032 revisions G and H and the only STM32U575 datasheet copy found (DS13737). Every value below carries its reference and page, so it can be checked against the copy named in the table (repository, commit, path and hash).

## Summary

| Candidate | Function | Verdict | What prevents selection |
|---|---|---|---|
| NUCLEO-U575ZI-Q | bench development of the telematics firmware | Candidate (development only) | none for bench use; it is not vehicle hardware |
| DRV5032 | wheel speed | **rejected for wheel speed** | sampled every 27 to 75 ms: misses most magnet passes at vehicle speed |
| DRV5023-Q1 (comparison) | wheel speed | not a candidate yet | vehicle speed, magnet geometry, supply current, mounting |
| LSM6DSV / ISM330DHCX | longitudinal acceleration, yaw rate (analysis) | Candidate | mounting, temperature, whether the PCB already has an IMU |
| MC3419 (board proposal) | acceleration | not suitable as the 6-axis IMU | no gyroscope |
| DS18B20 | slow temperatures for logging | Candidate (logging only) | measurement points; not usable for power-stage protection |
| AS5600 | steering angle (optional) | Candidate, blocked | steering geometry at the mounting point |
| NEO-M9N | position, speed, PPS time base | blocked line | whether the PCB assembly includes it; antenna connector |
| A7672 (variant by region) | LTE uplink | blocked | event country and operator; exact module (A7672 or SIM7672) |

## NUCLEO-U575ZI-Q

* **Board (N1):** MCU STM32U575ZIT6Q (Table 1, p. 3); "-Q" means the internal SMPS (pp. 2-3). On-board STLINK-V3E on USB Micro-B (CN1); its virtual COM port is USART1 on PA9/PA10 (pp. 14, 29). USB-C (CN15) is full-speed device and sink only (p. 30). The 32.768 kHz crystal is fitted (X2, p. 27). Whether the 16 MHz HSE crystal is fitted is not stated for this board (pp. 27-28).
* **Power (N1, Table 8, p. 17):** 5V_STLK, 5V_EXT, 5V_CHGR 4.75-5.5 V (500 mA); VIN 7-12 V; 5V_USB_C 4.75-5.5 V (1 A); 3V3 3.0-3.6 V.
* **Interfaces (N1):** ST Zio (Arduino Uno V3) and ST morpho (morpho headers not fitted by default, pp. 33, 37). FDCAN1 RX/TX on PD0/PD1 reach CN9 pins 25/27 (p. 35). **There is no CAN transceiver on the board** (none in the manual), and no Ethernet. I2C1 on PB8/PB9, SPI1 on PA5-PA7, TIM1/TIM2/TIM4 channels on the connectors (pp. 34-35). Board revisions covered: MB1549-U575ZIQ C02, C03, C05 (pp. 42-43).
* **MCU (N2, N3):** one FDCAN instance; USART1-3, UART4-5, LPUART1; SPI1-3; I2C1-4; TIM1-8, TIM15-17, LPTIM1-4 (N2 pp. 145, 148, 2094); 2 MB flash, SRAM1-4 192/64/512/16 KB (N2 pp. 276, 293); VDD 1.71-3.6 V (N2 pp. 404-405). The temperature range is a datasheet item; DS13737 could not be read (N3 lists -40 to 85 °C, a generic database value).
* **Fit:** every telematics interface has a peripheral: FDCAN1 plus an external transceiver for CAN; two UARTs for GNSS and the modem (the modem needs RTS/CTS and a 1.8 V level translator, see A7672); SPI or I2C for the IMU; timer input capture for wheel pulses; I2C for the AS5600; a UART in half-duplex or a GPIO for 1-Wire. **Development use only:** in the vehicle the unit needs a protected supply from the propulsion battery, a CAN transceiver, harness connectors and a transparent enclosure (Article 57j); that is the telematics PCB line.

## Wheel speed: DRV5032

* **Variants (T1 p. 3):** DU (unipolar, push-pull, 20 Hz), FA (omnipolar, push-pull, 20 Hz), FB (omnipolar, push-pull, 5 Hz), FC (omnipolar, open-drain, 20 Hz), FD (unipolar, push-pull, 20 Hz), AJ (omnipolar, open-drain, 20 Hz, B_OP max 9.5 mT), ZE (omnipolar, open-drain, 20 Hz, 63 mT).
* **Sampling (T1 p. 6):** 20 Hz versions f_S 13.3 / 20 / 37 Hz (min/typ/max), period t_S 27 / 50 / 75 ms; FB 3.5 / 5 / 8.5 Hz, t_S 117 / 200 / 286 ms; active time 40 µs. Between samples "The output is latched, and the device enters an ultra-low-power sleep state" (p. 14).
* **Supply, thresholds, environment (T1):** 1.65-5.5 V; T_A -40 to 85 °C (p. 5); FA/FB/FC B_OP ±1.5 / ±3 / ±4.8 mT, B_RP ±0.5 / ±1.5 / ±3 mT (p. 7); applications listed: "Battery-critical position sensing", tamper detection, case sensing, valve position (p. 1).
* **Check against wheel pulses:** [`generated/wheel_sensor_check.md`](generated/wheel_sensor_check.md) computes the field window of a magnet pass and the chance that a sample falls inside it, over a labelled geometry grid (the vehicle's wheel, magnet radius and field window are unknown). With a 10 mm window at 10 cm radius on a 1.5 m wheel, a 20 Hz version sees 11 to 17 % of passes at 10 km/h. It is certain to see every pass only below 0.3 to 11.5 km/h across the grid, and the release between magnets must be sampled too. Average pulse frequency is not the limit; pulse width is. **Rejected for wheel speed.**
* **Comparison, continuous switch DRV5023-Q1 (T2 p. 6):** bandwidth 20 kHz min, 30 typ ("the fastest changing magnetic field that can be detected"); output delay 13 typ, 25 max µs; VCC 2.7-38 V; supply current 2.7 mA typ at 25 °C, 3.5 mA max at the top temperature; open-drain; unipolar (south pole); -40 to 125 °C (Q grade). It sees every pass in the grid with margin. **Not selected:** maximum vehicle speed, magnet count and geometry, mounting and the supply current per channel must be checked first.
* **Revisions not read:** SLVSDC7 G (2024) and H (December 2024) exist; any variant they add is unverified here. A faster sampled variant still needs t_w >= t_S,max; the check takes t_S as a parameter.

## IMU

| | LSM6DSV (S1) | LSM6DSV16X (S2) | ISM330DHCX (S3) | MC3419 (S4) |
|---|---|---|---|---|
| Supply VDD / VDDIO | 1.71-3.6 / 1.08-3.6 V (p. 13) | same (p. 14) | 1.71-3.6 / 1.62-3.6 V (p. 13) | 1.7-3.6 V, no separate VDDIO (pp. 9, 18) |
| Interfaces | SPI 10 MHz, I2C 1 MHz, I3C (pp. 14, 16, 25) | same | SPI 10 MHz, I2C 1 MHz (pp. 14-15) | SPI 10 MHz, I2C 1 MHz (pp. 1, 36) |
| Ranges | ±2-16 g, ±125-4000 dps (p. 11) | same | same (p. 10) | ±2-16 g, **no gyroscope** (p. 17) |
| Data rates | accel up to 7680 Hz, gyro 7.5-7680 Hz (pp. 11-12) | same | up to 6667 Hz (p. 11) | 0.5-2000 Hz (p. 17) |
| Noise density | 60 µg/√Hz; 2.8 mdps/√Hz (p. 11) | same | 60 (100 max) µg/√Hz; 5 (8 max) mdps/√Hz (pp. 10-11) | 0.7 mg RMS X/Y at 125 Hz (p. 17) |
| Zero-g offset; drift | ±12 mg; ±0.07 mg/°C (p. 11) | same | ±10 mg; ±0.1 mg/°C typ (p. 10) | ±20 mg chip; ±1 mg/°C (p. 17) |
| Zero-rate offset; drift | ±1 dps; ±0.006 dps/°C (p. 11) | same | ±1 dps; ±0.005 dps/°C typ (p. 10) | n/a |
| Operating temperature | -40 to 85 °C | -40 to 85 °C | -40 to 105 °C (p. 11) | -40 to 85 °C (p. 16) |
| Anti-aliasing | analog filter active in high-performance and normal modes (p. 29) | same (p. 31) | no statement found | LPF at internal rate / 4.255 to 16 (p. 53) |
| Current, accel + gyro | 0.65 mA (p. 13) | same | 1.2 mA typ (p. 13) | 77 µA accel at 100 Hz (p. 18) |

* **Use:** longitudinal acceleration (energy and grade analysis, events) and yaw rate (lap segmentation). Not used for control. Useful bandwidth: vehicle dynamics are a few hertz; sampling at 52 to 208 Hz with the anti-aliasing filter and a digital low-pass is enough. The host model logs at 100 Hz (`host/telematics/sensors.py`).
* **Calibration need:** a ±12 mg zero-g offset equals a road grade of 1.2 %. That is several times the rolling-resistance force of an efficient vehicle, so raw IMU grade cannot be used to estimate rolling resistance. The offset is calibrated at rest (two orientations on a level surface) per run or per temperature, with the drift figures above. Rolling resistance comes from the coast-down (`docs/ENERGY_METHODS.md`).
* **Interface fit:** both ST parts run from the STM32U575's 3.3 V I/O over SPI or I2C. All three ST parts are LGA-14 2.5 x 3 mm.
* **Mounting and environment:** rigid on the chassis near the centre of mass, axes aligned and recorded in the run metadata, away from the motor. The ISM330DHCX alone covers above 85 °C.
* **Verdict:** LSM6DSV and ISM330DHCX are both **Candidates**. The LSM6DSV has lower noise, lower offset drift and a stated anti-aliasing filter; the ISM330DHCX has the wider temperature range. Selection waits for the mounting location and its temperature, and for whether the telematics board already carries an IMU (the proposal names the MC3419, which has no gyroscope and cannot give yaw rate). LSM6DSV and LSM6DSV16X have identical motion specifications; the 16X adds a machine-learning core and Qvar.

## DS18B20

* **Facts (T3):** conversion time max 93.75 / 187.5 / 375 / 750 ms at 9 / 10 / 11 / 12 bit, 12 bit by default (pp. 3, 9). Accuracy ±0.5 °C from -10 to +85 °C, ±1 °C from -30 to +100 °C, ±2 °C from -55 to +125 °C, 3-sigma limits (p. 2). Supply 3.0-5.5 V; 1-Wire with about 5 kΩ pull-up; parasite power needs a strong pull-up during conversion and is not recommended above +100 °C (p. 7). Packages TO-92, SO-8, µSOP. **No thermal time constant and no mounting guidance**; waterproof probes are third-party assemblies with their own, unknown time constants.
* **Fit:** slow temperatures for logging and analysis (battery surface, motor housing, ambient) at 1 Hz or slower.
* **Not suitable for power-stage thermal protection:** a reading is up to 750 ms old before the probe's own lag, and protection must not depend on the telematics unit. The controller keeps its own protection: an NTC at the low-side MOSFETs (TH701) and the motor temperature input (J701) read by the controller (`hardware/kicad`, `docs/HARDWARE_ARCHITECTURE.md`).
* **Before use:** measure each probe's time constant (step test). Choose the measurement points; that sets the quantity. **Candidate (logging only).**

## AS5600

* **Facts (A1):** 0-360° by default, programmable range "18° up to 360°" (p. 1); 12-bit, INL ±1° (p. 8). Outputs analog or PWM (115-920 Hz, p. 7) and I2C Fast-mode Plus at the fixed 7-bit address 0x36 (p. 10), so one device per I2C bus. Supply 4.5-5.5 V, or 3.0-3.6 V with VDD5V and VDD3V3 tied (pp. 5, 9). Diametrically magnetised on-axis magnet; field 30-90 mT (p. 8); air gap 0.5-3 mm typical; axis displacement at most 0.25 mm with a 6 mm magnet (p. 33). Sampling 150 µs; slow-filter settling 0.286-2.2 ms (p. 7). -40 to 125 °C. **No turn counter**: single-turn only.
* **Inconsistency in A1:** p. 19 says a narrowed range is "not scaled"; pp. 21 and 26 still describe scaling. Verify on the bench before relying on a programmed range.
* **Fit:** a steering angle works if the measured shaft turns less than one revolution lock to lock at the mounting point, and if a rigid coaxial magnet mount holds the 0.25 mm displacement. Multi-turn measurement is not available. The steering geometry is unknown. **Optional; Blocked** on the geometry.

## GNSS: NEO-M9N

* **Facts (U1, U2):**
  * Signals and performance (U1 pp. 4-5): L1 only (GPS/QZSS L1C/A, GLONASS L1OF, Galileo E1-B/C, BeiDou B1I), up to 25 Hz, 2.0 m CEP, velocity 0.05 m/s, time pulse 30 ns RMS.
  * Power (U1 pp. 10-11): VCC 2.7-3.6 V, 36 mA tracking with 4 GNSS, 100 mA peak; -40 to +85 °C.
  * RF and antenna supply: RF_IN is a 50 Ω pad with an internal DC block (U2 p. 76). VCC_RF output is VCC - 0.1 V, at most 50 mA; LNA_EN is active high (U1 p. 11, U2 p. 76). No antenna supervisor; short-circuit protection of the antenna supply is the designer's (U2 pp. 77-78). External gain at most 30 dB (U1 p. 11).
  * Interfaces: UART default 38400 baud (U1 p. 15).
  * Connector: the module has none; the carrier board sets the connector.
* **Antenna requirement:** active L1 antenna covering the four L1 signals; powered from VCC_RF with current limiting; total external gain within 30 dB; mounted with sky view. Check reception through the bodywork on the vehicle: conductive composites can block it.
* **Fit:** the 30 ns PPS is far finer than the 1 µs capture assumed by the log's UTC alignment (`docs/ICD.md` 4), and 25 Hz exceeds the 10 Hz the host model logs. **Line blocked:** whether the telematics PCB assembly includes the module (board files not received), and the antenna connector.

## LTE: A7672

* **Variants and bands (L1, Table 1, p. 10):**

  | Variant | 2G fallback (MHz) | LTE-FDD | LTE-TDD |
  |---|---|---|---|
  | A7672S | 900, 1800 | B1, B3, B5, B8 | B34, B38, B39, B40, B41 |
  | A7672E | 900, 1800 | B1, B3, B5, B7, B8, B20 | none |
  | A7672SA | 850, 900, 1800, 1900 | B1, B2, B3, B4, B5, B7, B8, B28, B66 | none |

* **Supply (L1):** VBAT 3.4-4.2 V, 3.8 V recommended (pp. 12, 26). Peak current "can reach 2A" at maximum GSM transmit power (p. 26). Bulk capacitance at least 300 µF if the supply can deliver 2 A, otherwise at least 600 µF (p. 27). Average LTE transmit current up to 859 mA at 23 dBm (B66, p. 62).
* **Interfaces (L1):** antenna pads RF_ANT, GNSS_ANT, BT_ANT, 50 Ω (pp. 54-55); **no diversity input**. Two USIM interfaces at 1.8/3.0 V (pp. 19, 38). Main UART up to 3.6864 Mbit/s, default 115200, RTS/CTS, **1.8 V logic** (pp. 13, 35): a level translator is needed to the 3.3 V MCU. Temperature -30 to +80 °C normal, -40 to +85 °C extended (p. 59).
* **Timing (L1 pp. 31-33):** UART ready about 8 s after power-on. After an emergency-stop power cut, the uplink needs at least this plus network attach before it sends again; the local log covers the gap.
* **MQTT (L2, chapter 18, pp. 408-436):** AT+CMQTT commands. Two clients; QoS 0-2; clean session 0 or 1; keep-alive 1-64800 s; payload up to 10240 bytes; MQTT 3.1, or 3.1.1 with version=4; TLS up to 1.2. The manual covers the "A76XX Series" and does not name the A7672, so applicability is inferred.
* **Network compatibility:** the variant must match the bands of an operator at the event. No per-variant region or operator certification statement was read. The event country is unknown (input sheet item 4).
* **Naming:** the G and NA suffixes appear only in SIMCom's separate SIM7672X line. Confirm which module the proposal means.
* **Power:** from the propulsion battery, downstream of the joulemeter (Articles 56d, 57b). About 0.86 A at 3.8 V while transmitting at full power is about 3.3 W, so the transmit duty cycle is an energy term (`docs/ENERGY_METHODS.md`). **Line blocked:** event country and operator, and whether the PCB assembly includes the modem.

## Pricing and availability

**Blocked.** No distributor page could be opened (list above), so no line has a dated price or stock figure. Search-result snippets were not used as prices. The team obtains dated quotes and enters them with supplier, date and reference in `hardware/bom/procurement.yaml`.

## Verifications still blocked

| Verification | Blocked by |
|---|---|
| Any DRV5032 variant added after Rev F | revisions G and H not readable here |
| STM32U575 electrical and temperature limits | DS13737 not readable here |
| AS5600 document number DS000365 | not printed in the revision read |
| Prices, stock, lead times for every line | distributor sites unreachable |
| Wheel field window and magnet geometry | bench measurement on the vehicle's wheel |
| GNSS reception through the bodywork | test on the vehicle |
| LTE coverage and bands at the event | event country, operator |
