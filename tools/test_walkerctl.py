import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import walkerctl as w


def test_cobs_known_vectors():
    # Standard COBS examples
    assert w.cobs_encode(b"\x00") == b"\x01\x01"
    assert w.cobs_encode(b"\x11\x22\x00\x33") == b"\x03\x11\x22\x02\x33"
    assert w.cobs_encode(b"\x11\x22\x33\x44") == b"\x05\x11\x22\x33\x44"
    assert w.cobs_encode(b"") == b"\x01"


def test_cobs_roundtrip():
    import random
    rnd = random.Random(1)
    cases = [b"", b"\x00", b"\x00\x00", bytes(range(256)), b"\x01" * 254,
             b"\x01" * 255, b"\x01" * 300, b"\x00" * 300]
    for _ in range(200):
        cases.append(bytes(rnd.choice([0, 1, 255, rnd.randrange(256)])
                           for _ in range(rnd.randrange(0, 400))))
    for c in cases:
        enc = w.cobs_encode(c)
        assert 0 not in enc
        assert w.cobs_decode(enc) == c


def test_cobs_decode_rejects_bad():
    for bad in (b"\x00", b"\x05\x01"):
        try:
            w.cobs_decode(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_frame_encode():
    f = w.frame_encode(w.T_IDENTIFY)
    assert f.endswith(b"\x00") and w.cobs_decode(f[:-1]) == b"\x02"


def test_xor():
    assert w.xor_bytes(b"\xfc") == b"\x56"  # beacon on the wire is 0x56
    assert w.xor_bytes(w.xor_bytes(b"hello")) == b"hello"


def test_checksum_derived_vector():
    # No packet examples exist in the notes, so this vector is derived by hand
    # from the GBATEK algorithm: ping 0x24, extra 0x01, zero checksum, sid 0.
    # sum = 2 + 0x24*0x100 + 0x01 = 0x2403 -> stored LE as 03 24.
    pkt = bytes([0x24, 0x01, 0, 0, 0, 0, 0, 0])
    assert w.checksum(pkt) == 0x2403
    assert w.checksum(pkt, seed=0) == 0x2401  # Dmitry-style seed
    built = w.build_packet(0x24, 0x01, 0)
    assert built == bytes([0x24, 0x01, 0x03, 0x24, 0, 0, 0, 0])


def test_checksum_fold():
    # Force a carry: many 0xFF bytes overflow 16 bits and must be folded.
    pkt = bytes([0x20, 0x02, 0, 0, 1, 2, 3, 4]) + b"\xff" * 0x68
    ck = w.checksum(pkt)
    assert 0 <= ck <= 0xFFFF
    # independent recomputation
    s = 2 + sum(b << 8 if i % 2 == 0 else b
                for i, b in enumerate(bytes([0x20, 0x02, 0, 0, 1, 2, 3, 4]) + b"\xff" * 0x68))
    s = (s >> 16) + (s & 0xFFFF)
    s = (s >> 16) + s
    assert ck == s & 0xFFFF


def test_build_parse_roundtrip():
    pl = bytes(range(0x68))
    pkt = w.build_packet(0x22, 0x02, 0xDEADBEEF, pl)
    pk = w.parse_packet(pkt)
    assert pk["cmd"] == 0x22 and pk["extra"] == 2
    assert pk["session_id"] == 0xDEADBEEF
    assert pk["checksum_ok"] and pk["payload"] == pl
    bad = bytearray(pkt)
    bad[10] ^= 1
    assert not w.parse_packet(bytes(bad))["checksum_ok"]


def test_parse_beacon_and_short():
    assert w.parse_packet(b"\xfc")["beacon"]
    assert w.parse_packet(b"\x01\x02") is None


def test_session_id():
    assert w.session_from(0x12345678, 0x0F0F0F0F) == 0x12345678 ^ 0x0F0F0F0F


def test_parse_identify():
    info = w.parse_identify(b"MDSW\x01\x03" + b"0.1.0")
    assert info["framed"] and info["raw"] and not info["wifi"]
    assert info["fw_version"] == "0.1.0"
    assert w.parse_identify(b"XXXX\x01\x03") is None


def test_decomp_vectors():
    ds, wk = 0x78563412, 0x01EFCDAB          # wire bytes 12 34 56 78 / ab cd ef 01
    assert w.build_packet(0xFA, 1, ds) == bytes.fromhex("fa01b06212345678")
    assert w.parse_packet(bytes.fromhex("f802d492abcdef01"))["checksum_ok"]
    sid = w.session_from(ds, wk)
    assert sid.to_bytes(4, "little") == bytes.fromhex("b9f9b979")
    assert w.build_packet(0x20, 1, sid) == bytes.fromhex("20017693b9f9b979")
    assert w.build_packet(0xF4, 1, sid) == bytes.fromhex("f4017767b9f9b979")
    assert w.build_packet(0x0C, 2, sid, bytes([0xCE, 0x8A, 2])) == \
        bytes.fromhex("0c020250b9f9b979ce8a02")
    assert w.xor_bytes(bytes.fromhex("fa01b06212345678")) == bytes.fromhex("50ab1ac8b89efcd2")
    assert w.checksum(bytes([0xFF, 0xFF, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF]) + b"\xff" * 0x80) == 0x0002


def test_strip_echo():
    class D:
        last_tx = b"\xfa\x01\xb0\x62\x12\x34\x56\x78"
    reply = bytes.fromhex("f802d492abcdef01")
    assert w.strip_echo(D, D.last_tx + reply) == reply
    assert w.strip_echo(D, reply) == reply


def test_parse_identity():
    pl = bytearray(0x68)
    pl[0x0C:0x10] = (0xBEEF1234).to_bytes(4, "little")
    pl[0x5B] = (7 << 3) | 0b011
    pl[0x60:0x64] = (1000).to_bytes(4, "big")
    pl[0x64:0x68] = (123456).to_bytes(4, "big")
    r = w.parse_identity(bytes(pl))
    assert r["tid"] == 0x1234 and r["sid"] == 0xBEEF
    assert r["registered"] and r["has_pokemon"] and not r["generated_pokemon"]
    assert r["rollover_hour"] == 7
    assert r["rtc_seconds"] == 1000 and r["total_steps"] == 123456
    assert w.parse_identity(b"\x00" * 0x67) is None


def test_tx_allowlist():
    sid = 0x01020304
    for cmd in (0xFA, 0x20, 0x24, 0xF4):
        assert w.is_safe_tx(w.build_packet(cmd, 1, sid))
    assert w.is_safe_tx(w.build_packet(0x0C, 2, sid, bytes([0xCE, 0x8A, 2])))
    assert not w.is_safe_tx(w.build_packet(0x0C, 2, sid, bytes([0xCE, 0x8A, 0x81])))
    assert not w.is_safe_tx(w.build_packet(0x0C, 2, sid, bytes([0xCE, 0x8A])))
    assert not w.is_safe_tx(w.build_packet(0x20, 1, sid, b"\x00"))
    for cmd in (0x2A, 0x2C, 0xF0, 0xFE, 0x00, 0x02, 0x06, 0x0A, 0x80, 0x82, 0xF8, 0xFC):
        assert not w.is_safe_tx(w.build_packet(cmd, 1, sid))
    assert not w.is_safe_tx(b"\x20\x01")

    class Ser:
        written = b""
        def write(self, b): Ser.written += b
        def flush(self): pass
    d = w.Dongle(Ser())
    try:
        d.send(w.T_IR_TX, w.xor_bytes(w.build_packet(0x2A, 1, sid)))
    except SystemExit:
        pass
    else:
        raise AssertionError("destructive command was not refused")
    assert Ser.written == b""
    d.send(w.T_IR_TX, w.xor_bytes(w.build_packet(0x24, 1, sid)))
    assert Ser.written


def test_destructive_names_marked():
    for cmd in (0x2A, 0x2C, 0xF0, 0xFE, 0x06, 0x32):
        assert "DESTRUCTIVE" in w.cmd_name(cmd)
    for cmd in (0x00, 0x02, 0x0A, 0x80, 0x82):
        assert "DESTRUCTIVE" in w.cmd_name(cmd)
