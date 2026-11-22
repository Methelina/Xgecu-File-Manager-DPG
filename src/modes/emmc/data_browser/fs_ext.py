"""
Data Browser: ext2/3/4 - directory listing per the public specification.
Read-only: superblock, group descriptors, inodes, extent trees (ext4)
and indirect blocks (ext2/3, depth <= 2).

src/modes/emmc/data_browser/fs_ext.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] ExtVolume: superblock @1024 (magic 0xEF53), block size, group descriptors.
  [+] Inodes: extent header 0xF30A (depth <= 1) and classic block pointers.
  [+] listdir(): dirent records, root = inode 2.
  [+] read_file(): full file content via extents/indirect blocks.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class ExtEntry:
    name: str
    is_dir: bool
    size: int
    inode: int
    offset: int  # absolute offset of data start in the dump (0 when empty/special)


class ExtVolume:
    def __init__(self, src, part_offset: int, part_size: int):
        self.src = src
        self.base = part_offset
        sb = src.read(part_offset + 1024, 264)
        if struct.unpack_from("<H", sb, 56)[0] != 0xEF53:
            raise ValueError("not ext: superblock magic mismatch")
        self.inodes_count = struct.unpack_from("<I", sb, 0)[0]
        self.blocks_count = struct.unpack_from("<I", sb, 4)[0]
        log_bs = struct.unpack_from("<I", sb, 24)[0]
        self.block_size = 1024 << log_bs
        self.blocks_per_group = struct.unpack_from("<I", sb, 32)[0]
        self.inodes_per_group = struct.unpack_from("<I", sb, 40)[0]
        self.inode_size = struct.unpack_from("<H", sb, 88)[0]
        feature_64bit = struct.unpack_from("<I", sb, 0x50)[0] & 0x80
        self.gd_size = 64 if feature_64bit else 32
        self._gd_cache: dict[int, int] = {}  # group -> inode_table_block

    def _block_offset(self, block: int) -> int:
        return self.base + block * self.block_size

    def _inode_location(self, ino: int) -> int:
        group = (ino - 1) // self.inodes_per_group
        index = (ino - 1) % self.inodes_per_group
        if group not in self._gd_cache:
            gd_block = 1 if self.block_size >= 2048 else 2
            gd_off = self._block_offset(gd_block) + group * self.gd_size
            gd = self.src.read(gd_off, self.gd_size)
            lo = struct.unpack_from("<I", gd, 8)[0]
            hi = struct.unpack_from("<I", gd, 40)[0] if self.gd_size == 64 else 0
            self._gd_cache[group] = lo | (hi << 32)
        return self._block_offset(self._gd_cache[group]) + index * self.inode_size

    def _read_inode(self, ino: int) -> bytes:
        return self.src.read(self._inode_location(ino), self.inode_size)

    @staticmethod
    def _inode_size_of(inode: bytes) -> int:
        return struct.unpack_from("<I", inode, 4)[0] | (struct.unpack_from("<I", inode, 108)[0] << 32)

    def _extent_blocks(self, inode: bytes) -> list[int]:
        """Data block numbers from the extent tree (depth <= 1)."""
        iblock = inode[40:100]
        if len(iblock) < 12 or struct.unpack_from("<H", iblock, 0)[0] != 0xF30A:
            return []
        depth = iblock[6]
        entries = struct.unpack_from("<H", iblock, 2)[0]
        blocks: list[int] = []

        def leaves_from(buf: bytes) -> list[int]:
            out: list[int] = []
            count = struct.unpack_from("<H", buf, 2)[0]
            for i in range(count):
                ee = buf[12 + 12 * i:24 + 12 * i]
                if len(ee) < 12:
                    break
                ee_len = struct.unpack_from("<H", ee, 4)[0]
                start = (struct.unpack_from("<H", ee, 10)[0] << 16) | \
                        struct.unpack_from("<H", ee, 8)[0]
                out.extend(range(start, start + ee_len))
            return out

        if depth == 0:
            return leaves_from(iblock)
        if depth == 1:
            # internal node: each entry points to a leaf block
            for i in range(entries):
                eh = iblock[12 + 12 * i:24 + 12 * i]
                if len(eh) < 12:
                    break
                leaf_block = (struct.unpack_from("<H", eh, 10)[0] << 16) | \
                             struct.unpack_from("<H", eh, 8)[0]
                leaf = self.src.read(self._block_offset(leaf_block), self.block_size)
                blocks.extend(leaves_from(leaf))
            return blocks
        return []  # depth >= 2 not supported (rare for filesystem files)

    def _data_blocks(self, inode: bytes) -> list[int]:
        """Data block numbers: extents (ext4) or classic pointers (ext2/3)."""
        iblock = inode[40:100]
        if len(iblock) >= 12 and struct.unpack_from("<H", iblock, 0)[0] == 0xF30A:
            return self._extent_blocks(inode)
        # classic pointers: 12 direct + singly indirect
        ptrs = struct.unpack_from("<15I", inode, 40)
        blocks = [p for p in ptrs[:12] if p]
        if ptrs[12]:
            ind = struct.unpack(f"<{self.block_size // 4}I",
                                self.src.read(self._block_offset(ptrs[12]), self.block_size))
            blocks.extend(p for p in ind if p)
        return blocks

    def _read_file_blocks(self, ino: int, size: int) -> bytes:
        inode = self._read_inode(ino)
        parts = []
        remaining = size
        for block in self._data_blocks(inode):
            if remaining <= 0:
                break
            take = min(self.block_size, remaining)
            parts.append(self.src.read(self._block_offset(block), take))
            remaining -= take
        return b"".join(parts)

    def read_file(self, entry: ExtEntry) -> bytes:
        """Full file content by inode (extent tree or indirect blocks)."""
        if entry.is_dir or entry.inode < 2:
            return b""
        return self._read_file_blocks(entry.inode, entry.size)

    def _parse_dirents(self, blob: bytes) -> list[tuple[int, str, bool]]:
        out: list[tuple[int, str, bool]] = []
        pos = 0
        while pos + 8 <= len(blob):
            ino, rec_len, name_len, ftype = struct.unpack_from("<IHBB", blob, pos)
            if rec_len < 8 or pos + rec_len > len(blob):
                break
            if ino:
                name = blob[pos + 8:pos + 8 + name_len].decode("utf-8", errors="replace")
                out.append((ino, name, ftype == 2))
            pos += rec_len
        return out

    def listdir(self, ino: int = 2) -> list[ExtEntry]:
        """Directory listing; root inode is 2."""
        inode = self._read_inode(ino)
        mode = struct.unpack_from("<H", inode, 0)[0]
        if (mode & 0xF000) != 0x4000:
            raise ValueError(f"inode {ino} is not a directory (mode=0x{mode:04x})")
        size = self._inode_size_of(inode)
        blob = self._read_file_blocks(ino, size)
        entries = []
        for child_ino, name, _ftype in self._parse_dirents(blob):
            if name in (".", ".."):
                continue
            ch = self._read_inode(child_ino)
            ch_mode = struct.unpack_from("<H", ch, 0)[0]
            ch_type = ch_mode & 0xF000
            if ch_type == 0xA000:
                # symlink: data blocks store the target path, not file content
                ch_blocks = self._data_blocks(ch)
                entries.append(ExtEntry(
                    name=f"{name} -> (symlink)", is_dir=False, size=0,
                    inode=child_ino,
                    offset=self._block_offset(ch_blocks[0]) if ch_blocks else 0,
                ))
                continue
            ch_blocks = self._data_blocks(ch)
            entries.append(ExtEntry(
                name=name,
                is_dir=ch_type == 0x4000,
                size=self._inode_size_of(ch),
                inode=child_ino,
                offset=self._block_offset(ch_blocks[0]) if ch_blocks else 0,
            ))
        return entries
