# Propulsion battery and BMS

Status: **team-reported values only; nothing here is datasheet-verified.** Hardware configuration validation stays blocked (`config/vehicle.unconfigured.yaml` fails `--mode hw`) until the specifications in section 3 are confirmed from the battery and BMS documentation.

## 1. Values reported by the team

| Quantity | Value | Source | Status |
|---|---|---|---|
| Nominal voltage | 48 V | team message, 2026-10-16 | reported; pending datasheet confirmation |
| Rated capacity | 10 Ah | team message, 2026-10-16 | reported; pending datasheet confirmation |
| Nominal energy | about 480 Wh (48 V x 10 Ah) | derived from the two values above | nominal, not measured usable energy |

The configuration file keeps `battery.nominal_voltage_V` null and records the reported values in `battery.notes`: the file accepts only verified or measured values.

## 2. What these values do not establish

* chemistry and series cell count;
* maximum (fully charged) voltage and minimum operating voltage;
* continuous and peak discharge current, and the peak duration;
* BMS protection thresholds (cell over-voltage, under-voltage, over-current, temperature) and its communication interface, if any;
* permitted charging current and regenerative current.

**10 Ah is a charge capacity, not a current limit.** It does not mean 10 A, and no discharge or charge current limit follows from it.

**48 V nominal is not a design rating.** MOSFETs, gate drivers, bulk capacitors, TVS diodes, fuses and DC-DC converters (controller and telematics) are rated from the maximum pack voltage, its transients and a design margin, and from the BMS current limits. None of these parts is selected from 48 V alone (`hardware/bom/README.md`, `docs/PROCUREMENT.md`).

## 3. Still required

1. Battery and BMS make and model numbers.
2. Photographs of the battery and BMS labels.
3. Battery and BMS datasheets: chemistry, series cells, maximum charged and minimum operating voltage, continuous and peak discharge current with duration, BMS thresholds and interface, charge and regenerative current limits, connector.

These are item 2 of `docs/INPUT_SHEET.md`.

## 4. Rule checks that depend on the battery (2026 Chapter I, `docs/RULES_COMPLIANCE.md`)

| Rule | Check | Status |
|---|---|---|
| 57a: at most 60 V on board at any point, by design | maximum charged voltage plus transients < 60 V | **open**: the maximum voltage is not known |
| 57d iv: lithium battery at most 1,000 Wh; if not rated in Wh, Ah x nominal V | 10 Ah x 48 V = 480 Wh by the rule's own method | **open until the datasheet confirms** the rating and the nominal voltage; the reported values give 480 Wh |
| 57b: one battery; no accessory battery for Battery Electric vehicles | all electronics, telematics included, run from this battery downstream of the joulemeter | design rule (`docs/TELEMETRY_INTEGRATION.md`) |
| 57d i, 66c: BMS tailored to the chemistry, automatic isolation on cell over-discharge and over-current | BMS datasheet | **open** |
