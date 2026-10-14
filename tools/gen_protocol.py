#!/usr/bin/env python3
"""Generate C/Python CAN codecs and golden vectors from protocol/protocol.yaml.

    python3 tools/gen_protocol.py           # (re)generate
    python3 tools/gen_protocol.py --check   # exit 1 if generated files are stale

Outputs:
    protocol/generated/semmc_protocol.h / .c     C codec (no allocation, no I/O)
    protocol/generated/semmc_protocol.py         Python codec (same arithmetic)
    protocol/generated/semmc_golden_vectors.c    C self-check against the vectors
    protocol/golden_vectors/vectors.json         expected bytes per vector

Arithmetic contract (identical in both languages so bytes match exactly):
    x      = f32(physical)                       # C fields are float
    x      = clamp(x, min, max)                  # in double; saturation flagged
    raw    = round_half_away((x - offset) / scale)   in double
    raw    = clamp(raw, raw_lo, raw_hi)          # raw range excludes the sentinel
    decode = f32(raw * scale + offset)           # in double, then to float
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "protocol" / "protocol.yaml"
GEN = ROOT / "protocol" / "generated"
VEC = ROOT / "protocol" / "golden_vectors" / "vectors.json"

ID_LO, ID_HI = 0x300, 0x33F


# --------------------------------------------------------------------------- spec
def load_spec(path=SPEC) -> dict:
    spec = yaml.safe_load(path.read_text())
    major = spec["protocol"]["major"]
    seen_ids, seen_names = set(), set()
    for m in spec["messages"]:
        if m["name"] in seen_names or m["id"] in seen_ids:
            raise ValueError(f"duplicate message {m['name']} / {m['id']:#x}")
        seen_names.add(m["name"])
        seen_ids.add(m["id"])
        if not ID_LO <= m["id"] <= ID_HI:
            raise ValueError(f"{m['name']}: id {m['id']:#x} outside {ID_LO:#x}-{ID_HI:#x}")
        m["data_id"] = ((major & 0x1F) << 11) | m["id"]
        used = [False] * 64
        for k in range(16):
            used[k] = True  # crc + seq
        fnames = set()
        for f in m["fields"]:
            if f["name"] in fnames or f["name"] in ("seq", "crc"):
                raise ValueError(f"{m['name']}.{f['name']}: duplicate/reserved name")
            fnames.add(f["name"])
            s, w = f["start"], f["width"]
            if not (16 <= s and s + w <= 64 and 1 <= w <= 32):
                raise ValueError(f"{m['name']}.{f['name']}: bits {s}+{w} out of payload")
            for b in range(s, s + w):
                if used[b]:
                    raise ValueError(f"{m['name']}.{f['name']}: bit {b} overlaps")
                used[b] = True
            f.setdefault("signed", False)
            f.setdefault("invalid", None)
            if f["kind"] == "bool" and w != 1:
                raise ValueError(f"{m['name']}.{f['name']}: bool must be 1 bit")
            if f["kind"] == "scaled":
                lo, hi = raw_limits(f)
                f["raw_lo"], f["raw_hi"] = lo, hi
                rmin = round_half_away((f["min"] - f["offset"]) / f["scale"])
                rmax = round_half_away((f["max"] - f["offset"]) / f["scale"])
                if rmin < lo or rmax > hi:
                    raise ValueError(f"{m['name']}.{f['name']}: [min,max] not representable in raw {lo}..{hi}")
            else:
                f["raw_lo"], f["raw_hi"] = 0, (1 << w) - 1
    return spec


def raw_limits(f) -> tuple[int, int]:
    w = f["width"]
    lo, hi = (-(1 << (w - 1)), (1 << (w - 1)) - 1) if f["signed"] else (0, (1 << w) - 1)
    inv = f.get("invalid")
    if inv is not None:
        if inv == lo:
            lo += 1
        elif inv == hi:
            hi -= 1
        else:
            raise ValueError(f"{f['name']}: invalid sentinel must be the raw min or max")
    return lo, hi


def round_half_away(x: float) -> int:
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def spec_hash(spec_text: str) -> str:
    return hashlib.sha256(spec_text.encode()).hexdigest()[:16]


# ------------------------------------------------------------- reference codec
def crc8_j1850(data: bytes, crc: int = 0xFF) -> int:
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc8_with_data_id(data_id: int, payload: bytes) -> int:
    return crc8_j1850(bytes([data_id & 0xFF, data_id >> 8]) + payload) ^ 0xFF


def to_f32(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return x
    if abs(x) > 3.4028234663852886e38:
        return math.copysign(math.inf, x)
    return struct.unpack("<f", struct.pack("<f", x))[0]


# The Python codec body is shared verbatim between this generator (to compute
# golden vectors) and the generated module, so there is one implementation.
PY_CODEC_BODY = r'''
class CodecError(ValueError):
    pass


def _crc8(data, crc=0xFF):
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc8_with_data_id(data_id, payload):
    return _crc8(bytes([data_id & 0xFF, data_id >> 8]) + bytes(payload)) ^ 0xFF


def _f32(x):
    if math.isnan(x) or math.isinf(x):
        return x
    if abs(x) > 3.4028234663852886e38:
        return math.copysign(math.inf, x)
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _round_half_away(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _put(buf, start, width, raw):
    raw &= (1 << width) - 1
    for k in range(width):
        bit = start + k
        if (raw >> k) & 1:
            buf[bit // 8] |= 1 << (bit % 8)


def _get(buf, start, width, signed):
    raw = 0
    for k in range(width):
        bit = start + k
        raw |= ((buf[bit // 8] >> (bit % 8)) & 1) << k
    if signed and raw & (1 << (width - 1)):
        raw -= 1 << width
    return raw


def encode(name, values, seq):
    """Encode physical values. Returns (bytes8, saturated_fields, invalid_fields).

    Raises CodecError for a missing field or a NaN in a field without sentinel."""
    m = MESSAGES[name]
    buf = bytearray(8)
    buf[1] = seq & 0xFF
    sat, inv = [], []
    for f in m["fields"]:
        if f["name"] not in values:
            raise CodecError(f"{name}: missing field {f['name']}")
        v = values[f["name"]]
        if f["kind"] == "bool":
            raw = 1 if v else 0
        elif f["kind"] == "raw":
            raw = int(v)
            if raw < f["raw_lo"] or raw > f["raw_hi"]:
                raw = min(max(raw, f["raw_lo"]), f["raw_hi"])
                sat.append(f["name"])
        else:
            x = _f32(float(v))
            if math.isnan(x):
                if f["invalid"] is None:
                    raise CodecError(f"{name}.{f['name']}: NaN but field has no invalid sentinel")
                raw = f["invalid"]
                inv.append(f["name"])
            else:
                if x < f["min"] or x > f["max"]:
                    x = min(max(x, f["min"]), f["max"])
                    sat.append(f["name"])
                raw = _round_half_away((x - f["offset"]) / f["scale"])
                raw = min(max(raw, f["raw_lo"]), f["raw_hi"])
        _put(buf, f["start"], f["width"], raw)
    buf[0] = crc8_with_data_id(m["data_id"], buf[1:])
    return bytes(buf), sat, inv


def decode(name_or_id, data):
    """Decode 8 bytes. Returns (values_dict, info_dict). info has 'status'
    ('ok' | 'bad_length' | 'bad_crc' | 'unknown_id'), 'seq', 'invalid' (fields
    that carried the sentinel -> NaN) and 'out_of_range' (raw beyond [min,max])."""
    m = MESSAGES.get(name_or_id) if isinstance(name_or_id, str) else BY_ID.get(name_or_id)
    if m is None:
        return {}, {"status": "unknown_id"}
    data = bytes(data)
    if len(data) != 8:
        return {}, {"status": "bad_length"}
    if crc8_with_data_id(m["data_id"], data[1:]) != data[0]:
        return {}, {"status": "bad_crc"}
    out, inv, oor = {}, [], []
    for f in m["fields"]:
        raw = _get(data, f["start"], f["width"], f["signed"])
        if f["kind"] == "bool":
            out[f["name"]] = bool(raw)
        elif f["kind"] == "raw":
            out[f["name"]] = raw
        elif f["invalid"] is not None and raw == f["invalid"]:
            out[f["name"]] = float("nan")
            inv.append(f["name"])
        else:
            x = _f32(raw * f["scale"] + f["offset"])
            if raw < f["raw_lo"] or raw > f["raw_hi"] or x < _f32(f["min"]) or x > _f32(f["max"]):
                oor.append(f["name"])
            out[f["name"]] = x
    return out, {"status": "ok", "seq": data[1], "invalid": inv, "out_of_range": oor}
'''


def build_python(spec, h) -> str:
    msgs = {}
    for m in spec["messages"]:
        msgs[m["name"]] = {
            "id": m["id"], "data_id": m["data_id"], "period_s": m["period_s"],
            "sender": m["sender"],
            "fields": [{k: f[k] for k in ("name", "start", "width", "kind", "signed", "invalid",
                                           "raw_lo", "raw_hi")}
                       | ({k: f[k] for k in ("scale", "offset", "min", "max")} if f["kind"] == "scaled" else {})
                       for f in m["fields"]],
        }
    return (
        f'"""GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit.\n\n'
        f'semmc CAN protocol v{spec["protocol"]["major"]}.{spec["protocol"]["minor"]}, spec hash {h}.\n"""\n'
        "import math\nimport struct\n\n"
        f'PROTOCOL_MAJOR = {spec["protocol"]["major"]}\nPROTOCOL_MINOR = {spec["protocol"]["minor"]}\n'
        f'SPEC_HASH = "{h}"\n\n'
        f"MESSAGES = {json.dumps(msgs, indent=1)}\n"
        .replace(": null", ": None").replace(": true", ": True").replace(": false", ": False")
        + "\nBY_ID = {m['id']: m for m in MESSAGES.values()}\nfor _n, _m in MESSAGES.items():\n    _m['name'] = _n\n"
        + PY_CODEC_BODY
    )


def _load_codec(py_src: str):
    ns: dict = {}
    exec(compile(py_src, "semmc_protocol.py", "exec"), ns)  # noqa: S102 - generated by us
    return ns


# --------------------------------------------------------------------------- C
def c_type(f) -> str:
    if f["kind"] == "scaled":
        return "float"
    if f["kind"] == "bool":
        return "bool"
    return "uint32_t"


def c_double(v) -> str:
    r = repr(float(v))
    return r if ("." in r or "e" in r or "inf" in r) else r + ".0"


def build_c_header(spec, h) -> str:
    P = spec["protocol"]
    L = [
        "/* GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit. */",
        f"/* semmc CAN protocol v{P['major']}.{P['minor']}, spec hash {h} */",
        "#ifndef SEMMC_PROTOCOL_H", "#define SEMMC_PROTOCOL_H", "",
        "#include <stdbool.h>", "#include <stdint.h>", "",
        f"#define SEMMC_PROTO_MAJOR {P['major']}u", f"#define SEMMC_PROTO_MINOR {P['minor']}u",
        f'#define SEMMC_PROTO_SPEC_HASH "{h}"', f"#define SEMMC_NOMINAL_BITRATE {P['nominal_bitrate']}u",
        "#define SEMMC_FRAME_LEN 8u", "",
        "typedef enum { SEMMC_OK = 0, SEMMC_E_LEN = 1, SEMMC_E_CRC = 2, SEMMC_E_NAN = 3 } semmc_status_t;", "",
        "typedef struct {",
        "    semmc_status_t status;",
        "    uint32_t saturated;    /* bit i: field i was clamped */",
        "    uint32_t invalid;      /* bit i: field i carried / was encoded as the sentinel */",
        "    uint32_t out_of_range; /* bit i: decoded raw outside the declared range */",
        "} semmc_result_t;", "",
        "uint8_t semmc_crc8_data_id(uint16_t data_id, const uint8_t *payload7);",
        "/* Returns the message index for a CAN id, or -1. */",
        "int semmc_msg_index(uint32_t can_id);", "",
    ]
    for m in spec["messages"]:
        N = m["name"].upper()
        L.append(f"/* {m['name']} - {m['description'].strip() if isinstance(m['description'], str) else ''} */")
        L += [f"#define SEMMC_ID_{N} 0x{m['id']:03X}u",
              f"#define SEMMC_DATAID_{N} 0x{m['data_id']:04X}u",
              f"#define SEMMC_PERIOD_US_{N} {int(round(m['period_s'] * 1e6))}u"]
        for i, f in enumerate(m["fields"]):
            L.append(f"#define SEMMC_F_{N}_{f['name'].upper()} (1u << {i})")
        L.append("typedef struct {")
        L.append("    uint8_t seq;")
        for f in m["fields"]:
            unit = f" /* {f.get('unit', '')} */" if f["kind"] == "scaled" else ""
            L.append(f"    {c_type(f)} {f['name']};{unit}")
        L.append(f"}} semmc_{m['name']}_t;")
        L.append(f"semmc_result_t semmc_encode_{m['name']}(const semmc_{m['name']}_t *m, uint8_t out[8]);")
        L.append(f"semmc_result_t semmc_decode_{m['name']}(const uint8_t *in, uint8_t len, semmc_{m['name']}_t *m);")
        L.append("")
    L += ["#endif /* SEMMC_PROTOCOL_H */", ""]
    return "\n".join(L)


def build_c_source(spec, h) -> str:
    L = [
        "/* GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit. */",
        f"/* spec hash {h}. Conversion arithmetic is in double (slow-loop only), matching the Python codec. */",
        "#include \"semmc_protocol.h\"", "", "#include <math.h>", "#include <string.h>", "",
        "static uint8_t crc8_upd(uint8_t crc, const uint8_t *d, unsigned n)",
        "{",
        "    for (unsigned i = 0; i < n; i++) {",
        "        crc ^= d[i];",
        "        for (int b = 0; b < 8; b++) {",
        "            const unsigned c = crc;",
        "            crc = (uint8_t)((c & 0x80u) ? ((c << 1) ^ 0x1Du) : (c << 1));",
        "        }",
        "    }",
        "    return crc;",
        "}", "",
        "uint8_t semmc_crc8_data_id(uint16_t data_id, const uint8_t *payload7)",
        "{",
        "    const uint8_t id[2] = {(uint8_t)(data_id & 0xFFu), (uint8_t)(data_id >> 8)};",
        "    return (uint8_t)(crc8_upd(crc8_upd(0xFFu, id, 2u), payload7, 7u) ^ 0xFFu);",
        "}", "",
        "static void put_bits(uint8_t *b, unsigned start, unsigned width, uint32_t raw)",
        "{",
        "    for (unsigned k = 0; k < width; k++) {",
        "        const unsigned bit = start + k;",
        "        if ((raw >> k) & 1u) b[bit / 8u] = (uint8_t)(b[bit / 8u] | (1u << (bit % 8u)));",
        "    }",
        "}", "",
        "static uint32_t get_bits(const uint8_t *b, unsigned start, unsigned width)",
        "{",
        "    uint32_t raw = 0u;",
        "    for (unsigned k = 0; k < width; k++) {",
        "        const unsigned bit = start + k;",
        "        raw |= (uint32_t)((b[bit / 8u] >> (bit % 8u)) & 1u) << k;",
        "    }",
        "    return raw;",
        "}", "",
        "static int64_t sext(uint32_t raw, unsigned width)",
        "{",
        "    if (width < 32u && (raw & (1u << (width - 1u)))) return (int64_t)raw - ((int64_t)1 << width);",
        "    if (width == 32u && (raw & 0x80000000u)) return (int64_t)raw - ((int64_t)1 << 32);",
        "    return (int64_t)raw;",
        "}", "",
        "static int64_t round_half_away(double x)",
        "{",
        "    return x >= 0.0 ? (int64_t)floor(x + 0.5) : -(int64_t)floor(-x + 0.5);",
        "}", "",
        "/* Encode one scaled field. Returns raw bits; flags saturation / sentinel. */",
        "static uint32_t enc_scaled(float v, double mn, double mx, double scale, double offset, int64_t rlo,",
        "                           int64_t rhi, bool has_inv, int64_t inv, unsigned width, uint32_t bit,",
        "                           semmc_result_t *r)",
        "{",
        "    double x = (double)v;",
        "    int64_t raw;",
        "    if (x != x) {",
        "        if (!has_inv) { r->status = SEMMC_E_NAN; return 0u; }",
        "        r->invalid |= bit;",
        "        raw = inv;",
        "    } else {",
        "        if (x < mn || x > mx) { x = x < mn ? mn : mx; r->saturated |= bit; }",
        "        raw = round_half_away((x - offset) / scale);",
        "        if (raw < rlo) raw = rlo;",
        "        if (raw > rhi) raw = rhi;",
        "    }",
        "    const uint64_t mask = (width == 32u) ? 0xFFFFFFFFull : ((1ull << width) - 1ull);",
        "    return (uint32_t)((uint64_t)raw & mask);",
        "}", "",
        "static float dec_scaled(int64_t raw, double mn, double mx, double scale, double offset, int64_t rlo,",
        "                        int64_t rhi, bool has_inv, int64_t inv, uint32_t bit, semmc_result_t *r)",
        "{",
        "    if (has_inv && raw == inv) { r->invalid |= bit; return NAN; }",
        "    const float x = (float)((double)raw * scale + offset);",
        "    if (raw < rlo || raw > rhi || (double)x < (double)(float)mn || (double)x > (double)(float)mx) r->out_of_range |= bit;",
        "    return x;",
        "}", "",
        "static uint32_t enc_raw(uint32_t v, uint32_t hi, uint32_t bit, semmc_result_t *r)",
        "{",
        "    if (v > hi) { r->saturated |= bit; return hi; }",
        "    return v;",
        "}", "",
        "int semmc_msg_index(uint32_t can_id)",
        "{",
        "    switch (can_id) {",
    ]
    for i, m in enumerate(spec["messages"]):
        L.append(f"    case 0x{m['id']:03X}u: return {i};")
    L += ["    default: return -1;", "    }", "}", ""]
    for m in spec["messages"]:
        N, n = m["name"].upper(), m["name"]
        L += [f"semmc_result_t semmc_encode_{n}(const semmc_{n}_t *m, uint8_t out[8])", "{",
              "    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};", "    uint8_t b[8] = {0};",
              "    b[1] = m->seq;"]
        for i, f in enumerate(m["fields"]):
            bit = f"(1u << {i})"
            if f["kind"] == "bool":
                L.append(f"    put_bits(b, {f['start']}u, {f['width']}u, m->{f['name']} ? 1u : 0u);")
            elif f["kind"] == "raw":
                L.append(f"    put_bits(b, {f['start']}u, {f['width']}u, enc_raw(m->{f['name']}, {f['raw_hi']}u, {bit}, &r));")
            else:
                inv = f["invalid"]
                L.append(
                    f"    put_bits(b, {f['start']}u, {f['width']}u, enc_scaled(m->{f['name']}, {c_double(f['min'])}, "
                    f"{c_double(f['max'])}, {c_double(f['scale'])}, {c_double(f['offset'])}, {f['raw_lo']}LL, "
                    f"{f['raw_hi']}LL, {'true' if inv is not None else 'false'}, {inv if inv is not None else 0}LL, "
                    f"{f['width']}u, {bit}, &r));")
        L += ["    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }",
              f"    b[0] = semmc_crc8_data_id(SEMMC_DATAID_{N}, &b[1]);",
              "    memcpy(out, b, 8);", "    return r;", "}", ""]
        L += [f"semmc_result_t semmc_decode_{n}(const uint8_t *in, uint8_t len, semmc_{n}_t *m)", "{",
              "    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};",
              "    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }",
              f"    if (semmc_crc8_data_id(SEMMC_DATAID_{N}, &in[1]) != in[0]) {{ r.status = SEMMC_E_CRC; return r; }}",
              "    m->seq = in[1];"]
        for i, f in enumerate(m["fields"]):
            bit = f"(1u << {i})"
            g = f"get_bits(in, {f['start']}u, {f['width']}u)"
            if f["kind"] == "bool":
                L.append(f"    m->{f['name']} = {g} != 0u;")
            elif f["kind"] == "raw":
                L.append(f"    m->{f['name']} = {g};")
            else:
                inv = f["invalid"]
                rawexpr = f"sext({g}, {f['width']}u)" if f["signed"] else f"(int64_t){g}"
                L.append(
                    f"    m->{f['name']} = dec_scaled({rawexpr}, {c_double(f['min'])}, {c_double(f['max'])}, "
                    f"{c_double(f['scale'])}, {c_double(f['offset'])}, {f['raw_lo']}LL, {f['raw_hi']}LL, "
                    f"{'true' if inv is not None else 'false'}, {inv if inv is not None else 0}LL, {bit}, &r);")
        L += ["    return r;", "}", ""]
    return "\n".join(L)


def c_literal(f, v) -> str:
    if f["kind"] == "bool":
        return "true" if v else "false"
    if f["kind"] == "raw":
        return f"{int(v)}u"
    if isinstance(v, float) and math.isnan(v):
        return "NAN"
    return f"{float(v)!r}f" if "e" not in repr(float(v)) else f"{float(v):.9e}f"


def build_vectors(spec, codec) -> list[dict]:
    out = []
    by_name = {m["name"]: m for m in spec["messages"]}
    for i, v in enumerate(spec["vectors"]):
        m = by_name[v["msg"]]
        data, sat, inv = codec["encode"](v["msg"], v["values"], v["seq"])
        dec, info = codec["decode"](v["msg"], data)
        def js(x):
            return "NaN" if isinstance(x, float) and math.isnan(x) else x
        out.append({
            "index": i, "msg": v["msg"], "id": m["id"], "seq": v["seq"],
            "values": {k: js(x) for k, x in v["values"].items()},
            "bytes": data.hex(), "saturated": sat, "invalid": inv,
            "decoded": {k: js(x) for k, x in dec.items()}, "note": v.get("note", ""),
        })
    return out


def build_c_golden(spec, vectors, h) -> str:
    by_name = {m["name"]: m for m in spec["messages"]}
    L = ["/* GENERATED by tools/gen_protocol.py - do not edit. Golden-vector self-check. */",
         f"/* spec hash {h} */", "#include <math.h>", "#include <stdio.h>", "#include <string.h>", "",
         "#include \"semmc_protocol.h\"", "",
         "int semmc_golden_check(void);", "",
         "static int same_float(float a, float b)",
         "{", "    if (a != a) return b != b;", "    return a == b;", "}", "",
         "int semmc_golden_check(void)", "{", "    int fails = 0;", "    uint8_t buf[8];"]
    for v in vectors:
        m = by_name[v["msg"]]
        n = m["name"]
        exp = ", ".join(f"0x{b:02X}" for b in bytes.fromhex(v["bytes"]))
        init = ", ".join([f".seq = {v['seq']}u"] + [
            f".{f['name']} = {c_literal(f, float('nan') if v['values'][f['name']] == 'NaN' else v['values'][f['name']])}"
            for f in m["fields"]])
        dec = v["decoded"]
        L += ["    {", f"        const semmc_{n}_t in = {{{init}}};", f"        const uint8_t exp[8] = {{{exp}}};",
              f"        semmc_{n}_t out;", f"        semmc_result_t r = semmc_encode_{n}(&in, buf);",
              f"        if (r.status != SEMMC_OK || memcmp(buf, exp, 8) != 0) {{ fails++; printf(\"golden {v['index']} {n}: encode mismatch\\n\"); }}",
              f"        r = semmc_decode_{n}(exp, 8u, &out);",
              f"        if (r.status != SEMMC_OK || out.seq != {v['seq']}u) {{ fails++; printf(\"golden {v['index']} {n}: decode status\\n\"); }}"]
        for f in m["fields"]:
            d = dec[f["name"]]
            if f["kind"] == "scaled":
                lit = "NAN" if d == "NaN" else f"(float){float(d)!r}"
                L.append(f"        if (!same_float(out.{f['name']}, {lit})) {{ fails++; printf(\"golden {v['index']} {n}.{f['name']}: decoded value\\n\"); }}")
            elif f["kind"] == "bool":
                L.append(f"        if (out.{f['name']} != {'true' if d else 'false'}) {{ fails++; printf(\"golden {v['index']} {n}.{f['name']}\\n\"); }}")
            else:
                L.append(f"        if (out.{f['name']} != {int(d)}u) {{ fails++; printf(\"golden {v['index']} {n}.{f['name']}\\n\"); }}")
        L.append("        /* single-bit corruption anywhere must fail the CRC */")
        L.append("        for (int k = 8; k < 64; k++) { uint8_t c[8]; memcpy(c, exp, 8); c[k / 8] ^= (uint8_t)(1u << (k % 8));")
        L.append(f"            if (semmc_decode_{n}(c, 8u, &out).status != SEMMC_E_CRC) {{ fails++; printf(\"golden {v['index']}: bitflip %d not detected\\n\", k); }} }}")
        L.append("    }")
    L += ["    return fails;", "}", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = SPEC.read_text()
    spec = load_spec()
    h = spec_hash(text)
    py = build_python(spec, h)
    codec = _load_codec(py)
    vectors = build_vectors(spec, codec)
    outputs = {
        GEN / "semmc_protocol.h": build_c_header(spec, h),
        GEN / "semmc_protocol.c": build_c_source(spec, h),
        GEN / "semmc_protocol.py": py,
        GEN / "semmc_golden_vectors.c": build_c_golden(spec, vectors, h),
        VEC: json.dumps({"spec_hash": h, "protocol": spec["protocol"], "vectors": vectors}, indent=1) + "\n",
    }
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print(f"wrote {path.relative_to(ROOT)}")
    for p in stale:
        print(f"STALE: {p.relative_to(ROOT)} (run tools/gen_protocol.py)")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
