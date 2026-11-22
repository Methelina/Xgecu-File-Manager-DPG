"""
Data Browser: partition content identification by signatures (check_part).
Magic table comes from the pluggable profile cfg/data_browser/signatures.json.

src/modes/emmc/data_browser/signatures.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] identify(): signature table from JSON profile (profiles.Profiles),
      code-level fallback defaults.
  [+] empty detection: all 00 or all FF.
"""

from __future__ import annotations

import struct

from .profiles import Profiles


def _all_same(data: bytes) -> int | None:
    if not data:
        return None
    first = data[0]
    if first in (0x00, 0xFF) and data == bytes([first]) * len(data):
        return first
    return None


def identify(src, offset: int, size: int, profiles: Profiles | None = None) -> str:
    """Content label for a partition. Reads header areas only."""
    if size <= 0:
        return "empty"
    head = src.read(offset, min(4096, size))
    if not head:
        return "empty"
    fill = _all_same(head)
    if fill is not None:
        return f"empty:{'ff' if fill == 0xFF else '00'}"

    prof = profiles or Profiles()
    label = prof.identify(head)
    if label != "unknown":
        return label

    # Rules not expressible as a single magic at a fixed offset.
    if len(head) >= 512 and head[510:512] == b"\x55\xaa":
        bps = struct.unpack_from("<H", head, 0x0B)[0]
        if bps in (512, 1024, 2048, 4096):
            return _fat_label(head)
    return "unknown"


def _fat_label(head: bytes) -> str:
    """FAT sub-type from BPB geometry (labels at 54/82 are unreliable)."""
    bps = struct.unpack_from("<H", head, 0x0B)[0]
    spc = head[0x0D]
    reserved = struct.unpack_from("<H", head, 0x0E)[0]
    nfats = head[0x10]
    root_entries = struct.unpack_from("<H", head, 0x11)[0]
    totsec16 = struct.unpack_from("<H", head, 0x13)[0]
    fat_size16 = struct.unpack_from("<H", head, 0x16)[0]
    totsec32 = struct.unpack_from("<I", head, 0x20)[0]
    fat_size32 = struct.unpack_from("<I", head, 0x24)[0]
    if totsec16 == 0 and fat_size16 == 0 and fat_size32:
        return "fat32"
    totsec = totsec16 or totsec32
    fat_size = fat_size16 or fat_size32
    root_dir_sectors = (root_entries * 32 + bps - 1) // bps
    first_data = reserved + nfats * fat_size + root_dir_sectors
    clusters = (totsec - first_data) // spc
    if clusters < 4085:
        return "fat12"
    if clusters < 65525:
        return "fat16"
    return "fat32"
