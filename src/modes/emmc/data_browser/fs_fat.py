"""
Data Browser: FAT12/16/32 - directory listing per the public specification.
Read-only: BPB, FAT chains, LFN.

src/modes/emmc/data_browser/fs_fat.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] FatVolume: BPB parsing, FAT type detection, cluster chains.
  [+] listdir(): 32-byte 8.3 entries + LFN, hierarchy via cluster chains.
  [+] read_file(): full file content via the cluster chain.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

ATTR_DIR = 0x10
ATTR_VOLUME = 0x08
ATTR_LFN = 0x0F
ENTRY_END = 0x00
ENTRY_FREE = 0xE5


@dataclass
class FatEntry:
    name: str
    is_dir: bool
    size: int
    cluster: int
    offset: int  # absolute offset of data start in the dump


class FatVolume:
    def __init__(self, src, part_offset: int, part_size: int):
        self.src = src
        self.base = part_offset
        self.size = part_size
        bpb = src.read(part_offset, 512)
        self.bps = struct.unpack_from("<H", bpb, 0x0B)[0]
        self.spc = bpb[0x0D]
        self.reserved = struct.unpack_from("<H", bpb, 0x0E)[0]
        self.nfats = bpb[0x10]
        self.root_entries = struct.unpack_from("<H", bpb, 0x11)[0]
        totsec16 = struct.unpack_from("<H", bpb, 0x13)[0]
        self.fat_size16 = struct.unpack_from("<H", bpb, 0x16)[0]
        totsec32 = struct.unpack_from("<I", bpb, 0x20)[0]
        self.fat_size32 = struct.unpack_from("<I", bpb, 0x24)[0]
        self.root_cluster = struct.unpack_from("<I", bpb, 0x2C)[0]
        totsec = totsec16 or totsec32
        fat_size = self.fat_size16 or self.fat_size32
        root_dir_sectors = (self.root_entries * 32 + self.bps - 1) // self.bps
        self.first_data_sector = self.reserved + self.nfats * fat_size + root_dir_sectors
        data_sectors = totsec - self.first_data_sector
        clusters = data_sectors // self.spc
        self.fat_type = "FAT12" if clusters < 4085 else ("FAT16" if clusters < 65525 else "FAT32")
        self._fat_cache: bytes | None = None

    def _cluster_offset(self, cluster: int) -> int:
        return self.base + (self.first_data_sector + (cluster - 2) * self.spc) * self.bps

    def _fat(self) -> bytes:
        if self._fat_cache is None:
            offset = self.base + self.reserved * self.bps
            fat_sectors = self.fat_size16 or self.fat_size32
            self._fat_cache = self.src.read(offset, fat_sectors * self.bps)
        return self._fat_cache

    def _next_cluster(self, cluster: int) -> int | None:
        fat = self._fat()
        if self.fat_type == "FAT12":
            byte_i = cluster + cluster // 2
            if byte_i + 1 >= len(fat):
                return None
            v = fat[byte_i] | (fat[byte_i + 1] << 8)
            value = (v >> 4) if cluster & 1 else (v & 0xFFF)
            eoc = value >= 0xFF8
        elif self.fat_type == "FAT16":
            if cluster * 2 + 2 > len(fat):
                return None
            value = struct.unpack_from("<H", fat, cluster * 2)[0]
            eoc = value >= 0xFFF8
        else:
            if cluster * 4 + 4 > len(fat):
                return None
            value = struct.unpack_from("<I", fat, cluster * 4)[0] & 0x0FFFFFFF
            eoc = value >= 0x0FFFFFF8
        return None if eoc or value in (0x0000, 0x0FF7, 0xFFF7) else value

    def _cluster_chain(self, start: int, max_clusters: int = 1_000_000) -> list[int]:
        chain = [start]
        seen = {start}
        cur = start
        for _ in range(max_clusters):
            nxt = self._next_cluster(cur)
            if nxt is None or nxt in seen:
                break
            chain.append(nxt)
            seen.add(nxt)
            cur = nxt
        return chain

    def _read_cluster_chain(self, start: int, size_limit: int | None = None) -> bytes:
        parts = []
        total = 0
        for c in self._cluster_chain(start):
            data = self.src.read(self._cluster_offset(c), self.bps * self.spc)
            parts.append(data)
            total += len(data)
            if size_limit is not None and total >= size_limit:
                break
        blob = b"".join(parts)
        return blob[:size_limit] if size_limit is not None else blob

    @staticmethod
    def _lfn_from(parts: list[bytes]) -> str | None:
        if not parts:
            return None
        chars: list[str] = []
        for rec in reversed(parts):
            chars.append(rec[1:11].decode("utf-16-le", errors="replace"))
            chars.append(rec[14:26].decode("utf-16-le", errors="replace"))
            chars.append(rec[28:32].decode("utf-16-le", errors="replace"))
        name = "".join(chars).split("\x00")[0].split("\uffff")[0]
        return name or None

    @staticmethod
    def _short_name(rec: bytes) -> str:
        base = rec[0:8].decode("ascii", errors="replace").rstrip()
        ext = rec[8:11].decode("ascii", errors="replace").rstrip()
        first = rec[0]
        if first == 0x05:
            base = "\xe5" + base[1:]
        return f"{base}.{ext}" if ext else base

    def listdir(self, cluster: int | None = None) -> list[FatEntry]:
        """Directory listing; None = root (FAT16 root area / FAT32 root_cluster)."""
        entries: list[FatEntry] = []
        if cluster is None:
            if self.fat_type == "FAT32":
                cluster = self.root_cluster
                blob = self._read_cluster_chain(cluster)
            else:
                start = self.base + (self.reserved + self.nfats * self.fat_size16) * self.bps
                blob = self.src.read(start, self.root_entries * 32)
        else:
            blob = self._read_cluster_chain(cluster)

        lfn_parts: list[bytes] = []
        for i in range(0, len(blob) - 31, 32):
            rec = blob[i:i + 32]
            first = rec[0]
            if first == ENTRY_END:
                break
            if first == ENTRY_FREE:
                lfn_parts = []
                continue
            attr = rec[11]
            if attr == ATTR_LFN:
                lfn_parts.append(rec)
                continue
            if attr & ATTR_VOLUME:
                lfn_parts = []
                continue
            name = self._lfn_from(lfn_parts) or self._short_name(rec)
            lfn_parts = []
            clus = struct.unpack_from("<H", rec, 26)[0]
            if self.fat_type == "FAT32":
                clus |= struct.unpack_from("<H", rec, 20)[0] << 16
            size = struct.unpack_from("<I", rec, 28)[0]
            if clus == 0 and not (attr & ATTR_DIR):
                continue
            entries.append(FatEntry(
                name=name,
                is_dir=bool(attr & ATTR_DIR),
                size=size,
                cluster=clus,
                offset=self._cluster_offset(clus) if clus >= 2 else 0,
            ))
        return entries

    def read_file(self, entry: FatEntry) -> bytes:
        """Full file content by following the cluster chain, truncated to size."""
        if entry.is_dir or entry.cluster < 2:
            return b""
        return self._read_cluster_chain(entry.cluster, size_limit=entry.size or None)
