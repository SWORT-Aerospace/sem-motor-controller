"""Advisory assurance in SHADOW mode: qualified evidence -> cross-domain witnesses -> advisory conclusions.

    evidence producers (host/telematics: adapters, wheel, sensors)
      -> qualified evidence (host/telematics/evidence.py: one state per value; only VALID is admissible)
      -> cross-domain witnesses (witnesses.py: relations with declared contexts, parameters and causes)
      -> advisory conclusions with receipts (verdicts.py: SUPPORTED, AMBIGUOUS, UNSUPPORTED)

Nothing in this package can command the motor controller: it imports no transport, opens no socket, builds no
frame, and its output is a record for people (tests/telematics/test_receive_only_boundary.py). It names no fault:
an inconsistency is reported as observed, with the causes the evidence cannot yet tell apart.
"""
