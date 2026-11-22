"""
Data Browser: VDFS filesystem (Philips/MStar TVs) - catalog listing per the
reverse-engineered structures (recon sections 16.1/16.3).

Superblock signatures: VDFS2006 / VDFS2007 / VDFS1002 / VDFS0001 / 1eMMCFS.
Layout notes:
  - fork pointer table sits at the END of the fork area: entry i is a u32 at
    (fork_area_end - 4*(i+1)), counted backwards;
  - each catalog record is 0x120 bytes at (base + table_value):
      +0x00 u32 self_offset      +0x04 u16 name_len (seek delta)
      +0x08 i64 parent_id        +0x10 u32 attr
      +0x110 i64 size            +0x118 u8 type (1=dir node, 2=file)
      +0x119 char name[255]
  - file data address = start_page * page_size + base (4 KiB page addressing);
  - read-only: only enough to list the tree and give extraction ranges.

src/modes/emmc/data_browser/fs_vdfs.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] VdfsVolume: superblock detection, fork table read, catalog record walk.
  [+] listdir(): entries with parent_id/type/name/size, flat then nested.
  [+] read_file(): page-addressed range readback.
  [+] EXPERIMENTAL: field offsets verified against recon; no live VDFS dump
      available yet - validate on the first real VDFS partition before use.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURES = (b"VDFS2006", b"VDFS2007", b"VDFS1002", b"VDFS0001", b"1eMMCFS")
PAGE_SIZE = 0x1000
RECORD_SIZE = 0x120
TYPE_DIR = 1
TYPE_FILE = 2


@dataclass
class VdfsEntry:
    name: str
    is_dir: bool
    size: int
    parent_id: int
    offset: int  # absolute offset of data start in the dump


class VdfsVolume:
    def __init__(self, src, part_offset: int, part_size: int):
        self.src = src
        self.base = part_offset
        self.size = part_size
        sig = src.read(part_offset, 8)
        if sig not in SIGNATURES:
            raise ValueError(f"not VDFS: signature {sig!r}")
        self.version = sig.decode("ascii", errors="replace")
        # superblock probe: fork area parameters live at +0x600 region
        # (VDFS2006/2007) or +0x679 (0001/1eMMCFS); refined per recon 16.1.
        if self.version in ("VDFS2006", "VDFS2007", "VDFS1002"):
            probe_off = 0x600
        else:
            probe_off = 0x679
        meta = src.read(part_offset + probe_off, 32)
        self.fork_count = struct.unpack_from("<H", meta, 0x0E)[0]
        self.fork_table_abs = part_offset + probe_off  # end of fork area, refined live

    def _fork_offsets(self) -> list[int]:
        """Catalog entry offsets: u32 values read backwards from the fork end."""
        out: list[int] = []
        for i in range(self.fork_count):
            pos = self.fork_table_abs - 4 * (i + 1)
            (val,) = struct.unpack("<I", self.src.read(pos, 4))
            out.append(self.base + val)
        return out

    def _read_record(self, abs_off: int) -> VdfsEntry | None:
        rec = self.src.read(abs_off, RECORD_SIZE)
        name_len = struct.unpack_from("<H", rec, 0x04)[0]
        parent_id, = struct.unpack_from("<q", rec, 0x08)
        size, = struct.unpack_from("<q", rec, 0x110)
        ftype = rec[0x118]
        raw_name = rec[0x119:0x119 + 0xFF].split(b"\x00")[0]
        try:
            name = raw_name.decode("cp1251")
        except UnicodeDecodeError:
            name = raw_name.decode("ascii", errors="replace")
        if not name:
            return None
        (start_page,) = struct.unpack_from("<q", rec, 0x0C)
        data_off = self.base + start_page * PAGE_SIZE if start_page > 0 else 0
        return VdfsEntry(name=name, is_dir=(ftype == TYPE_DIR), size=max(0, size),
                         parent_id=parent_id, offset=data_off)

    def list_all(self) -> list[VdfsEntry]:
        """Flat catalog: all records with a name (dirs type=1, files type=2)."""
        entries: list[VdfsEntry] = []
        seen: set[int] = set()
        for abs_off in self._fork_offsets():
            entry = self._read_record(abs_off)
            if entry is None or abs_off in seen:
                continue
            seen.add(abs_off)
            entries.append(entry)
        return entries

    def read_file(self, entry: VdfsEntry) -> bytes:
        """Full file content via page-addressed range read."""
        if entry.is_dir or entry.offset == 0 or entry.size == 0:
            return b""
        return self.src.read(entry.offset, entry.size)
