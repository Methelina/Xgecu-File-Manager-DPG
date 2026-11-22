"""
Data Browser: partition maps. GPT (UEFI standard, header and array CRC), MBR,
cmdline map mt53xx-emmc:/blkdevparts=mmcblk0: (Linux kernel cmdline format).

LBA ranges are inclusive: size = (last - first + 1) * sector_size.

src/modes/emmc/data_browser/partmaps.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Partition dataclass (name, offset, size, kind).
  [+] GPT: header at LBA1, header CRC32 (zeroed @0x10..0x13) and array CRC32,
      entry walk, backup header detection.
  [+] cmdline map: search for "mt53xx-emmc:"/"blkdevparts=mmcblk0:" in the
      first 2 MiB, parse size<suffix>(name)[enc]; suffix k/K -> *1024,
      m/M -> *1024^2, no suffix -> remainder of the dump.
  [+] MBR 55AA signature detection.
  [+] MStar PT: native partition table at LBA2 (records every 0x200 from 0x400,
      u64 base, u32 size_sectors, u32 attr, name @0x10); partition starts are
      the cumulative byte sums of preceding sizes from offset 0.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class Partition:
    name: str
    offset: int  # bytes from dump start
    size: int
    kind: str  # "gpt" | "cmdline" | "mbr"
    enc: bool = False


def crc32(data: bytes) -> int:
    import zlib
    return zlib.crc32(data) & 0xFFFFFFFF


@dataclass
class GptInfo:
    ok_header_crc: bool
    ok_array_crc: bool
    partitions: list[Partition]
    backup_lba: int


def read_gpt(src, sector_size: int = 512) -> GptInfo | None:
    """GPT header at LBA1; None when the signature is absent."""
    hdr = src.read(sector_size, 0x60)
    if hdr[0:8] != b"EFI PART":
        return None
    (
        _sig, _rev, _hsize, _crc, _rsv, cur_lba, bak_lba, first_lba, last_lba,
        disk_guid, arr_lba, n_entries, entry_size, arr_crc,
    ) = struct.unpack("<8sIIIIQQQQ16sQIII", hdr[:92])
    if not 0 < _hsize <= len(hdr):
        _hsize = 92

    zeroed = bytearray(hdr[:_hsize])
    zeroed[0x10:0x14] = b"\x00\x00\x00\x00"
    ok_header = crc32(bytes(zeroed)) == _crc

    arr = src.read(arr_lba * sector_size, n_entries * entry_size)
    ok_array = crc32(arr) == arr_crc

    parts: list[Partition] = []
    for i in range(n_entries):
        e = arr[i * entry_size:(i + 1) * entry_size]
        if e[0:16] == b"\x00" * 16:
            break
        first, last = struct.unpack_from("<QQ", e, 0x20)
        if last < first:
            continue
        raw_name = e[0x38:0x80].decode("utf-16-le", errors="replace")
        name = raw_name.split("\x00")[0]
        parts.append(Partition(
            name=name,
            offset=first * sector_size,
            size=(last - first + 1) * sector_size,
            kind="gpt",
        ))
    return GptInfo(ok_header_crc=ok_header, ok_array_crc=ok_array,
                   partitions=parts, backup_lba=bak_lba)


def check_backup_gpt(src, sector_size: int = 512) -> bool:
    tail = src.read(src.size() - sector_size, 8)
    return tail[0:8] == b"EFI PART"


_CMDLINE_MARKERS = (
    (b"mt53xx-emmc:", 0x0C),
    (b"blkdevparts=mmcblk0:", 0x14),
)

_UNITS_SMALL = ("k", "K")   # *1024
_UNITS_BIG = ("m", "M")     # *1024**2


def _parse_cmdline_map(text: str, base_offset: int, dump_size: int) -> list[Partition]:
    parts: list[Partition] = []
    cur = base_offset
    for token in text.split(","):
        token = token.strip()
        if not token:
            break
        enc = token.endswith("enc")
        if enc:
            token = token[:-3]
        # size: leading digits, optional unit suffix letter, then (name)
        i = 0
        while i < len(token) and token[i].isdigit():
            i += 1
        num = token[:i]
        rest = token[i:]
        suffix = ""
        name = ""
        if rest.startswith("("):
            close = rest.find(")")
            if close != -1:
                name = rest[1:close]
        else:
            if rest and rest[0] in _UNITS_SMALL + _UNITS_BIG:
                suffix = rest[0]
            if "(" in rest:
                open_i = rest.find("(")
                close = rest.find(")", open_i)
                if close != -1:
                    name = rest[open_i + 1:close]
        if not num:
            # no size digits: last bare-name token takes the rest of the dump
            value = dump_size - cur
            if value <= 0:
                break
            parts.append(Partition(name=name or token.strip("()"),
                                   offset=cur, size=value, kind="cmdline", enc=enc))
            break
        value = int(num)
        if suffix in _UNITS_SMALL:
            value *= 1024
        elif suffix in _UNITS_BIG:
            value *= 1024 * 1024
        else:
            value = dump_size - cur  # last partition takes the remainder
        if value <= 0:
            break
        parts.append(Partition(name=name, offset=cur, size=value, kind="cmdline", enc=enc))
        cur += value
        if cur >= dump_size:
            break
    return parts


def scan_cmdline_map(src, limit: int = 2 * 1024 * 1024) -> list[Partition] | None:
    """Search for a cmdline map within the first limit bytes of the dump."""
    window = min(limit, src.size())
    buf = src.read(0, window)
    for marker, skip in _CMDLINE_MARKERS:
        pos = buf.find(marker)
        if pos != -1:
            text = buf[pos + skip:].split(b" ")[0].decode("ascii", errors="replace")
            return _parse_cmdline_map(text, 0, src.size())
    return None


def detect_mbr(src) -> bool:
    return src.read(0, 512)[510:512] == b"\x55\xaa"


def parse_mstar_pt(src) -> list[Partition] | None:
    """MStar native partition table (no GPT): records at 0x400, stride 0x200.

    Record layout (512 bytes):
      +0x00 u64 base_sectors (constant, informational)
      +0x08 u32 size_sectors
      +0x0C u32 attributes
      +0x10 char name[32]
    Partition start = cumulative sum of preceding sizes in bytes (offset 0).
    """
    head = src.read(0, 0x400)
    if head[0:8] == b"EFI PART":
        return None
    first = src.read(0x400, 0x200)
    name = first[0x10:0x30].split(b"\x00")[0]
    if len(name) < 3 or not all(32 <= c < 127 for c in name):
        return None
    parts: list[Partition] = []
    cur = 0
    for off in range(0x400, 0x4C00, 0x200):
        rec = src.read(off, 0x200)
        raw_name = rec[0x10:0x30].split(b"\x00")[0]
        if len(raw_name) < 3:
            break
        try:
            text = raw_name.decode("ascii")
        except UnicodeDecodeError:
            break
        size_sectors, attr = struct.unpack_from("<II", rec, 8)
        size = size_sectors * 512
        if size == 0:
            break
        dump_size = src.size()
        if cur >= dump_size:
            break
        if cur + size > dump_size:
            # table may overcount trailing partitions; clamp to the dump end
            size = dump_size - cur
        parts.append(Partition(name=text, offset=cur, size=size, kind="mstar-pt"))
        cur += size
    return parts or None


def build_partition_map(src, sector_size: int = 512) -> tuple[list[Partition], dict]:
    """Priority: GPT -> MStar PT -> cmdline -> MBR placeholder."""
    diag: dict = {}
    gpt = read_gpt(src, sector_size)
    if gpt is not None:
        diag["gpt_header_crc_ok"] = gpt.ok_header_crc
        diag["gpt_array_crc_ok"] = gpt.ok_array_crc
        diag["gpt_backup_present"] = check_backup_gpt(src, sector_size)
        if gpt.partitions:
            return gpt.partitions, diag
    mstar = parse_mstar_pt(src)
    if mstar:
        diag["mstar_pt_found"] = True
        return mstar, diag
    cmdline = scan_cmdline_map(src)
    if cmdline:
        diag["cmdline_found"] = True
        return cmdline, diag
    diag["mbr_55aa"] = detect_mbr(src)
    return [], diag
