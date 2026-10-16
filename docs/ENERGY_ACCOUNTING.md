# Battery-terminal energy accounting (v0.2)

The quantity every strategy is scored on is **battery-terminal energy** `E = ∫ V_term · I_batt dt` (discharge positive), the quantity a joulemeter at the battery terminals measures. This document lists what that energy contains, where each term is modelled, and which terms are excluded, so that nothing is counted twice or silently dropped. Implementation: `models/vehicle/powertrain.py` (`p_batt`, `breakdown`), `models/vehicle/longitudinal.py` (forces), `models/optimization/strategies.py::simulate` (integration and reconciliation).

## 1. Decomposition

```
E_batt = E_shaft + E_motor_friction + E_motor_Cu+Fe + E_inverter + E_aux          (power map, per mode)
E_shaft = E_wheel + E_drivetrain_loss                                              (vehicle model)
E_wheel = ΔKE + W_resistive + W_friction_brake                                     (dynamics; checked numerically)
```

| Term | Modelled in | Counted in E_batt? | Notes |
|---|---|---|---|
| Shaft output `T·ω` | power map | yes | `T` is the controller's propulsion torque **after** every limit, including the acceleration limit, so the energy charged belongs to the torque actually applied. |
| Motor friction `T_f·ω` | power map | yes (v0.2) | The motor produces `T + T_f` electromagnetically to deliver `T` at the shaft. **v0.1 omitted this term while driving** (≈ 1.5 W at 6 m/s in the synthetic model). |
| Motor copper + iron | power map | yes | Copper from `i_q = (T+T_f)/k_t`. Iron is charged while driving only. |
| Inverter conduction, switching, dead time, gate drive | power map (`models/inverter/losses.py`) | yes | |
| Auxiliary electronics on the battery side of the meter | power map `aux` (synthetic 3 W) | yes, in every mode (also during coast and braking) | Same constant for every strategy. Reported separately as `aux_energy_J`; time-proportional, so equal at matched finish time. Its real value and the joulemeter's position decide whether the companion computer, telemetry modem etc. belong here (`EFFICIENCY_RESEARCH.md` H6). |
| Drivetrain efficiency and drag | vehicle model | via `E_shaft − E_wheel` | The map must **not** also include them: `check_no_double_counting` raises if a map declares `drivetrain` while the vehicle model applies it. |
| Motor drag when coupled and unpowered | vehicle model (resistive force) | no (it is vehicle kinetic energy) | Only without a freewheel. In coast the battery supplies only `aux`. |
| Rolling, aerodynamic, grade, cornering | vehicle model | no (supplied from `E_wheel` or kinetic energy) | |
| **Friction brake** | simulator / DP (`F_brake·distance`) | **no** | Reported separately as `brake_energy_J`: this is kinetic energy (that was paid for earlier by the battery) dissipated by the **driver's** brake. Never added to `E_batt`. Never confused with coast. |
| Regeneration | n/a | n/a | Disabled (ADR-0007); the map refuses negative torque. |
| Battery internal resistance loss | n/a | **excluded by definition** | Inside the battery, upstream of the terminals. |
| Harness, fuse, connector, precharge-resistor, DC-link ESR losses | n/a | **not modelled** | Small but non-zero, and on the controller side of the terminals. Add them as a measured term once the harness exists (stage 6). |
| Kinetic energy left at the finish | n/a | **no credit** | The terminal condition is "finish line crossed; final speed free" for every strategy. Final speed is reported per run. |

## 2. Checks that run on every simulation

* **Mechanical reconciliation:** `W_tractive − (ΔKE + W_resistive + W_brake)`. With the update used (`a = F/m`, `ds = v_mid·dt`), this is exactly zero for consistent bookkeeping. It is reported as `reconciliation_residual_J`; observed values are ~1e-11 J. A run in which force was applied without being charged (as the v0.1 acceleration clip did when it bound) shows a non-zero residual (`optimization_synthetic.md` §2).
* **Loss sign:** `E_batt − W_tractive > 0` (losses + aux are positive).
* **Power-map decomposition:** `breakdown()` parts sum to `p_batt` (test).
* **DP segment balance:** braking segments satisfy `½m(v₁²−v₀²) = −(F_res + F_brake)·ds` within the predictor-corrector tolerance (test), and `E_brake = F_brake · distance` exactly.

## 3. What the controller measures versus what is scored

The controller integrates `V_bus · I_bus` from its own INA228-class meter (`ctrl_energy`). That meter sits on the controller's DC input, downstream of the official joulemeter, so it excludes harness losses upstream of the controller and any auxiliary load not powered through the controller. The two will **not** agree exactly. `VALIDATION_PLAN.md` §4 specifies the cross-check, and §5 says energy decisions use run-level battery-terminal measurements, never phase-shunt estimates.
