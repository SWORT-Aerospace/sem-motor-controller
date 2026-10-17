#!/usr/bin/env python3
"""Generate the hierarchical KiCad schematic DRAFT for the SEM motor controller.

    python3 tools/gen_kicad_schematic.py            # writes hardware/kicad/*
    python3 tools/gen_kicad_schematic.py --check    # + kicad-cli netlist export and connectivity check

DRAFT - NOT FOR FABRICATION. The schematic captures the functional design
(docs/HARDWARE_ARCHITECTURE.md). Every value that depends on the unknown motor,
battery, harness or event rules is written as UNRESOLVED; every part whose
pinout has not yet been checked against a primary datasheet
carries Pin_check = UNVERIFIED. No PCB, footprint assignment, Gerber or
fabrication BOM is produced from this.

Connectivity is made with labels placed exactly on pin connection points
(local labels inside a sheet, hierarchical labels + sheet pins between sheets,
global labels for power rails). The check step exports the netlist with
kicad-cli and compares KiCad's computed connectivity with the intended
connectivity declared below, net by net.
"""
from __future__ import annotations

import argparse
import copy
import csv
import pathlib
import re
import subprocess
import sys
import uuid as uuidlib

from kiutils.items.common import Effects, Font, Justify, PageSettings, Position, Property, TitleBlock
from kiutils.items.schitems import (GlobalLabel, HierarchicalLabel, HierarchicalPin, HierarchicalSheet,
                                    HierarchicalSheetInstance, LocalLabel, NoConnect, SchematicSymbol,
                                    SymbolInstance, Text)
from kiutils.schematic import Schematic
from kiutils.symbol import SymbolLib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "kicad"
LIBDIR = pathlib.Path("/usr/share/kicad/symbols")
PROJECT = "semmc"
REV = "D0.2-draft"
# Date of revision REV, changed together with it. Not the generation date: regenerating the
# same revision must reproduce the committed files byte for byte (the CI drift gate).
REV_DATE = "2026-10-15"
NS = uuidlib.UUID("6f1d2c1e-5e3a-4c55-9a77-5e3b0c0f0a11")

POWER = {"VBAT_PROT", "VDC", "PGND", "GND", "+5V", "+3V3", "+3V3A"}
U = "UNRESOLVED"
UNVERIFIED = {"Pin_check": "UNVERIFIED (pinout not checked against a primary datasheet)"}

# MCU function (from the pin allocation) -> net name, where they differ
MCU_NET = {"PWM_BREAK": "DRV_NFAULT", "PWM_BREAK2": "BRK2_N", "DRV_ENABLE": "MCU_DRV_EN",
           "OUTPUT_ENABLE_FEEDBACK": "DRV_EN_GATED", "ESTOP_CHAIN_SENSE": "HW_PERMIT",
           "EXT_WDG_RST_SENSE": "WDG_RST_N", "EXT_WDG_WDI": "WDG_WDI"}


def uid(*parts) -> str:
    return str(uuidlib.uuid5(NS, "/".join(str(p) for p in parts)))


class P:
    """One part: library symbol, value, pin -> net (None = no-connect)."""

    def __init__(self, prefix, lib, name, value, pins, status="", rating="", mpn="", dnp=False, **extra):
        self.prefix, self.lib, self.name, self.value, self.pins = prefix, lib, name, value, pins
        self.props = {"Status": status, "Rating_basis": rating, "MPN": mpn}
        self.props.update({k: v for k, v in extra.items()})
        self.props = {k: v for k, v in self.props.items() if v}
        self.dnp = dnp
        self.ref = ""


def R(value, a, b, **kw):
    return P("R", "Device", "R", value, {"1": a, "2": b}, **kw)


def C(value, a, b, **kw):
    return P("C", "Device", "C", value, {"1": a, "2": b}, **kw)


def TP(net):
    return P("TP", "Connector", "TestPoint", net, {"1": net}, status="bench test point")


# ----------------------------------------------------------------------------- design data
def sheets(mcu_map: dict) -> list:
    S = []
    # 1 -------------------------------------------------------------- power input
    S.append(("power_input", "Power input, protection, bus shunt, precharge", [
        P("J", "Connector_Generic", "Conn_01x02", "BATTERY_IN", {"1": "VBAT_IN", "2": "PGND"},
          status=U, rating="connector/cable from I_batt,max and V_bat,max (battery/BMS unknown)"),
        P("F", "Device", "Fuse", f"{U} fuse", {"1": "VBAT_IN", "2": "VBAT_F"}, status=U,
          rating="I_batt,max, V_bat,max, breaking capacity >= BMS short-circuit current"),
        P("D", "Device", "D_TVS", f"{U} TVS", {"1": "VBAT_F", "2": "PGND"}, status=U,
          rating="V_standoff >= V_bat,max; V_clamp at surge current < V_DS(abs max) of the bridge MOSFETs"),
        P("U", PROJECT, "RPP_BLOCK", f"{U} reverse-polarity protection", {"IN": "VBAT_F", "OUT": "VBAT_PROT",
                                                                         "GND": "PGND"},
          status=U, rating="ideal-diode controller + N-FETs, or keyed harness only: harness decision pending"),
        C(f"{U} 100V MLCC", "VBAT_PROT", "PGND", status=U, rating=">= 1.25 x V_bat,max"),
        P("R", "Device", "R_Shunt", f"{U} bus shunt", {"1": "VBAT_PROT", "2": "VBAT_SH", "3": "IBUS_SP",
                                                         "4": "IBUS_SN"},
          status=U, rating="I_batt,max into INA228 full-scale range; Kelvin sense pads"),
        R(f"{U} precharge R", "VBAT_SH", "VDC", status=U,
          rating="C_link, V_bat,max, precharge time; pulse energy 0.5*C*V^2 per attempt"),
        P("Q", "Device", "Q_PMOS_GSD", f"{U} bypass P-FET", {"1": "PRE_G", "2": "VBAT_SH", "3": "VDC"}, status=U,
          rating="V_DS >= 1.25 x V_bat,max; continuous I_batt,max; SOA for closing after precharge"),
        R("100k", "VBAT_SH", "PRE_G", status="design value", rating="gate-source hold-off"),
        P("D", "Device", "D_Zener", "12V zener", {"1": "VBAT_SH", "2": "PRE_G"}, status="design value",
          rating="clamps V_GS of the bypass FET (check V_GS abs max of selected FET)"),
        R("47k", "PRE_G", "PRE_D", status="design value - verify",
          rating="zener current (V_bat,max-12V)/R; power (V_bat,max-12V)^2/R"),
        P("Q", "Device", "Q_NMOS_GSD", f"{U} small-signal N-FET", {"1": "PRECHG_EN", "2": "GND", "3": "PRE_D"},
          status=U, rating="V_DS >= 1.25 x V_bat,max (drain sees the battery when off)"),
        R("100k", "PRECHG_EN", "GND", status="design value", rating="bypass OFF while the MCU is in reset"),
        # ERC markers: these rails are driven through a connector, inductor, ferrite bead or switch, which
        # KiCad cannot see as a power source. Not components (no BOM line, no footprint).
        *[P("#FLG", "power", "PWR_FLAG", "PWR_FLAG", {"1": n}, status="ERC marker")
          for n in ("VBAT_PROT", "VDC", "PGND", "GND", "+5V", "+3V3A")],
    ], ["Precharge: the bypass FET is OFF at power-up (R pull-down on PRECHG_EN, MCU pins high-Z in reset).",
        "Firmware closes it only after V_DC >= 0.95 x V_BAT (VBUS_SENSE vs INA228 VBUS).",
        "The vehicle e-stop isolates the battery upstream of J (vehicle hardware, not this board)."]))
    # 2 -------------------------------------------------------------- DC link + OV comparator
    S.append(("dc_link", "DC link, bus-voltage sense, independent over-voltage trip", [
        *[P("C", "Device", "C_Polarized", f"{U} bulk", {"1": "VDC", "2": "PGND"}, status=U,
            rating="ripple current (Kolar-Round at I_ph,max), V_rated >= 1.25 x V_bat,max, ESR, temperature")
          for _ in range(3)],
        *[C(f"{U} MLCC (per half-bridge)", "VDC", "PGND", status=U, rating=">= 100 V X7R, DC-bias derated")
          for _ in range(3)],
        R(f"{U} bleeder", "VDC", "PGND", status=U, rating="discharge time vs power at V_bat,max"),
        R(f"{U} divider top", "VDC", "VBUS_DIV", status=U, rating="ratio = 2.495 V / V_OV,trip (rule 37: FS >= 1.05 OV)"),
        R(f"{U} divider bottom", "VBUS_DIV", "GND", status=U, rating="see top"),
        C("10nF", "VBUS_DIV", "GND", status="design value"),
        R("1k", "VBUS_DIV", "VBUS_SENSE", status="design value", rating="ADC input isolation"),
        P("U", "Comparator", "TLV7041DBV", "TLV7041DBV", {"1": "BRK2_N", "2": "GND", "3": "OV_REF", "4": "VBUS_DIV",
                                                         "5": "+3V3"},
          status="CANDIDATE", mpn="TLV7041DBVR", rating="open-drain: wired-OR into TIM1_BKIN2"),
        R(f"{U} hysteresis", "BRK2_N", "OV_REF", status=U),
        R("10k", "BRK2_N", "+3V3", status="design value"),
        P("U", "Reference_Voltage", "TL431DBZ", "TL431 (2.495 V)", {"1": "OV_REF", "2": "OV_REF", "3": "GND"},
          status="CANDIDATE", mpn="TL431BIDBZR"),
        R("1k", "+3V3", "OV_REF", status="design value", rating="TL431 cathode current ~0.8 mA"),
    ], ["Over-voltage trip is independent of firmware: comparator -> BRK2_N -> TIM1_BKIN2 (outputs off in hardware)."]))
    # 3 -------------------------------------------------------------- bridge
    br = []
    for x in "ABC":
        br += [P("Q", "Device", "Q_NMOS_GDS", f"{U} N-MOSFET HS-{x}", {"1": f"GH_{x}", "2": "VDC", "3": f"PHASE_{x}"},
                 status=U, rating="V_DS >= 1.5 x V_bat,max; I_D, R_DS(on), Q_g, R_thJC from I_ph,max (motor unknown)"),
               P("Q", "Device", "Q_NMOS_GDS", f"{U} N-MOSFET LS-{x}", {"1": f"GL_{x}", "2": f"PHASE_{x}", "3": f"SL_{x}"},
                 status=U, rating="as HS"),
               R("0R", f"GH_{x}_DRV", f"GH_{x}", status="design option", rating="series gate R option; IDRIVE sets slew"),
               R("0R", f"GL_{x}_DRV", f"GL_{x}", status="design option"),
               P("R", "Device", "R_Shunt", f"{U} phase shunt {x}", {"1": f"SL_{x}", "2": "PGND", "3": f"SP_{x}",
                                                                     "4": f"SN_{x}"},
                 status=U, rating="I_ph,max into CSA linear range; P = I_rms^2 R; Kelvin pads")]
    br.append(P("J", "Connector_Generic", "Conn_01x03", "MOTOR_PHASES", {"1": "PHASE_A", "2": "PHASE_B", "3": "PHASE_C"},
                status=U, rating="I_ph,max; motor connector unknown"))
    S.append(("bridge", "Six-switch bridge and low-side shunts", br,
              ["All MOSFET, shunt and connector ratings are UNRESOLVED until motor and battery ratings are measured."]))
    # 4 -------------------------------------------------------------- gate drive
    gd_pins = {"VM": "VDC", "VDRAIN": "VDC", "GND": "PGND", "PAD": "PGND", "CPH": "CP_H", "CPL": "CP_L", "VCP": "VCP",
               "VGLS": "VGLS", "DVDD": "DVDD", "VREF": "+3V3A", "ENABLE": "DRV_EN_GATED", "nFAULT": "DRV_NFAULT",
               "nSCS": "DRV_SPI_NSS", "SCLK": "DRV_SPI_SCK", "SDI": "DRV_SPI_MOSI", "SDO": "DRV_SPI_MISO"}
    for x in "ABC":
        gd_pins.update({f"GH{x}": f"GH_{x}_DRV", f"SH{x}": f"PHASE_{x}", f"GL{x}": f"GL_{x}_DRV",
                        f"SP{x}": f"SP_{x}", f"SN{x}": f"SN_{x}", f"SO{x}": f"SO_{x}",
                        f"INH{x}": f"PWM_{x}_HI", f"INL{x}": f"PWM_{x}_LO"})
    S.append(("gate_drive", "Gate driver, enable chain, startup states", [
        P("U", PROJECT, "DRV8353S", "DRV8353S (candidate)", gd_pins, status="CANDIDATE (SPI, integrated CSAs, VDS monitors)",
          mpn="DRV8353SRTAR (verify)", **UNVERIFIED),
        C("47nF (verify)", "CP_H", "CP_L", status="TYPICAL - verify vs DS", rating=">= V_bat,max + 16 V"),
        C("1uF (verify)", "VCP", "VDC", status="TYPICAL - verify vs DS"),
        C("1uF (verify)", "VGLS", "PGND", status="TYPICAL - verify vs DS"),
        C("1uF (verify)", "DVDD", "GND", status="TYPICAL - verify vs DS"),
        C(f"{U} 100nF 100V", "VDC", "PGND", status=U, rating="VM decoupling at the driver"),
        R("10k", "DRV_NFAULT", "+3V3", status="design value", rating="open-drain nFAULT -> TIM1_BKIN + GPIO"),
        P("U", "74xGxx", "74LVC1G08", "74LVC1G08", {"1": "MCU_DRV_EN", "2": "HW_PERMIT", "3": "GND", "4": "DRV_EN_GATED",
                                                  "5": "+3V3"}, status="CANDIDATE", mpn="SN74LVC1G08DBVR"),
        R("100k", "MCU_DRV_EN", "GND", status="design value", rating="driver disabled while MCU pins are high-Z"),
        R("100k", "DRV_EN_GATED", "GND", status="design value", rating="driver disabled if the AND gate is unpowered"),
        R("10k", "DRV_SPI_NSS", "+3V3", status="design value", rating="SPI deselected at boot"),
        *[R("100k", f"PWM_{x}_{s}", "GND", status="DNP if internal pull-downs verified", dnp=True)
          for x in "ABC" for s in ("HI", "LO")],
    ], ["DRV8353S pin NAMES and NUMBERS are PLACEHOLDERS (primary datasheet not readable here): renumber from TI SLVSDY6x before any footprint/layout.",
        "Gate-driver ENABLE = MCU_DRV_EN AND HW_PERMIT (safety loop + watchdog): firmware alone cannot enable the driver."]))
    # 5 -------------------------------------------------------------- current sense
    cs = []
    for x in "ABC":
        cs += [C("DNP (diff. filter option)", f"SP_{x}", f"SN_{x}", status="DNP option", dnp=True),
               R("100R", f"SO_{x}", f"ISENSE_{x}", status="design value - see timing budget",
                 rating="with 470 pF: tau = 47 ns (settling inside the PWM sampling window)"),
               C("470pF", f"ISENSE_{x}", "GND", status="design value", rating=">> ADC S/H capacitance (charge kick-back)"),
               TP(f"ISENSE_{x}")]
    S.append(("current_sense", "Phase-current sensing (CSA outputs to three ADCs)", cs,
              ["PROPOSED, not substantiated: phase currents to ADC1, ADC2 and ADC3 started by the same TIM1 trigger. "
               "Simultaneity still needs the trigger configuration, ADC synchronization, acquisition windows and a "
               "bench measurement (hardware/timing/timing_budget.md, bring-up stage 4)."]))
    # 6 -------------------------------------------------------------- bus measurement
    S.append(("bus_measurement", "DC-bus energy meter (INA228-class)", [
        P("U", PROJECT, "INA228", "INA228 (candidate)", {"IN+": "IBUS_SP_F", "IN-": "IBUS_SN_F", "VBUS": "VBAT_SH",
                                                         "GND": "GND", "VS": "+3V3", "SCL": "I2C_SCL", "SDA": "I2C_SDA",
                                                         "ALERT": "INA_ALERT", "A0": "GND", "A1": "GND"},
          status="CANDIDATE (85 V common mode, 20-bit)", mpn="INA228AIDGSR (verify)",
          Pin_check="SECONDARY: numbers match the KiCad official library (INA226-derived VSSOP-10) @cf07d539; "
                    "primary TI datasheet NOT read"),
        R("10R (verify)", "IBUS_SP", "IBUS_SP_F", status="TYPICAL - verify input-filter guidance"),
        R("10R (verify)", "IBUS_SN", "IBUS_SN_F", status="TYPICAL - verify input-filter guidance"),
        C("100nF", "IBUS_SP_F", "IBUS_SN_F", status="TYPICAL - verify"),
        C("100nF", "+3V3", "GND", status="design value"),
        R("4.7k", "I2C_SCL", "+3V3", status="design value"),
        R("4.7k", "I2C_SDA", "+3V3", status="design value"),
        R("10k", "INA_ALERT", "+3V3", status="design value"),
    ], ["Energy is integrated from this meter, never from the phase shunts.",
        "Its VBUS input is on the battery side of the precharge, so the precharge check is VBUS_SENSE (link) versus INA228 VBUS (battery)."]))
    # 7 -------------------------------------------------------------- temperature
    S.append(("temperature", "Power-stage and motor temperature", [
        P("TH", "Device", "Thermistor_NTC", "10k NTC (B per selection)", {"1": "TFET_N", "2": "GND"},
          status="CANDIDATE", rating="placed at the low-side MOSFETs"),
        R("10k", "+3V3A", "TFET_N", status="design value"),
        R("1k", "TFET_N", "TEMP_FET", status="design value"),
        C("100nF", "TEMP_FET", "GND", status="design value"),
        P("J", "Connector_Generic", "Conn_01x02", "MOTOR_TEMP", {"1": "TMOT_IN", "2": "GND"}, status=U,
          rating="sensor type unknown (NTC/PTC/KTY/PT1000)"),
        R(f"{U} bias", "+3V3A", "TMOT_IN", status=U, rating="depends on the motor's sensor"),
        R("1k", "TMOT_IN", "TEMP_MOTOR", status="design value"),
        C("100nF", "TEMP_MOTOR", "GND", status="design value"),
        P("D", "Diode", "ESD9B3.3ST5G", "ESD9B3.3ST5G", {"1": "TMOT_IN", "2": "GND"}, status="CANDIDATE"),
    ], ["A missing or implausible temperature derates, it does not fault (firmware MC_DR_TEMP_UNKNOWN)."]))
    # 8 -------------------------------------------------------------- MCU + debug + watchdog
    mcu = {"VDD": "+3V3", "VSS": "GND", "VDDA": "+3V3A", "VSSA": "GND", "VREF+": "+3V3A", "VBAT": "+3V3",
           "PG10": "NRST", "PB8": "BOOT0", "PF0": "HSE_IN", "PF1": "HSE_OUT", "PA13": "SWDIO", "PA14": "SWCLK",
           "PB3": "SWO"}
    mcu.update(mcu_map)
    S.append(("mcu_debug", "MCU, clock, debug, external watchdog", [
        P("U", "MCU_ST_STM32G4", "STM32G474VETx", "STM32G474VET6", mcu, status="CANDIDATE (pin map generated)",
          mpn="STM32G474VET6", Pin_check="KiCad library symbol (pin map from ST open pin data @7d1f151)"),
        *[C("100nF", "+3V3", "GND", status="design value") for _ in range(5)],
        C("4.7uF", "+3V3", "GND", status="design value"),
        P("FB", "Device", "FerriteBead_Small", "600R@100MHz", {"1": "+3V3", "2": "+3V3A"}, status="design value"),
        C("1uF", "+3V3A", "GND", status="design value"), C("10nF", "+3V3A", "GND", status="design value"),
        C("1uF", "+3V3A", "GND", status="design value", rating="VREF+ decoupling (ratiometric with DRV VREF)"),
        R("10k", "BOOT0", "GND", status="design value", rating="boot from flash"),
        C("100nF", "NRST", "GND", status="design value"),
        P("SW", "Switch", "SW_Push", "RESET", {"1": "NRST", "2": "GND"}, status="bench"),
        P("Y", "Device", "Crystal_GND24", "HSE UNSELECTED", {"1": "HSE_IN", "2": "GND", "3": "HSE_OUT", "4": "GND"},
          status=U, rating="frequency NOT selected: depends on the vehicle bus (classic or FD, bit rates) and the CPU "
                           "frequency; candidates 8-40 MHz in hardware/timing/clock_tree_alternatives.md. "
                           "The v0.2 '40 MHz required' claim is withdrawn."),
        C(f"{U} load", "HSE_IN", "GND", status=U, rating="from the selected crystal's C_L and stray"),
        C(f"{U} load", "HSE_OUT", "GND", status=U, rating="see above"),
        P("J", "Connector", "Conn_ARM_JTAG_SWD_10", "SWD", {"1": "+3V3", "2": "SWDIO", "3": "GND", "4": "SWCLK",
                                                          "5": "GND", "6": "SWO", "7": None, "8": None, "9": "GND",
                                                          "10": "NRST"}, status="bench only"),
        P("J", "Connector_Generic", "Conn_01x03", "UART (bench)", {"1": "DBG_UART_TX", "2": "DBG_UART_RX", "3": "GND"},
          status="bench only; not populated for competition"),
        R("1k", "LED_STATUS", "LED_S_A", status="design value"),
        P("D", "Device", "LED", "green", {"1": "GND", "2": "LED_S_A"}, status="design value"),
        R("1k", "LED_FAULT", "LED_F_A", status="design value"),
        P("D", "Device", "LED", "red", {"1": "GND", "2": "LED_F_A"}, status="design value"),
        P("U", "Power_Supervisor", "MAX6369", "MAX6369 (candidate)", {"1": "WDG_WDI", "2": "GND", "3": None,
                                                                     "4": "GND", "5": "+3V3", "6": "GND",
                                                                     "7": "WDG_RST_N", "8": "+3V3"},
          status="CANDIDATE - SET0..2 strap per timeout table (verify)", mpn="MAX6369KA+T"),
        R("10k", "WDG_RST_N", "+3V3", status="design value"),
        R("0R", "WDG_RST_N", "NRST", status="design option", rating="watchdog resets the MCU"),
        P("D", "Device", "D_Schottky", "BAT54", {"1": "WDG_RST_N", "2": "HW_PERMIT"}, status="CANDIDATE",
          rating="watchdog timeout pulls HW_PERMIT low (driver disabled in hardware)"),
        TP("+3V3"), TP("NRST"), TP("DRV_NFAULT"),
    ], ["Unused MCU pins are no-connect in this draft; pin functions come from hardware/interfaces/pin_allocation_STM32G474VBCETx.csv."]))
    # 9 -------------------------------------------------------------- hall inputs
    hl = [P("J", "Connector_Generic", "Conn_01x05", "HALL", {"1": "HALL_PWR", "2": "GND", "3": "HA_IN", "4": "HB_IN",
                                                             "5": "HC_IN"}, status=U, rating="motor hall connector unknown"),
          P("JP", "Jumper", "SolderJumper_3_Open", "HALL SUPPLY 5V/3V3", {"1": "+5V", "2": "HALL_PWR_SEL", "3": "+3V3"},
            status=U, rating="hall sensor supply voltage unknown"),
          P("F", "Device", "Polyfuse_Small", f"{U} polyfuse", {"1": "HALL_PWR_SEL", "2": "HALL_PWR"}, status=U,
            rating="hall supply current unknown")]
    for x in "ABC":
        hl += [R("4.7k", f"H{x}_IN", "+3V3", status="design value", rating="assumes open-collector hall outputs (verify)"),
               R("1k", f"H{x}_IN", f"HALL_{x}", status="design value"),
               C("1nF", f"HALL_{x}", "GND", status="design value", rating="tau = 1 us"),
               P("D", "Diode", "ESD9B5.0ST5G", "ESD9B5.0ST5G", {"1": f"H{x}_IN", "2": "GND"}, status="CANDIDATE")]
    S.append(("hall_inputs", "Hall sensor inputs", hl, ["Hall output stage (open collector vs push-pull) and supply are unknown."]))
    # 10 ------------------------------------------------------------- driver controls
    dc = [P("J", "Connector_Generic", "Conn_01x12", "DRIVER_CONTROLS",
            {"1": "SENS_5V", "2": "GND", "3": "THR_A_IN", "4": "THR_B_IN", "5": "BRAKE_IN", "6": "CANCEL_IN",
             "7": "MODE_IN", "8": "ARM_IN", "9": "RESET_IN", "10": "DEADMAN_IN", "11": "LOOP_P", "12": "LOOP_N"},
            status=U, rating="vehicle harness connector unknown"),
          P("F", "Device", "Polyfuse_Small", "polyfuse (sensor supply)", {"1": "+5V", "2": "SENS_5V"}, status="CANDIDATE")]
    for x in "AB":
        dc += [R("10k", f"THR_{x}_IN", f"THROTTLE_{x}", status="design value - assumes 0-5 V ratiometric pedal"),
               R("18k", f"THROTTLE_{x}", "GND", status="design value", rating="5 V -> 3.21 V"),
               R("100k", f"THR_{x}_IN", "GND", status="design value", rating="open wire reads 0 -> implausible"),
               C("100nF", f"THROTTLE_{x}", "GND", status="design value")]
    for src, net in (("BRAKE_IN", "BRAKE_SWITCH"), ("CANCEL_IN", "ECO_CANCEL"), ("MODE_IN", "MODE_SWITCH"),
                     ("ARM_IN", "ARM_SWITCH"), ("RESET_IN", "FAULT_RESET"), ("DEADMAN_IN", "DEADMAN_SENSE")):
        dc += [R("10k", src, "+3V3", status="design value"), R("1k", src, net, status="design value"),
               C("10nF", net, "GND", status="design value"),
               P("D", "Diode", "ESD9B5.0ST5G", "ESD9B5.0ST5G", {"1": src, "2": "GND"}, status="CANDIDATE")]
    dc += [P("U", "Isolator", "PC817", "PC817 (safety-loop sense)", {"1": "LOOP_A", "2": "LOOP_N", "3": "HW_PERMIT",
                                                                     "4": "+3V3"}, status="CANDIDATE"),
           R(f"{U} LED series", "LOOP_P", "LOOP_A", status=U, rating="safety-loop voltage unknown (I_F ~ 5 mA)"),
           R("10k", "HW_PERMIT", "GND", status="design value", rating="HW_PERMIT low unless the loop is energised"),
           C("1nF", "HW_PERMIT", "GND", status="design value")]
    S.append(("driver_controls", "Wired driver controls and safety-loop sense", dc,
              ["HW_PERMIT is high only while the vehicle safety loop (e-stop + dead-man) is energised and the watchdog is not asserting.",
               "Brake switch: normally closed preferred (fails safe); the firmware polarity is configurable."]))
    # 11 ------------------------------------------------------------- CAN
    S.append(("can_phy", "CAN physical layer", [
        P("U", "Interface_CAN_LIN", "TJA1051T-3", "TJA1051T/3", {"1": "CAN_TX", "2": "GND", "3": "+5V", "4": "CAN_RX",
                                                               "5": "+3V3", "6": "CAN_L", "7": "CAN_H", "8": "CAN_S"},
          status="CANDIDATE (alternate TCAN1042V, pin-compatible class - verify)", mpn="TJA1051T/3/1J"),
        R("10k", "CAN_S", "GND", status="design value", rating="normal (not silent) mode"),
        C("100nF", "+5V", "GND", status="design value"), C("100nF", "+3V3", "GND", status="design value"),
        P("D", "Power_Protection", "NUP2105L", "NUP2105L", {"1": "CAN_H", "2": "CAN_L", "3": "GND"}, status="CANDIDATE"),
        P("JP", "Jumper", "SolderJumper_2_Open", "TERM", {"1": "CAN_H", "2": "TERM_H"}, status=U,
          rating="close only if this node is a bus end (harness unknown)"),
        R("60.4R", "TERM_H", "TERM_MID", status="design value"),
        R("60.4R", "TERM_MID", "TERM_L", status="design value"),
        P("JP", "Jumper", "SolderJumper_2_Open", "TERM", {"1": "TERM_L", "2": "CAN_L"}, status=U),
        C("4.7nF", "TERM_MID", "GND", status="design value", rating="split termination"),
        P("J", "Connector_Generic", "Conn_01x04", "CAN", {"1": "CAN_H", "2": "CAN_L", "3": "GND", "4": "CAN_SHLD"},
          status=U, rating="vehicle CAN harness connector, pinout and termination UNKNOWN (telematics proposal: CANH, CANL, GND)"),
        C("1nF", "CAN_SHLD", "GND", status=U, rating="shield termination per harness"),
    ], ["Classic CAN at 500 kbit/s assumed; protocol block 0x300-0x33F, base set by calibration (docs/ICD.md section 2). Bit timing and termination must match the vehicle bus."]))
    # 12 ------------------------------------------------------------- aux rails
    S.append(("aux_rails", "Auxiliary rails and ground star point", [
        P("U", "Regulator_Switching", "LM5164DDA", "LM5164 (candidate)", {"1": "GND", "2": "VBAT_PROT", "3": "BUCK_EN",
                                                                         "4": "BUCK_RON", "5": "BUCK_FB", "6": "BUCK_PG",
                                                                         "7": "BUCK_BST", "8": "BUCK_SW", "9": "GND"},
          status="CANDIDATE (100 V input class - verify)", mpn="LM5164DDAR"),
        C(f"{U} 2.2uF 100V", "VBAT_PROT", "GND", status=U, rating=">= 1.25 x V_bat,max"),
        C(f"{U} 2.2uF 100V", "VBAT_PROT", "GND", status=U),
        R(f"{U} UVLO top", "VBAT_PROT", "BUCK_EN", status=U, rating="from V_bat,min"),
        R(f"{U} UVLO bottom", "BUCK_EN", "GND", status=U),
        R(f"{U} RON", "BUCK_RON", "GND", status=U, rating="on-time vs V_IN range (battery unknown)"),
        C("2.2nF (verify)", "BUCK_BST", "BUCK_SW", status="TYPICAL - verify vs DS"),
        P("L", "Device", "L", f"{U} inductor", {"1": "BUCK_SW", "2": "+5V"}, status=U,
          rating="per DS design procedure for the V_IN range and 5 V load"),
        R("31.6k (verify VFB)", "+5V", "BUCK_FB", status="TYPICAL - verify"),
        R("10k", "BUCK_FB", "GND", status="design value"),
        C("22uF", "+5V", "GND", status="design value"), C("22uF", "+5V", "GND", status="design value"),
        R("100k", "BUCK_PG", "+3V3", status="design value"),
        P("U", "Regulator_Linear", "TLV75533PDBV", "TLV75533", {"1": "+5V", "2": "GND", "3": "+5V", "4": None,
                                                              "5": "+3V3"}, status="CANDIDATE", mpn="TLV75533PDBVR"),
        C("1uF", "+5V", "GND", status="design value"), C("1uF", "+3V3", "GND", status="design value"),
        P("NT", "Device", "NetTie_2", "PGND-GND star", {"1": "PGND", "2": "GND"}, status="layout: single point at the shunt ground"),
        TP("+5V"), TP("GND"), TP("BUCK_PG"),
    ], ["Logic rails run from VBAT_PROT (before precharge), so the MCU is alive while the link precharges."]))
    return S


# ----------------------------------------------------------------------------- custom symbols
CUSTOM = {
    # name: (description, left pins, right pins); pins are (name, electrical type). Numbers are
    # PLACEHOLDERS assigned in order and MUST be replaced from the datasheet pin table.
    "DRV8353S": ("100 V three-phase smart gate driver, SPI, 3 CSAs (TI DRV8353S, candidate). PLACEHOLDER: pin names "
                 "and numbers NOT verified (no primary datasheet and no library symbol available). Not footprint-ready.",
                 [("VM", "power_in"), ("VDRAIN", "input"), ("CPH", "passive"), ("CPL", "passive"), ("VCP", "passive"),
                  ("VGLS", "passive"), ("DVDD", "power_out"), ("VREF", "power_in"), ("INHA", "input"), ("INLA", "input"),
                  ("INHB", "input"), ("INLB", "input"), ("INHC", "input"), ("INLC", "input"), ("ENABLE", "input"),
                  ("nFAULT", "open_collector"), ("nSCS", "input"), ("SCLK", "input"), ("SDI", "input"),
                  ("SDO", "output"), ("GND", "power_in"), ("PAD", "power_in")],
                 [("GHA", "output"), ("SHA", "passive"), ("GLA", "output"), ("GHB", "output"), ("SHB", "passive"),
                  ("GLB", "output"), ("GHC", "output"), ("SHC", "passive"), ("GLC", "output"), ("SPA", "input"),
                  ("SNA", "input"), ("SPB", "input"), ("SNB", "input"), ("SPC", "input"), ("SNC", "input"),
                  ("SOA", "output"), ("SOB", "output"), ("SOC", "output")]),
    # INA228 VSSOP-10 (DGS) numbers: CROSS-CHECKED against the KiCad official library (Sensor_Energy INA228 extends
    # INA226, footprint TSSOP-10 3x3 mm P0.5, kicad-symbols @cf07d539), a SECONDARY source. TI datasheet not read here.
    "INA228": ("85 V 20-bit power/energy monitor, I2C (TI INA228AIDGSR, VSSOP-10). Pin numbers cross-checked against "
               "the KiCad library (secondary); primary TI datasheet verification pending.",
               [("IN+", "input", "10"), ("IN-", "input", "9"), ("VBUS", "input", "8"), ("VS", "power_in", "6"),
                ("GND", "power_in", "7")],
               [("SCL", "input", "5"), ("SDA", "bidirectional", "4"), ("ALERT", "open_collector", "3"),
                ("A0", "input", "2"), ("A1", "input", "1")]),
    "RPP_BLOCK": ("UNRESOLVED reverse-polarity protection block (implementation pending harness/current decision)",
                  [("IN", "passive"), ("GND", "passive")], [("OUT", "passive")]),
}


def write_custom_lib(path: pathlib.Path):
    out = ["(kicad_symbol_lib (version 20211014) (generator semmc_gen)"]
    for name, (desc, left, right) in CUSTOM.items():
        n = max(len(left), len(right))
        h = (n + 1) * 2.54
        w = 25.4 if name != "RPP_BLOCK" else 15.24
        top = h / 2
        out.append(f'  (symbol "{name}" (in_bom yes) (on_board yes)')
        out.append(f'    (property "Reference" "U" (id 0) (at 0 {top + 2.54:.2f} 0) (effects (font (size 1.27 1.27))))')
        out.append(f'    (property "Value" "{name}" (id 1) (at 0 {-top - 2.54:.2f} 0) (effects (font (size 1.27 1.27))))')
        out.append('    (property "Footprint" "" (id 2) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        out.append('    (property "Datasheet" "" (id 3) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        out.append(f'    (property "ki_description" "{desc}" (id 4) (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        out.append(f'    (symbol "{name}_0_1" (rectangle (start {-w/2:.2f} {top:.2f}) (end {w/2:.2f} {-top:.2f}) '
                   '(stroke (width 0.254) (type default)) (fill (type background))))')
        out.append(f'    (symbol "{name}_1_1"')
        num = 1
        for side, pins in ((-1, left), (1, right)):
            for i, pin in enumerate(pins):
                pn, et = pin[0], pin[1]
                y = top - 2.54 * (i + 1)
                x = side * (w / 2 + 2.54)
                ang = 0 if side < 0 else 180
                out.append(f'      (pin {et} line (at {x:.2f} {y:.2f} {ang}) (length 2.54) '
                           f'(name "{pn}" (effects (font (size 1.27 1.27)))) '
                           f'(number "{pin[2] if len(pin) > 2 else num}" (effects (font (size 1.27 1.27)))))')
                num += 1
        out.append("    )\n  )")
    out.append(")")
    path.write_text("\n".join(out) + "\n")


# ----------------------------------------------------------------------------- symbol access
_LIBS: dict = {}


def lib_symbol(lib: str, name: str):
    if lib not in _LIBS:
        p = OUT / f"{PROJECT}.kicad_sym" if lib == PROJECT else LIBDIR / f"{lib}.kicad_sym"
        _LIBS[lib] = {s.entryName: s for s in SymbolLib.from_file(str(p)).symbols}
    d = _LIBS[lib]
    s = copy.deepcopy(d[name])
    if s.extends:                                    # flatten derived symbols
        base = copy.deepcopy(d[s.extends])
        while base.extends:
            base = copy.deepcopy(d[base.extends])
        props = {p.key: p for p in base.properties}
        for p in s.properties:
            props[p.key] = p
        base.properties = list(props.values())
        base.entryName = name
        for u in base.units:
            u.entryName = name
        base.extends = None
        s = base
    s.libraryNickname = lib
    return s


def pin_table(sym):
    """[(number, name, x, y, angle)] of all pins of unit 0/1 (library coordinates)."""
    pins = []
    for u in sym.units:
        if u.unitId in (0, 1):
            for p in u.pins:
                pins.append((p.number, p.name, p.position.X, p.position.Y, p.position.angle or 0, p.electricalType))
    return pins


def resolve_pins(part: P, sym) -> list:
    """Map the part's pin keys (number or name) to (number, x, y, angle, net). Every pin is mapped."""
    table = pin_table(sym)
    out = []
    for num, name, x, y, a, et in table:
        if num in part.pins:
            net = part.pins[num]
        elif name in part.pins:
            net = part.pins[name]
        else:
            net = None
        out.append((num, name, x, y, a, et, net))
    keys = set(part.pins)
    known = {t[0] for t in table} | {t[1] for t in table}
    bad = keys - known
    if bad:
        raise ValueError(f"{part.lib}:{part.name}: unknown pin keys {sorted(bad)}")
    return out


# ----------------------------------------------------------------------------- generation
def fx(h=1.27, hide=False, just=None):
    return Effects(font=Font(height=h, width=h), justify=Justify(horizontally=just) if just else Justify(), hide=hide)


def label_angle(pin_angle: float) -> int:
    return {0: 180, 180: 0, 90: 270, 270: 90}[int(pin_angle) % 360]


def mcu_map_from_csv() -> dict:
    p = ROOT / "hardware" / "interfaces" / "pin_allocation_STM32G474VBCETx.csv"
    m = {}
    with p.open() as fh:
        for row in csv.DictReader(fh):
            m[row["pin"].split("-")[0]] = MCU_NET.get(row["function"], row["function"])
    return m


def build(check: bool) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    write_custom_lib(OUT / f"{PROJECT}.kicad_sym")
    design = sheets(mcu_map_from_csv())
    root_uuid = uid("root")
    date = REV_DATE
    # net -> sheets using it
    use = {}
    for sname, _t, parts, _n in design:
        for prt in parts:
            for net in prt.pins.values():
                if net:
                    use.setdefault(net, set()).add(sname)
    hier = {n for n, ss in use.items() if len(ss) > 1 and n not in POWER}
    counters = {}
    expected = {}       # net -> set((ref, pin))
    root = Schematic.create_new()
    root.version, root.generator = "20211014", "semmc_gen"
    root.uuid = root_uuid
    root.paper = PageSettings(paperSize="A3")
    root.titleBlock = TitleBlock(title="SEM motor controller - DRAFT - NOT FOR FABRICATION", date=date, revision=REV,
                                 company="SWORT Aerospace / SEM team",
                                 comments={1: "Functional schematic draft: ratings UNRESOLVED until motor/battery measured",
                                           2: "Pinouts marked UNVERIFIED must be checked against primary datasheets",
                                           3: "Generated by tools/gen_kicad_schematic.py - edit the generator, not the files"})
    root.sheetInstances = [HierarchicalSheetInstance(instancePath="/", page="1")]
    for si, (sname, title, parts, notes) in enumerate(design, start=1):
        sh_uuid = uid("sheet", sname)
        sch = Schematic.create_new()
        sch.version, sch.generator = "20211014", "semmc_gen"
        sch.uuid = sh_uuid
        big = sname == "mcu_debug"
        sch.paper = PageSettings(paperSize="A1" if big else "A2")
        sch.titleBlock = TitleBlock(title=f"{title} - DRAFT, NOT FOR FABRICATION", date=date, revision=REV,
                                    company="SWORT Aerospace / SEM team",
                                    comments={1: "UNRESOLVED = depends on motor/battery/harness/rules inputs",
                                              2: "Pin_check UNVERIFIED = pinout not checked against a primary datasheet"})
        libs = {}
        x0, y0 = 40.0, 50.0
        col_x, row_y, row_h = x0, y0, 0.0
        max_w = 760.0 if big else 520.0
        for prt in parts:
            sym = lib_symbol(prt.lib, prt.name)
            libs[f"{prt.lib}:{prt.name}"] = sym
            pins = resolve_pins(prt, sym)
            xs = [p[2] for p in pins] or [0]
            ys = [p[3] for p in pins] or [0]
            w = (max(xs) - min(xs)) + 60.0
            h = (max(ys) - min(ys)) + 25.0
            if col_x + w > max_w:
                col_x, row_y, row_h = x0, row_y + row_h, 0.0
            X = round(round((col_x - min(xs) + 30.0) / 2.54) * 2.54, 4)
            Y = round(round((row_y + max(ys) + 12.0) / 2.54) * 2.54, 4)
            col_x += w
            row_h = max(row_h, h)
            k = (si, prt.prefix)
            counters[k] = counters.get(k, 0) + 1
            prt.ref = f"{prt.prefix}{si * 100 + counters[k]}"     # sheet 3 -> R301, R302 ...
            s_uuid = uid("sym", sname, prt.ref)
            props = [Property("Reference", prt.ref, 0, Position(X, Y - 5.08, 0), fx()),
                     Property("Value", prt.value, 1, Position(X, Y + 5.08, 0), fx()),
                     Property("Footprint", "", 2, Position(X, Y, 0), fx(hide=True)),
                     Property("Datasheet", "", 3, Position(X, Y, 0), fx(hide=True))]
            for i, (k, v) in enumerate(prt.props.items()):
                props.append(Property(k, v, 4 + i, Position(X, Y, 0), fx(hide=True)))
            ss = SchematicSymbol(libraryNickname=prt.lib, entryName=prt.name, position=Position(X, Y, 0), unit=1,
                                 inBom=not prt.dnp, onBoard=True, uuid=s_uuid, properties=props,
                                 pins={p[0]: uid("pin", s_uuid, p[0]) for p in pins})
            if prt.dnp:
                ss.dnp = True
            sch.schematicSymbols.append(ss)
            root.symbolInstances.append(SymbolInstance(path=f"/{sh_uuid}/{s_uuid}", reference=prt.ref, unit=1,
                                                       value=prt.value, footprint=""))
            for num, name, px, py, pa, et, net in pins:
                ax, ay = round(X + px, 4), round(Y - py, 4)
                if net is None:
                    # A pin the library already types as no_connect needs no flag: KiCad 8 ERC reports
                    # the extra flag as both "connected" and "dangling" (seen on J801 KEY, MAX6369 NC,
                    # TLV755 NC).
                    if et != "no_connect":
                        sch.noConnects.append(NoConnect(Position(ax, ay), uid("nc", s_uuid, num)))
                    continue
                if not prt.ref.startswith("#"):          # power flags are not netlist components
                    expected.setdefault(net, set()).add((prt.ref, num))
                la = label_angle(pa)
                just = "right" if la in (180, 270) else "left"
                lu = uid("lbl", s_uuid, num)
                if net in POWER:
                    sch.globalLabels.append(GlobalLabel(text=net, shape="passive", position=Position(ax, ay, la),
                                                        effects=fx(just=just), uuid=lu))
                elif net in hier:
                    sch.hierarchicalLabels.append(HierarchicalLabel(text=net, shape="bidirectional",
                                                                    position=Position(ax, ay, la),
                                                                    effects=fx(just=just), uuid=lu))
                else:
                    sch.labels.append(LocalLabel(text=net, position=Position(ax, ay, la), effects=fx(just=just), uuid=lu))
        sch.libSymbols = list(libs.values())
        ny = 20.0
        for n in notes:
            sch.texts.append(Text(text=n, position=Position(20.0, ny, 0), effects=fx(1.8, just="left"),
                                  uuid=uid("txt", sname, n)))
            ny += 5.0
        fname = f"{si:02d}_{sname}.kicad_sch"
        sch.filePath = str(OUT / fname)
        sch.to_file()
        # sheet symbol on the root
        nets = sorted(n for n in hier if sname in use[n])
        col, rowi = (si - 1) % 4, (si - 1) // 4
        sx, sy = 25.4 + col * 96.52, 40.64 + rowi * 91.44
        hgt = max(20.32, 2.54 * (len(nets) + 2))
        hs = HierarchicalSheet(position=Position(sx, sy), width=55.88, height=hgt, uuid=sh_uuid,
                               sheetName=Property("Sheet name", sname, 0, Position(sx, sy - 0.8, 0), fx(just="left")),
                               fileName=Property("Sheet file", fname, 1, Position(sx, sy + hgt + 0.8, 0), fx(just="left")))
        for k, n in enumerate(nets):
            py = sy + 2.54 * (k + 1)
            px = sx + 55.88
            hs.pins.append(HierarchicalPin(name=n, connectionType="bidirectional", position=Position(px, py, 0),
                                           effects=fx(just="right"), uuid=uid("spin", sname, n)))
            root.labels.append(LocalLabel(text=n, position=Position(px, py, 0), effects=fx(just="left"),
                                          uuid=uid("rlbl", sname, n)))
        root.sheets.append(hs)
        root.sheetInstances.append(HierarchicalSheetInstance(instancePath=f"/{sh_uuid}", page=str(si + 1)))
    root.texts.append(Text(text="DRAFT - NOT FOR FABRICATION. Functional architecture only; component selection is not frozen.",
                           position=Position(25.4, 25.4, 0), effects=fx(2.5, just="left"), uuid=uid("rt", 1)))
    root.filePath = str(OUT / f"{PROJECT}.kicad_sch")
    root.to_file()
    (OUT / f"{PROJECT}.kicad_pro").write_text('{"meta": {"filename": "semmc.kicad_pro", "version": 1}}\n')
    (OUT / "sym-lib-table").write_text(f'(sym_lib_table\n  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/{PROJECT}.kicad_sym")(options "")(descr "project symbols (UNVERIFIED pinouts)"))\n)\n')
    write_bom(design)
    n_parts = sum(len(p) for _s, _t, p, _n in design)
    print(f"wrote {len(design)} sheets, {n_parts} parts, {len(expected)} nets to {OUT.relative_to(ROOT)}")
    if check:
        return check_netlist(expected, design)
    return 0


# ----------------------------------------------------------------------------- BOM
def write_bom(design):
    """Draft BOM grouped from the schematic data (hardware/bom/BOM_draft.csv). Pricing is added by
    tools/price_bom.py from hardware/bom/pricing.yaml; nothing here is order-ready."""
    groups = {}
    for sname, _t, parts, _n in design:
        for prt in parts:
            if prt.ref.startswith("#"):
                continue
            key = (prt.lib, prt.name, prt.value, prt.props.get("MPN", ""), prt.dnp)
            g = groups.setdefault(key, {"refs": [], "sheets": set(), "status": prt.props.get("Status", ""),
                                        "rating": prt.props.get("Rating_basis", ""),
                                        "pin_check": prt.props.get("Pin_check", "")})
            g["refs"].append(prt.ref)
            g["sheets"].add(sname)
    path = ROOT / "hardware" / "bom" / "BOM_draft.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["line", "refs", "qty", "symbol", "value", "mpn_candidate", "dnp", "selection_status",
                    "rating_basis", "pin_check", "sheets"])
        for i, ((lib, name, value, mpn, dnp), g) in enumerate(sorted(groups.items(), key=lambda kv: kv[1]["refs"][0]), 1):
            w.writerow([i, " ".join(sorted(g["refs"])), len(g["refs"]), f"{lib}:{name}", value, mpn, "DNP" if dnp else "",
                        g["status"], g["rating"], g["pin_check"], " ".join(sorted(g["sheets"]))])


# ----------------------------------------------------------------------------- check
def _sexp(text):
    tok = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tok:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def check_netlist(expected: dict, design) -> int:
    net_path = OUT / "semmc.net"
    r = subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(net_path),
                        str(OUT / f"{PROJECT}.kicad_sch")], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 2
    # kicad-cli records the absolute checkout path and the export time; make the
    # committed netlist independent of both (repository-relative paths, revision date).
    text = net_path.read_text().replace(str(OUT) + "/", "hardware/kicad/")
    text = re.sub(r'^(    \(date ")[^"]*("\))$', lambda m: m.group(1) + REV_DATE + m.group(2), text, count=1, flags=re.M)
    net_path.write_text(text)
    tree = _sexp(text)
    nets_node = next(x for x in tree if isinstance(x, list) and x and x[0] == "nets")
    got = {}
    for n in nets_node[1:]:
        name = next(x[1] for x in n if isinstance(x, list) and x[0] == "name")
        nodes = {(next(y[1] for y in x if isinstance(y, list) and y[0] == "ref"),
                  next(y[1] for y in x if isinstance(y, list) and y[0] == "pin"))
                 for x in n if isinstance(x, list) and x[0] == "node"}
        got[name] = nodes
    # map KiCad net names (/sheet/NET, NET) to intended names by node-set equality
    by_nodes = {frozenset(v): k for k, v in got.items()}
    problems = []
    for net, nodes in sorted(expected.items()):
        if frozenset(nodes) not in by_nodes:
            hit = [k for k, v in got.items() if nodes & v]
            problems.append(f"net {net}: expected {len(nodes)} nodes; KiCad nets touching them: {hit[:4]}")
        if len(nodes) < 2:
            problems.append(f"net {net}: only {len(nodes)} connection(s) - single-pin net")
    extra = [k for k, v in got.items() if frozenset(v) not in {frozenset(n) for n in expected.values()}
             and not k.startswith("unconnected-")]
    for k in extra:
        problems.append(f"unexpected KiCad net {k}: {sorted(got[k])[:6]}")
    unc = [k for k in got if k.startswith("unconnected-")]
    rep = OUT / "CONNECTIVITY_CHECK.md"
    lines = ["# Schematic connectivity check (generated)", "",
             f"kicad-cli {subprocess.run(['kicad-cli', 'version'], capture_output=True, text=True).stdout.strip()} "
             "exported the netlist of the draft; every intended net was compared with KiCad's computed connectivity "
             "(same node set).", "",
             f"* intended nets: {len(expected)}", f"* KiCad nets: {len(got)} (of which no-connect singletons: {len(unc)})",
             f"* problems: {len(problems)}", ""]
    lines += [f"- {p}" for p in problems] or ["No mismatches: KiCad connectivity equals the intended connectivity."]
    lines += ["", "This checks connectivity only. It is not an electrical rules check (the KiCad ERC runs separately: "
              "`tools/run_kicad_erc.sh` with KiCad 8 or newer, in the CI `erc` job) and not a design review."]
    rep.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:8]))
    for p in problems[:30]:
        print("  ", p)
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    return build(ap.parse_args().check)


if __name__ == "__main__":
    sys.exit(main())
