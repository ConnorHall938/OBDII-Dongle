"""Turning characteristic bytes into something readable, and back again."""

from __future__ import annotations

import struct

# Write formats offered in the explorer, in menu order.
WRITE_FORMATS = (
    "hex",
    "utf-8",
    "u8",
    "u16le",
    "u16be",
    "u32le",
    "u32be",
    "i16le",
    "i32le",
    "f32le",
)


def hexdump(data: bytes) -> str:
    """Space-separated uppercase hex, e.g. `E8 03`."""
    return " ".join(f"{b:02X}" for b in data) if data else "<empty>"


def _ascii(data: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


def interpretations(data: bytes) -> list[tuple[str, str]]:
    """Every decode that fits `data`, as (label, value) pairs.

    Deliberately format-agnostic: rather than hardcoding which characteristic
    holds what, show all the plausible readings and let the eye pick the right
    one (a uint16 LE RPM of 1000 reads `E8 03` -> u16le 1000).

    Ordered most-likely-useful first, so the reading you want is near the top:
    hex, then the width-specific numbers, then text, then the length. A value
    only wide enough to be text has no numeric rows, so text floats up anyway.
    """
    out: list[tuple[str, str]] = [("hex", hexdump(data))]
    if not data:
        return out + [("len", "0 bytes")]

    n = len(data)
    if n == 1:
        out.append(("u8", str(data[0])))
        out.append(("i8", str(struct.unpack("<b", data)[0])))
        out.append(("bits", format(data[0], "08b")))
    if n == 2:
        out.append(("u16le", str(struct.unpack("<H", data)[0])))
        out.append(("u16be", str(struct.unpack(">H", data)[0])))
        out.append(("i16le", str(struct.unpack("<h", data)[0])))
    if n == 4:
        out.append(("u32le", str(struct.unpack("<I", data)[0])))
        out.append(("u32be", str(struct.unpack(">I", data)[0])))
        out.append(("i32le", str(struct.unpack("<i", data)[0])))
        out.append(("f32le", f"{struct.unpack('<f', data)[0]:g}"))
    if n == 8:
        out.append(("u64le", str(struct.unpack("<Q", data)[0])))
        out.append(("f64le", f"{struct.unpack('<d', data)[0]:g}"))

    out.append(("ascii", _ascii(data)))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        if text.isprintable() or text.strip():
            out.append(("utf-8", repr(text)[1:-1]))

    out.append(("len", f"{n} bytes"))
    return out


def decode_as(data: bytes, fmt: str) -> str:
    """Single named decode, for the dashboard's fixed-format readouts."""
    if fmt == "hex":
        return hexdump(data)
    if fmt == "utf-8":
        return data.decode("utf-8", errors="replace")
    if fmt == "ascii":
        return _ascii(data)
    sizes = {"u8": 1, "i8": 1, "u16le": 2, "u16be": 2, "i16le": 2,
             "u32le": 4, "u32be": 4, "i32le": 4, "f32le": 4}
    codes = {"u8": "<B", "i8": "<b", "u16le": "<H", "u16be": ">H", "i16le": "<h",
             "u32le": "<I", "u32be": ">I", "i32le": "<i", "f32le": "<f"}
    if fmt not in sizes:
        raise ValueError(f"unknown format {fmt!r}")
    need = sizes[fmt]
    if len(data) < need:
        raise ValueError(f"{fmt} needs {need} bytes, got {len(data)}")
    return str(struct.unpack(codes[fmt], data[:need])[0])


def decode_int(data: bytes, fmt: str) -> int:
    """Like `decode_as` but guaranteed numeric — used for plotting."""
    return int(float(decode_as(data, fmt)))


def encode(text: str, fmt: str) -> bytes:
    """Parse the write box. Raises ValueError with a message fit for the UI."""
    text = text.strip()
    if fmt == "hex":
        cleaned = text.replace("0x", "").replace(",", " ").replace("-", " ")
        cleaned = "".join(cleaned.split())
        if not cleaned:
            return b""
        if len(cleaned) % 2:
            raise ValueError("hex needs an even number of digits")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError(f"bad hex: {exc}") from exc
    if fmt == "utf-8":
        # Let the usual escapes through so you can send a trailing newline.
        return text.encode("utf-8").decode("unicode_escape").encode("latin-1")

    codes = {"u8": "<B", "u16le": "<H", "u16be": ">H", "u32le": "<I",
             "u32be": ">I", "i16le": "<h", "i32le": "<i", "f32le": "<f"}
    if fmt not in codes:
        raise ValueError(f"unknown format {fmt!r}")
    try:
        value = float(text) if fmt.startswith("f") else int(text, 0)
        return struct.pack(codes[fmt], value)
    except (ValueError, struct.error) as exc:
        raise ValueError(f"{text!r} is not a valid {fmt}: {exc}") from exc
