# Evidence recorder: telemetry-unit interface (proposal, host-tested)

The vehicle half of the record requests used by the schedulers. The code is portable C11 in [`recorder/`](recorder/), tested on a host with sanitizers, and it compiles for the Cortex-M4F. It has **not** run on the telemetry unit: the unit's firmware and platform layer are not written ([`../docs/TELEMETRY_EMBEDDED_PORT.md`](../docs/TELEMETRY_EMBEDDED_PORT.md)), so no STM32 driver, scheduler hook or flash code is written here. Inference stays at the pit; the recorder only keeps, selects and sends records.

## 1. What exists today and what this adds

| | Today [F] | Proposed here [P] |
|---|---|---|
| Records | every received CAN frame and every sensor sample goes to the STLG log, stamped on receipt in the unit's clock (`host/telematics/node.py`) | the same records also enter fixed-capacity rings, one per channel |
| Uplink | a 2 Hz JSON summary; a 30-message backlog during outages | unchanged, plus responses to requests, sent in the uplink's spare capacity |
| Pit to vehicle | **no request path exists** ([`PROTOCOL.md`](PROTOCOL.md) section 3) | a 32-byte request message (below); the transport (for example an MQTT topic the unit subscribes to) is a design decision still to be made |
| Controller | unchanged | unchanged: the recorder never sends to the controller and never touches the CAN bus |

## 2. Interface (version 1.0)

`bea_on_record(channel, type, t_us, body, len)` is called from the unit's logging path for each record. `bea_on_request(msg, len, now_us)` validates a request and accepts or refuses it. `bea_poll(now_us, out, cap)` returns at most one response chunk. All three are bounded: `bea_on_record` is O(1); `bea_on_request` is O(log capacity) per channel; `bea_poll` writes at most `max_chunk_bytes`. Nothing allocates memory: the caller supplies every ring.

**Request** (32 bytes, little-endian): `"BQ"`, major and minor version, request id, kind, decimation, channel mask, window start, window end (buffer) or duration in milliseconds (capture), deadline, reserved word, CRC-32 (zlib) of the first 28 bytes. Kinds:

| Kind | Meaning |
|---|---|
| buffer | records already held whose stamps lie in [t0, t1]; t1 is cut to the request's arrival, so no record from after the request is ever sent |
| capture | records of the next `duration` milliseconds, sent once the window has passed |
| status | the counters (section 3) and nothing else |

**Response chunk**: `"BR"`, version, request id, status, chunk number, flags (bit 0: last chunk), record count, first and last stamp, payload length, then records in the STLG record format (type, body length, 32-bit stamp, body), then a CRC-32 of the whole chunk. Record bodies are the STLG bodies unchanged, so the pit decodes them with the existing log reader.

**Refusals and statuses**: duplicate id (one of the last 16), expired deadline, busy (4 requests already active), wrong major version (a minor version is accepted), bad CRC, malformed (length, kind, empty or unknown channel mask, empty window, zero decimation), capture too long for the ring. A response is complete, partial (the start of the window had already been overwritten) or empty. A request that reaches its deadline is reported as expired and its records are released.

**Protection of owed records**: an accepted request pins the records it still owes. A new record that would overwrite a pinned one is dropped and counted (`dropped_pinned`), so a slow uplink cannot make a response inconsistent. Pins move forward as chunks are sent and are released when the request completes or expires. A capture longer than a ring can hold is refused rather than truncated.

**Rate limit**: a token bucket (`rate_bytes_per_s`, `burst_bytes`) bounds the response bytes. A chunk never exceeds the tokens held, and a chunk that cannot hold one record is deferred without consuming anything (`rate_deferred`).

**Clock**: 32-bit microseconds of the unit's clock, compared modulo 2^32, so a window may span the wrap (every 71.6 minutes). Records carry the receipt stamp. The pit maps it to UTC with the existing PPS mapping; the recorder does not.

## 3. Counters

`records_in`, `overwritten`, `dropped_pinned`, `dropped_bad_channel`, `requests_accepted`, the refusal counts by reason, `abandoned_expired`, `chunks_sent`, `bytes_sent` and `rate_deferred`. The status request returns all of them. They are the recorder's part of the "clock and receipt-path metadata" action: the pit can tell a lost record from one never recorded.

## 4. Tests and measurements

`tests/research/test_recorder_c.py` builds [`recorder/tests/test_bea_recorder.c`](recorder/tests/test_bea_recorder.c) with AddressSanitizer and UndefinedBehaviorSanitizer and runs it (72 checks). The checks cover:

- ring overwrite and counters;
- buffer windows, including partial ones;
- no record from after the request;
- decimation;
- a capture that waits for its window and is protected;
- pinned records;
- every refusal;
- the rate limit without loss;
- expiry with release;
- a window across the clock wrap;
- the status counters.

The same file is compiled for the Cortex-M4F (`-Os`): 2.3 kB of code; the recorder state is 848 bytes plus the rings.

**Timing [M], host only.** On the computer that ran the tests, the measured maximum was:

- `bea_on_record`: 12 to 35 µs, the larger figure at the first calls (page faults);
- `bea_poll` with a 512-byte chunk: about 7 µs.

These are measured maxima on a host under a sanitizer, **not worst-case execution times**, and say nothing about the STM32U575. The target measurement is in [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md) section 4.

## 5. Sizing (assumptions, not measured)

At the record rates of the host model, the channels the schedulers request write about 4.4 kB/s:

- controller motion and current frames at 100 Hz;
- the command trace at 50 Hz;
- wheel windows at 10 Hz.

A 60 s depth for those channels is about 260 kB of slots. That is beyond the internal SRAM of a small MCU and must come from the external flash log the telemetry proposal already has (8 MB). The rings shown here are the RAM index of recent records; reading older windows from the flash log is the obvious next step and is not implemented. The pit-side simulation charges the flash read time (`research/bea/harness.py`, `FLASH_READ_Bps`) as an assumption.
