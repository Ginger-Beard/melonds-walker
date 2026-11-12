#!/usr/bin/env python3
"""walkerctl: host bench tool for the melonDS-walker IR dongle.

Speaks the host <-> dongle USB serial protocol in docs/protocol.md (COBS
frames) and the Pokewalker IR packet protocol in
docs/research/notes/ir_hardware_and_protocol.md.

This tool never writes to the walker: it does NOT implement EEPROM or memory
write commands, and a hard-coded allowlist in the send path refuses to
transmit anything except 0xFA, 0x20, 0x24, 0xF4 (and 0x0C with exactly 3
payload bytes). Note that 0x20 makes the walker flush its own save and watts
to its EEPROM before replying (its own state, benign, but it costs write
cycles).

TODO: add a read-only `dump` subcommand (loop 0x0C reads over the 64 KB
EEPROM, compare against a Stage 0 golden dump). Cap len at 0x80, send exactly
3 payload bytes (addrHi, addrLo, len), use extra 0x02 like the game, and send
each read within 97 ms of the previous reply (the walker drops the session
after 97.7 ms of idle).
"""
import argparse
import json
import os
import random
import statistics
import struct
import sys
import time

# ---------------------------------------------------------------- constants

MAGIC = b"MDSW"
XOR_KEY = 0xAA
HEADER_LEN = 8
MAX_PAYLOAD = 0x80

# Host -> dongle
T_IR_TX, T_IDENTIFY, T_SET_CONFIG, T_RAW_MODE, T_PING = 0x01, 0x02, 0x03, 0x04, 0x05
# Dongle -> host
T_IR_RX, T_IDENTIFY_RESP, T_CONFIG_ACK, T_TX_DONE, T_PONG = 0x81, 0x82, 0x83, 0x84, 0x85
T_LOG, T_ERROR = 0x8E, 0x8F

CONFIG_KEYS = {"gap": 0x01, "echo": 0x02, "enable": 0x03}
CONFIG_U16 = {"gap", "echo"}

ERROR_NAMES = {
    0x01: "malformed frame",
    0x02: "unknown type",
    0x03: "IR RX overflow or truncation",
    0x04: "IR TX too long",
    0x05: "bad config key",
    0x06: "IR TX queue full (packet dropped)",
}

CONFIG_STATUS_NAMES = {
    0: "ok",
    1: "wrong value length for this key",
    2: "value out of range",
}

# Hard safety allowlist: the only commands walkerctl may ever put on the IR
# link. Everything else (0x2A/0x2C wipe the walker, 0xF0, 0xFE, all writes)
# is destructive. Enforced in Dongle.send for every IR_TX frame.
SAFE_TX_CMDS = frozenset({0xFA, 0x20, 0x24, 0xF4})
DUMP_READ_CMD = 0x0C

# Command names from the pw decompilation (protocol.h) and the facts doc.
# [DESTRUCTIVE] commands are never sent by walkerctl (enforced by SAFE_TX_CMDS).
CMD_NAMES = {
    0x00: "compressed page write (addr=extra<<8|0x00) [DESTRUCTIVE]",
    0x80: "compressed page write (addr=extra<<8|0x80) [DESTRUCTIVE]",
    0x02: "raw EEPROM write (addr=extra<<8|0x00) [DESTRUCTIVE]",
    0x82: "raw EEPROM write (addr=extra<<8|0x80) [DESTRUCTIVE]",
    0x04: "EEPROM write ack",
    0x06: "RAM write [DESTRUCTIVE]",
    0x0A: "EEPROM write (addr=extra<<8|pl[0]) [DESTRUCTIVE]",
    0x0C: "EEPROM read (pl: hi, lo, len<=0x80)", 0x0E: "EEPROM read reply",
    0x10: "peer status request", 0x12: "peer status reply",
    0x14: "peer info", 0x16: "peer start", 0x1C: "peer already recorded",
    0x20: "identity/status request", 0x22: "identity/status reply (0x68)",
    0x24: "ping", 0x26: "pong",
    0x2A: "RESET ALL (reply carries device ID) [DESTRUCTIVE]",
    0x2C: "RESET keep steps (reply cmd 0x2A) [DESTRUCTIVE]",
    0x32: "walk start request [DESTRUCTIVE]", 0x34: "walk start accepted",
    0x36: "walk start rejected", 0x38: "walk start commit",
    0x40: "walk end request [DESTRUCTIVE]", 0x42: "walk end accepted",
    0x44: "walk end rejected", 0x4E: "walk end commit", 0x50: "walk end ack",
    0x52: "walk update request [DESTRUCTIVE]", 0x54: "walk update accepted",
    0x56: "walk update rejected", 0x5A: "walk update commit",
    0x60: "gift request [DESTRUCTIVE]", 0x62: "gift accepted", 0x64: "gift rejected",
    0x66: "gift collection commit", 0x68: "gift collection ack",
    0x9C: "event buffer full", 0x9E: "event already received",
    0xA0: "event map check", 0xA2: "event pokemon check",
    0xA4: "event item check", 0xA6: "event course check",
    0xA8: "event stamp0 check", 0xAA: "event stamp1 check",
    0xAC: "event stamp2 check", 0xAE: "event stamp3 check",
    0xB8: "event stamp0", 0xBA: "event stamp1", 0xBC: "event stamp2", 0xBE: "event stamp3",
    0xC8: "event stamp0 ack", 0xCA: "event stamp1 ack",
    0xCC: "event stamp2 ack", 0xCE: "event stamp3 ack",
    0xC0: "event map done", 0xC2: "event pokemon done",
    0xC4: "event item done", 0xC6: "event course done",
    0xD0: "event stamp+map done", 0xD2: "event stamp+pokemon done",
    0xD4: "event stamp+item done", 0xD6: "event stamp+course done",
    0xD8: "event rejected",
    0xF0: "factory setup [DESTRUCTIVE]",
    0xF4: "disconnect",
    0xF8: "connect reply", 0xFA: "connect request", 0xFC: "connection beacon",
    0xFE: "motion threshold setup (no session needed) [DESTRUCTIVE]",
}

# Seed 2 is confirmed by both firmwares (walker PacketChecksum, HGSS
# ov112_021E5900); Dmitry's seed-0 variant is off by 2.
DEFAULT_SEED = 2


# ------------------------------------------------------- pure: COBS / XOR

def cobs_encode(data: bytes) -> bytes:
    """COBS-encode data (no trailing delimiter)."""
    out = bytearray()
    block = bytearray()
    for b in data:
        if b == 0:
            out.append(len(block) + 1)
            out += block
            block.clear()
        else:
            block.append(b)
            if len(block) == 254:
                out.append(255)
                out += block
                block.clear()
    out.append(len(block) + 1)
    out += block
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """Decode COBS data (no trailing delimiter). Raises ValueError if bad."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        code = data[i]
        if code == 0:
            raise ValueError("zero byte inside COBS data")
        i += 1
        end = i + code - 1
        if end > n:
            raise ValueError("COBS block overruns data")
        out += data[i:end]
        i = end
        if code != 255 and i < n:
            out.append(0)
    return bytes(out)


def frame_encode(ftype: int, payload: bytes = b"") -> bytes:
    """Build a wire frame: COBS(type + payload) + 0x00."""
    return cobs_encode(bytes([ftype]) + payload) + b"\x00"


def xor_bytes(data: bytes, key: int = XOR_KEY) -> bytes:
    return bytes(b ^ key for b in data)


# --------------------------------------------------- pure: IR packet layer

def checksum(packet: bytes, seed: int = DEFAULT_SEED) -> int:
    """GBATEK checksum over a decoded (un-XORed) packet.

    The checksum field (bytes 2..3) is treated as zero. Even index bytes are
    the high byte of a 16-bit word, odd index bytes the low byte.
    """
    p = bytearray(packet)
    if len(p) >= 4:
        p[2] = p[3] = 0
    s = seed
    for i, b in enumerate(p):
        s += b * 0x100 if i % 2 == 0 else b
    s = (s >> 16) + (s & 0xFFFF)
    s = (s >> 16) + s
    return s & 0xFFFF


def build_packet(cmd: int, extra: int, session_id: int, payload: bytes = b"",
                 seed: int = DEFAULT_SEED) -> bytes:
    """Build a decoded (un-XORed) packet with a valid checksum."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload longer than 0x80 bytes")
    hdr = bytearray([cmd, extra, 0, 0]) + (session_id & 0xFFFFFFFF).to_bytes(4, "little")
    pkt = bytes(hdr) + payload
    ck = checksum(pkt, seed)
    return pkt[:2] + ck.to_bytes(2, "little") + pkt[4:]


def parse_packet(packet: bytes, seed: int = DEFAULT_SEED):
    """Parse a decoded packet into a dict, or None if shorter than a header.

    A single 0xFC byte is the beacon and has no header.
    """
    if len(packet) == 1 and packet[0] == 0xFC:
        return {"cmd": 0xFC, "beacon": True}
    if len(packet) < HEADER_LEN:
        return None
    ck = int.from_bytes(packet[2:4], "little")
    return {
        "cmd": packet[0],
        "extra": packet[1],
        "checksum": ck,
        "checksum_ok": ck == checksum(packet, seed),
        "session_id": int.from_bytes(packet[4:8], "little"),
        "payload": packet[HEADER_LEN:],
    }


def cmd_name(cmd: int) -> str:
    return CMD_NAMES.get(cmd, "unknown")


def session_from(request_id: int, reply_id: int) -> int:
    return (request_id ^ reply_id) & 0xFFFFFFFF


def is_safe_tx(pkt: bytes) -> bool:
    """Allowlist check on a plain (un-XORed) packet about to be transmitted."""
    if len(pkt) < HEADER_LEN:
        return False
    cmd = pkt[0]
    if cmd in SAFE_TX_CMDS:
        return len(pkt) == HEADER_LEN
    if cmd == DUMP_READ_CMD:
        return len(pkt) == HEADER_LEN + 3 and pkt[HEADER_LEN + 2] <= MAX_PAYLOAD
    return False


def strip_echo(d, dec: bytes) -> bytes:
    """Host-side safety net: drop a leading copy of our own last TX packet."""
    tx = getattr(d, "last_tx", b"")
    if tx and dec.startswith(tx):
        return dec[len(tx):]
    return dec


def parse_identity(pl: bytes):
    """Decode the 0x68-byte 0x22 identity/status payload (DeviceStatus)."""
    if len(pl) < 0x68:
        return None
    compat, mon_compat, ver, mon_ver, ot = struct.unpack_from("<IIHHI", pl, 0)
    f = pl[0x5B]
    return {
        "console_compat": compat, "pokemon_compat": mon_compat,
        "game_version": ver, "pokemon_game_version": mon_ver,
        "tid": ot & 0xFFFF, "sid": ot >> 16,          # TID/SID split = Gen4 convention
        "device_id": pl[0x10:0x38].hex(),
        "received_events": pl[0x38:0x48].hex(),
        "trainer_name_u16": list(struct.unpack_from("<8H", pl, 0x48)),  # Gen4 charset
        "receipt_index": pl[0x5A],
        "registered": bool(f & 1), "has_pokemon": bool(f & 2),
        "generated_pokemon": bool(f & 4), "rollover_hour": f >> 3,
        "peer_protocol": pl[0x5C], "console_protocol_level": pl[0x5D],
        "fw_compat": pl[0x5E], "fw_revision": pl[0x5F],
        "rtc_seconds": int.from_bytes(pl[0x60:0x64], "big"),
        "total_steps": int.from_bytes(pl[0x64:0x68], "big"),
    }


# --------------------------------------------------------- serial wrapper

class Dongle:
    """Framed-mode connection to the dongle."""

    def __init__(self, ser):
        self.ser = ser
        self.buf = bytearray()
        self.pending_ir = []      # IR_RX payloads seen while waiting for other frames
        self.last_tx = b""        # last plain packet we sent (for echo stripping)

    def send(self, ftype: int, payload: bytes = b""):
        if ftype == T_IR_TX and not is_safe_tx(xor_bytes(payload)):
            raise SystemExit(
                "refusing to transmit: command 0x%02x is not in the safe set "
                "(0xFA, 0x20, 0x24, 0xF4, 0x0C x3)" % (xor_bytes(payload)[0] if payload else 0))
        self.ser.write(frame_encode(ftype, payload))
        self.ser.flush()

    def recv(self, timeout: float):
        """Return (type, payload) or None on timeout. Skips malformed frames."""
        deadline = time.monotonic() + timeout
        while True:
            while True:
                idx = self.buf.find(b"\x00")
                if idx < 0:
                    break
                raw = bytes(self.buf[:idx])
                del self.buf[:idx + 1]
                if not raw:
                    continue
                try:
                    dec = cobs_decode(raw)
                except ValueError:
                    continue
                if dec:
                    return dec[0], dec[1:]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            # read(1) returns as soon as one byte arrives; read(256) would block
            # for the whole timeout unless 256 bytes came in, adding ~100 ms to
            # every reply and blowing the walker's ~98 ms session timeout.
            self.ser.timeout = min(remaining, 0.1)
            chunk = self.ser.read(1)
            if chunk:
                chunk += self.ser.read(self.ser.in_waiting)
                self.buf += chunk

    def request(self, ftype, payload, want, timeout=1.0):
        """Send and wait for a frame of type `want`; other frames are passed
        to self.on_other (if set). Returns payload or None."""
        self.send(ftype, payload)
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            fr = self.recv(left)
            if fr is None:
                return None
            if fr[0] == want:
                return fr[1]
            handler = getattr(self, "on_other", None)
            if handler:
                handler(*fr)


def parse_identify(payload: bytes):
    if len(payload) < 6 or payload[:4] != MAGIC:
        return None
    return {
        "proto_version": payload[4],
        "caps": payload[5],
        "framed": bool(payload[5] & 1),
        "raw": bool(payload[5] & 2),
        "wifi": bool(payload[5] & 4),
        "fw_version": payload[6:].decode("ascii", "replace"),
    }


def open_serial(port, baud=115200):
    import serial  # imported lazily so the pure functions need no pyserial
    # Dropping DTR does not leave raw mode on the dongle (only USB\n    # re-enumeration or reset does), so DTR handling is not critical here.
    return serial.Serial(port, baud, timeout=0.1)


def probe(port):
    """Return (Dongle, info) if port answers IDENTIFY with MDSW, else None."""
    try:
        ser = open_serial(port)
    except Exception:
        return None
    d = Dongle(ser)
    try:
        time.sleep(0.05)
        ser.reset_input_buffer()
        ser.write(b"\x00")  # empty frame: dongle ignores it, resyncs framing
        ser.flush()
        resp = d.request(T_IDENTIFY, b"", T_IDENTIFY_RESP, timeout=0.5)
        info = parse_identify(resp) if resp is not None else None
        if info:
            return d, info
    except Exception:
        pass
    ser.close()
    return None


def connect(port):
    from serial.tools import list_ports
    if port:
        r = probe(port)
        if not r:
            die(f"{port}: no MDSW IDENTIFY_RESP (wrong port, or dongle in raw mode? "
                f"replug or reset it to return to framed mode)")
        return r
    cands = sorted(list_ports.comports(),
                   key=lambda p: (p.vid != 0x303A, p.device))
    for p in cands:
        r = probe(p.device)
        if r:
            print(f"# auto-detected dongle on {p.device}", file=sys.stderr)
            return r
    die("no dongle found; pass --port (candidates tried: "
        + ", ".join(p.device for p in cands) + ")")


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def hexs(b: bytes) -> str:
    return b.hex(" ")


# ------------------------------------------------------------ subcommands

def cmd_identify(args, d, info):
    print(f"magic        : MDSW")
    print(f"proto version: {info['proto_version']}")
    print(f"caps         : 0x{info['caps']:02x} (framed={info['framed']} "
          f"raw={info['raw']} wifi={info['wifi']})")
    print(f"firmware     : {info['fw_version']}")


def cmd_ping(args, d, info):
    rtts = []
    lost = 0
    for i in range(args.n):
        pl = i.to_bytes(4, "little") + os.urandom(4)
        t0 = time.perf_counter()
        resp = d.request(T_PING, pl, T_PONG, timeout=1.0)
        dt = (time.perf_counter() - t0) * 1000
        if resp == pl:
            rtts.append(dt)
        else:
            lost += 1
    if not rtts:
        die("no PONG replies")
    rtts.sort()
    p95 = rtts[min(len(rtts) - 1, int(round(0.95 * (len(rtts) - 1))))]
    print(f"{len(rtts)}/{args.n} replies ({lost} lost/mismatched)")
    print(f"rtt ms: min {rtts[0]:.3f}  avg {statistics.mean(rtts):.3f}  "
          f"max {rtts[-1]:.3f}  p95 {p95:.3f}")


def describe_packet(raw: bytes, seed):
    dec = xor_bytes(raw)
    pk = parse_packet(dec, seed)
    if pk is None:
        return dec, None, f"short/unparsed ({len(raw)} bytes)"
    if pk.get("beacon"):
        return dec, pk, "0xFC connection beacon"
    return dec, pk, (f"cmd 0x{pk['cmd']:02x} ({cmd_name(pk['cmd'])}) "
                     f"extra 0x{pk['extra']:02x} sid 0x{pk['session_id']:08x} "
                     f"len {len(pk['payload'])} checksum "
                     f"{'ok' if pk['checksum_ok'] else 'BAD'} (0x{pk['checksum']:04x})")


def cmd_sniff(args, d, info):
    logf = open(args.log, "a") if args.log else None
    prev = None
    print("# sniffing, Ctrl-C to stop", file=sys.stderr)
    try:
        while True:
            fr = d.recv(0.5)
            if fr is None:
                continue
            t, pl = fr
            wall = time.time()
            if t == T_IR_RX and len(pl) >= 4:
                ts = int.from_bytes(pl[:4], "little")
                raw = pl[4:]
                delta = None if prev is None else (ts - prev) & 0xFFFFFFFF
                prev = ts
                dec, pk, desc = describe_packet(raw, args.seed)
                dstr = "-" if delta is None else f"+{delta}us"
                print(f"RX  t={ts}us {dstr}\n    raw {hexs(raw)}\n    dec {hexs(dec)}\n    {desc}")
                rec = {"type": "ir_rx", "wall": wall, "ts_us": ts, "delta_us": delta,
                       "raw": raw.hex(), "decoded": dec.hex()}
                if pk and not pk.get("beacon"):
                    rec.update(cmd=pk["cmd"], extra=pk["extra"], session_id=pk["session_id"],
                               checksum=pk["checksum"], checksum_ok=pk["checksum_ok"])
                elif pk:
                    rec.update(cmd=0xFC, beacon=True)
            elif t == T_TX_DONE and len(pl) >= 4:
                ts = int.from_bytes(pl[:4], "little")
                print(f"TX_DONE t={ts}us")
                rec = {"type": "tx_done", "wall": wall, "ts_us": ts}
            elif t == T_LOG:
                txt = pl.decode("ascii", "replace")
                print(f"LOG {txt}")
                rec = {"type": "log", "wall": wall, "text": txt}
            elif t == T_ERROR and pl:
                txt = pl[1:].decode("ascii", "replace")
                print(f"ERROR 0x{pl[0]:02x} ({ERROR_NAMES.get(pl[0], 'unknown')}) {txt}")
                rec = {"type": "error", "wall": wall, "code": pl[0], "text": txt}
            else:
                print(f"?? type 0x{t:02x} payload {hexs(pl)}")
                rec = {"type": "unknown", "wall": wall, "frame_type": t, "payload": pl.hex()}
            sys.stdout.flush()
            if logf:
                logf.write(json.dumps(rec) + "\n")
                logf.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if logf:
            logf.close()


def wait_ir(d, timeout, match):
    """Wait for an IR_RX whose decoded packet satisfies match(raw_dec, pk).
    Returns (dec, pk) or None. Prints LOG/ERROR frames on the way. Frames
    queued by send_ir while it waited for TX_DONE are consumed first."""
    deadline = time.monotonic() + timeout
    while True:
        if d.pending_ir:
            fr = (T_IR_RX, d.pending_ir.pop(0))
        else:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            fr = d.recv(left)
            if fr is None:
                return None
        t, pl = fr
        if t == T_IR_RX and len(pl) >= 4:
            dec = strip_echo(d, xor_bytes(pl[4:]))
            if not dec:
                continue
            pk = parse_packet(dec, d.seed)
            if pk and match(dec, pk):
                return dec, pk
            print(f"  (ignored RX: {hexs(dec)})")
        elif t == T_LOG:
            print(f"  LOG {pl.decode('ascii', 'replace')}")
        elif t == T_ERROR and pl:
            print(f"  ERROR 0x{pl[0]:02x} ({ERROR_NAMES.get(pl[0], 'unknown')}) "
                  f"{pl[1:].decode('ascii', 'replace')}")


def send_ir(d, pkt: bytes, timeout=1.0):
    d.last_tx = pkt
    d.send(T_IR_TX, xor_bytes(pkt))
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        fr = d.recv(left) if left > 0 else None
        if fr is None:
            die("no TX_DONE from dongle")
        t, pl = fr
        if t == T_TX_DONE:
            return
        if t == T_IR_RX:
            d.pending_ir.append(pl)       # keep it; it may be the walker's reply
        elif t == T_LOG:
            print(f"  LOG {pl.decode('ascii', 'replace')}")
        elif t == T_ERROR and pl:
            print(f"  ERROR 0x{pl[0]:02x} ({ERROR_NAMES.get(pl[0], 'unknown')}) "
                  f"{pl[1:].decode('ascii', 'replace')}")


def cmd_handshake(args, d, info):
    d.seed = args.seed
    print(f"waiting up to {args.beacon_timeout:.0f}s for walker beacon 0xFC. Start this first, "
          f"then pick Connect on the walker (it beacons for only ~2.5 s)")
    my_id = random.getrandbits(32)
    fa = build_packet(0xFA, 0x01, my_id, seed=args.seed)
    deadline = time.monotonic() + args.beacon_timeout
    sent = 0
    while True:
        r = wait_ir(d, deadline - time.monotonic(),
                    lambda dec, pk: pk.get("beacon") or pk["cmd"] == 0xF8)
        if not r:
            die("timeout: no 0xF8 connect reply" if sent else
                "timeout: no 0xFC beacon seen. Check wiring/aiming with `sniff` "
                "(expect a 0x56 byte every ~100-140 ms for ~2.5 s)")
        dec, pk = r
        if pk.get("beacon"):
            send_ir(d, fa)
            sent += 1
            print(f"beacon -> sent 0xFA #{sent}, random id {fa[4:8].hex(' ')}")
            continue
        break
    if not pk["checksum_ok"] or pk["extra"] != 0x02:
        die(f"bad 0xF8 (checksum/extra): {hexs(dec)}")
    sid = session_from(my_id, pk["session_id"])
    print(f"got 0xF8, walker id {dec[4:8].hex(' ')}; session id = "
          f"{sid.to_bytes(4, 'little').hex(' ')}")

    disconnected = False
    try:
        send_ir(d, build_packet(0x20, 0x01, sid, seed=args.seed))
        r = wait_ir(d, args.timeout, lambda dec, pk: pk["cmd"] == 0x22)
        if not r:
            die("timeout: no 0x22 identity reply")
        dec, pk = r
        # Disconnect immediately: the walker gives up 97.7 ms after its reply.
        send_ir(d, build_packet(0xF4, 0x01, sid, seed=args.seed))
        disconnected = True
        print("sent 0x20 identity request, got reply; sent 0xF4 disconnect")
        print(f"reply cmd 0x{pk['cmd']:02x} ({cmd_name(pk['cmd'])}) "
              f"sid {dec[4:8].hex(' ')} "
              f"checksum {'ok' if pk['checksum_ok'] else 'BAD'}")
        if pk["session_id"] != sid:
            print("  WARNING: session id in reply differs from expected")
        pl = pk["payload"]
        print(f"payload ({len(pl)} bytes, expected 0x68):")
        for i in range(0, len(pl), 16):
            print(f"  {i:04x}: {hexs(pl[i:i+16])}")
        ident = parse_identity(pl)
        if ident:
            for k, v in ident.items():
                print(f"  {k}: {v}")
    finally:
        if not disconnected:
            try:
                send_ir(d, build_packet(0xF4, 0x01, sid, seed=args.seed))
                print("sent 0xF4 disconnect")
            except SystemExit:
                pass


def cmd_config(args, d, info):
    key = CONFIG_KEYS[args.key]
    try:
        val = int(args.value, 0)
    except ValueError:
        die(f"bad value {args.value!r}")
    if args.key in CONFIG_U16:
        if not 0 <= val <= 0xFFFF:
            die("value must fit u16")
        vb = val.to_bytes(2, "little")
    else:
        if val not in (0, 1):
            die("enable must be 0 or 1")
        vb = bytes([val])
    resp = d.request(T_SET_CONFIG, bytes([key]) + vb, T_CONFIG_ACK)
    if resp is None or len(resp) < 2:
        die("no CONFIG_ACK")
    if resp[1] != 0:
        die(f"CONFIG_ACK key 0x{resp[0]:02x} status {resp[1]} "
            f"({CONFIG_STATUS_NAMES.get(resp[1], 'unknown')})")
    print(f"ok: {args.key} = {val}")


def cmd_raw(args, d, info):
    resp = d.request(T_RAW_MODE, b"", T_CONFIG_ACK)
    if resp is None or len(resp) < 2 or resp[1] != 0:
        die("RAW_MODE not acknowledged")
    print("dongle is now in raw mode. Closing the port or dropping DTR does NOT "
          "leave raw mode; unplug/replug the dongle (USB re-enumeration) or reset it "
          "to return to framed mode")


# ------------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(description="melonDS-walker dongle bench tool")
    ap.add_argument("--port", help="serial port (default: auto-detect via IDENTIFY)")
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=DEFAULT_SEED,
                    help="checksum start value; debug knob only. 2 is confirmed correct (Dmitry's 0 is off by 2). default 2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("identify", help="print firmware info").set_defaults(fn=cmd_identify)
    p = sub.add_parser("ping", help="round-trip latency")
    p.add_argument("-n", type=int, default=20)
    p.set_defaults(fn=cmd_ping)
    p = sub.add_parser("sniff", help="print IR traffic")
    p.add_argument("--log", metavar="FILE.jsonl")
    p.set_defaults(fn=cmd_sniff)
    p = sub.add_parser("handshake", help="act as the DS side: connect, read identity, disconnect")
    p.add_argument("--beacon-timeout", type=float, default=15.0)
    p.add_argument("--timeout", type=float, default=0.3, help="reply timeout (s); the walker drops the session after 97.7 ms idle")
    p.set_defaults(fn=cmd_handshake)
    p = sub.add_parser("config", help="set dongle config")
    p.add_argument("key", choices=sorted(CONFIG_KEYS))
    p.add_argument("value")
    p.set_defaults(fn=cmd_config)
    sub.add_parser("raw", help="switch dongle to raw mode").set_defaults(fn=cmd_raw)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    d, info = connect(args.port)
    d.seed = args.seed
    d.on_other = lambda t, pl: None
    try:
        args.fn(args, d, info)
    finally:
        d.ser.close()


if __name__ == "__main__":
    main()
