# ADR-0010 — Driver authority is wired

Throttle (two redundant tracks), brake switch, eco-cancel, mode switch, arm switch, fault reset, e-stop chain sense and dead-man sense are wired directly to the controller. The controller **reports** them on CAN (`driver_controls`) for logging, but never accepts them from CAN. Manual driving therefore needs no CAN, companion or cellular link (tested: bus-off does not affect MANUAL). The pit network can never arm the vehicle, because no arming message exists.
