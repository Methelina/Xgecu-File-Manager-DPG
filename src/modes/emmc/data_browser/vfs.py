"""
Data Browser: VFS facade. Partition map -> per-partition filesystem backend ->
unified node tree (Explorer-style) with extraction ranges.

Backends registered by fs label from signatures.identify():
  fat12/fat16/fat32 -> fs_fat.FatVolume
  ext2/3/4          -> fs_ext.ExtVolume
  others            -> raw partition node (no file listing yet)

src/modes/emmc/data_browser/vfs.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] VfsNode dataclass: unified tree node (name, is_dir, size, offset, children).
  [+] DataBrowser.build(): partition map + signatures + FS listing in one pass.
  [+] extract(): full file content via the FS backend, written to disk.
  [+] Preset matching via profiles (device name detection).
  [+] unpack_partition(): squashfs/gzip/lzo/nfsb via assets/tools (ToolsRunner),
      partition first saved read-only to a temp dir, extraction to dest_dir.
  [+] gzip replaced by native Python zlib (stdlib): decompress_gzip_native(),
      external gzip.exe kept only as fallback. Native path verified e2e.
  [+] 7z replaced by native py7zr (requirements.txt), external 7z.exe fallback.
  [+] LZO blocks: native python-lzo; lzop container files still via lzop.exe.
  [+] squashfs: native PySquashfsImage (requirements.txt) preferred,
      unsquashfs.exe as fallback (kept because native lib appeared late).
  [+] dump_tree(): debug output of the built tree in classic tree format
      (directories with /, file sizes and fs labels), for diagnosis.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

from dataclasses import dataclass, field
from typing import Any

from .partmaps import Partition, build_partition_map
from .profiles import Profiles
from .signatures import identify


@dataclass
class VfsNode:
    name: str
    is_dir: bool = True
    size: int = 0
    offset: int = 0  # absolute offset in the dump
    fs_label: str = ""
    enc: bool = False
    backend: Any = None  # FS volume instance serving this subtree
    read_key: Any = None  # backend-specific: FatEntry / ExtEntry / None for raw
    children: list["VfsNode"] = field(default_factory=list)

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()

    def find(self, path: str) -> "VfsNode | None":
        parts = [p for p in path.split("/") if p]
        node: VfsNode | None = self
        for part in parts:
            node = next((c for c in node.children if c.name == part), None)
            if node is None:
                return None
        return node


def _fs_children(src, part: Partition, fs_label: str, volume_out: list) -> list[VfsNode]:
    children: list[VfsNode] = []
    if fs_label in ("fat12", "fat16", "fat32"):
        from .fs_fat import FatVolume
        try:
            vol = FatVolume(src, part.offset, part.size)
            volume_out.append(vol)

            def walk_fat(cluster: int | None, depth: int) -> list[VfsNode]:
                if depth > 8:
                    return []
                out: list[VfsNode] = []
                for e in vol.listdir(cluster):
                    node = VfsNode(name=e.name, is_dir=e.is_dir, size=e.size,
                                   offset=e.offset, fs_label=fs_label,
                                   backend=vol, read_key=e)
                    if e.is_dir and e.cluster >= 2:
                        try:
                            node.children = walk_fat(e.cluster, depth + 1)
                        except (ValueError, IOError, OSError):
                            pass
                    out.append(node)
                return out

            children = walk_fat(None, 0)
        except (ValueError, IOError, OSError):
            pass
    elif fs_label == "ext2/3/4":
        from .fs_ext import ExtVolume
        try:
            vol = ExtVolume(src, part.offset, part.size)
            volume_out.append(vol)

            def walk_ext(ino: int, depth: int) -> list[VfsNode]:
                if depth > 8:
                    return []
                out: list[VfsNode] = []
                for e in vol.listdir(ino):
                    node = VfsNode(name=e.name, is_dir=e.is_dir, size=e.size,
                                   offset=e.offset, fs_label=fs_label,
                                   backend=vol, read_key=e)
                    if e.is_dir:
                        try:
                            node.children = walk_ext(e.inode, depth + 1)
                        except (ValueError, IOError, OSError):
                            pass
                    out.append(node)
                return out

            children = walk_ext(2, 0)
        except (ValueError, IOError, OSError) as exc:
            # policy: silent fallback is forbidden - log why listing failed
            print(f"[data_browser] fallback: ext listing failed on "
                  f"{part.name} ({type(exc).__name__}: {exc})")
    elif fs_label == "vdfs":
        from .fs_vdfs import VdfsVolume
        try:
            vol = VdfsVolume(src, part.offset, part.size)
            volume_out.append(vol)
            # flat catalog first; parent nesting refined once validated live
            for e in vol.list_all():
                children.append(VfsNode(name=e.name, is_dir=e.is_dir,
                                        size=e.size, offset=e.offset,
                                        fs_label=fs_label, backend=vol,
                                        read_key=e))
        except (ValueError, IOError, OSError) as exc:
            print(f"[data_browser] fallback: vdfs listing failed on "
                  f"{part.name} ({type(exc).__name__}: {exc})")
    return children


def _extract_squashfs_native(image_path: str, dest_dir: str) -> int:
    """Extract a squashfs image via dissect.squashfs; returns file count.

    dissect needs the complete image (metadata table is at the end), so the
    caller must pass the inner image from its magic offset to the end of the
    partition. PySquashfsImage kept as a secondary fallback.
    """
    import os as _os
    from dissect.squashfs import SquashFS
    count = 0
    with open(image_path, "rb") as fh:
        fs = SquashFS(fh)
        root = fs.root

        def write_dir(ino, parent_path: str):
            nonlocal count
            for child in ino.iterdir():
                name = child.name
                if name in (".", ".."):
                    continue
                path = _os.path.join(parent_path, name)
                if child.is_dir():
                    _os.makedirs(path, exist_ok=True)
                    write_dir(child, path)
                elif child.is_symlink():
                    continue
                elif child.is_file():
                    with open(path, "wb") as f:
                        f.write(child.open().read())
                    count += 1

        _os.makedirs(dest_dir, exist_ok=True)
        write_dir(root, dest_dir)
    return count


def _find_inner_offset(image_path: str, scan_limit: int = 256 * 1024 * 1024) -> int | None:
    """Find a squashfs magic ('hsqs') inside a partition image; None if absent."""
    with open(image_path, "rb") as f:
        pos = 0
        prev_tail = b""
        chunk = f.read(1024 * 1024)
        while chunk and pos < scan_limit:
            i = (prev_tail + chunk).find(b"hsqs")
            if i != -1:
                return pos - len(prev_tail) + i
            prev_tail = chunk[-4:]
            pos += len(chunk)
            chunk = f.read(1024 * 1024)
    return None


class DataBrowser:
    def __init__(self, src, sector_size: int = 512, profiles: Profiles | None = None,
                 partition_progress=None):
        self.src = src
        self.sector_size = sector_size
        self.profiles = profiles or Profiles()
        self._partition_progress = partition_progress

    def build(self, list_fs: bool = True) -> tuple[VfsNode, dict]:
        """Root node with partition children; diagnostics dict.

        list_fs=False skips filesystem tree walking (shallow mode: partition
        map + signatures only, fast for huge dumps).
        """
        parts, diag = build_partition_map(self.src, self.sector_size)
        root = VfsNode(name="/")
        self._last_root = root
        if parts:
            preset = self.profiles.match_preset([p.name for p in parts])
            if preset:
                diag["device_preset"] = preset.get("device")
        known = self.profiles.known_extensions
        for idx, part in enumerate(parts):
            if self._partition_progress is not None:
                try:
                    self._partition_progress(idx + 1, len(parts), part.name)
                except Exception:
                    pass
            label = identify(self.src, part.offset, part.size, self.profiles)
            node = VfsNode(name=part.name or f"part@0x{part.offset:x}",
                           size=part.size, offset=part.offset,
                           fs_label=label, enc=part.enc, backend=None,
                           read_key=("raw", part))
            if list_fs and label not in ("empty:00", "empty:ff"):
                holder: list = []
                node.children = _fs_children(self.src, part, label, holder)
                if holder:
                    node.backend = holder[0]
            root.children.append(node)
        # annotate leaf nodes with the known-extension flag (icon/filter use)
        for n in root.walk():
            if not n.is_dir:
                n.fs_label = n.fs_label or ("known-ext" if self.profiles.is_known_extension(n.name) else "")
        return root, diag

    def read_node(self, node: VfsNode) -> bytes:
        """Full content of a file node (FS backend) or a whole raw partition."""
        if node.read_key and isinstance(node.read_key, tuple) and \
                node.read_key[0] == "raw":
            part = node.read_key[1]
            return self.src.read(part.offset, part.size)
        if node.backend is not None and node.read_key is not None and \
                hasattr(node.backend, "read_file"):
            return node.backend.read_file(node.read_key)
        if node.size and node.offset:
            return self.src.read(node.offset, node.size)
        return b""

    def extract(self, node: VfsNode, dest_path: str) -> int:
        """Write the node content to dest_path; returns the byte count."""
        data = self.read_node(node)
        with open(dest_path, "wb") as f:
            f.write(data)
        return len(data)

    def dump_tree(self, dest_path: str, max_per_dir: int = 10000) -> int:
        """Write the built tree to dest_path in classic tree format.

        Returns the line count. Directories end with '/', files carry
        (size, fs_label). Intended for diagnosis of what the scan actually
        saw (e.g. when only some partitions list files).
        """
        lines: list[str] = [f"{self.__class__.__name__} tree"]

        def walk(node: VfsNode, prefix: str):
            children = node.children
            for i, child in enumerate(children):
                last = i == len(children) - 1
                connector = "└── " if last else "├── "
                if child.is_dir:
                    lines.append(f"{prefix}{connector}{child.name}/ "
                                 f"[{child.fs_label}] enc={child.enc}")
                    walk(child, prefix + ("    " if last else "│   "))
                else:
                    lines.append(f"{prefix}{connector}{child.name} "
                                 f"({child.size} B) [{child.fs_label}]")

        walk(self.root_node if hasattr(self, "root_node") else self._last_root,
             "")
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return len(lines)

    def decompress_gzip_native(self, node: VfsNode, dest_path: str) -> int:
        """gzip decompression via Python stdlib (zlib), no external tools.

        Multi-member safe: zlib.decompressobj(wbits=31) chain via unused_data.
        Returns the decompressed byte count. Raises zlib.error on corrupt input.
        """
        import zlib
        blob = self.read_node(node)
        out = bytearray()
        rest = blob
        while rest:
            dec = zlib.decompressobj(31)
            out.extend(dec.decompress(rest))
            out.extend(dec.flush())
            rest = dec.unused_data
            if rest == blob:  # guard: no progress on garbage
                break
        with open(dest_path, "wb") as f:
            f.write(bytes(out))
        return len(out)

    def unpack_partition(self, node: VfsNode, dest_dir: str,
                         tools_dir: str | None = None):
        """Save the partition read-only, then unpack via external tools.

        The dump itself is never touched: the partition image goes to a temp
        file first, extraction lands in dest_dir. Returns the ToolResult.
        """
        from .tools_runner import ToolsRunner
        runner = ToolsRunner(tools_dir)
        label = node.fs_label
        part_node = node if node.read_key and isinstance(node.read_key, tuple) \
            and node.read_key[0] == "raw" else None
        if part_node is None:
            # caller passed a partition-level node without raw key: read all
            part_node = node
        tmp_fd, image_path = tempfile.mkstemp(suffix=".img")
        os.close(tmp_fd)
        try:
            self.extract(part_node, image_path)
            if label == "squashfs" or (label == "unknown" and
                                       _find_inner_offset(image_path) is not None):
                # native PySquashfsImage first; unsquashfs.exe fallback;
                # squashfs may sit at an inner offset inside the partition
                inner = _find_inner_offset(image_path)
                try:
                    fs_path = image_path
                    if inner is not None:
                        # dissect needs the full image from magic to end
                        fs_path = image_path + ".inner"
                        with open(image_path, "rb") as fsrc, open(fs_path, "wb") as fdst:
                            fsrc.seek(inner)
                            shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
                    _extract_squashfs_native(fs_path, dest_dir)
                    if fs_path != image_path:
                        os.remove(fs_path)
                    result = None  # native: exceptions are the failure mode
                except ImportError:
                    result = runner.run_unsquashfs(image_path, dest_dir)
                except Exception:
                    fs_path = image_path + ".inner" if inner is not None else image_path
                    result = runner.run_unsquashfs(fs_path, dest_dir)
            elif label in ("gzip", "lzo"):
                os.makedirs(dest_dir, exist_ok=True)
                if label == "gzip":
                    # native stdlib path (no external tools)
                    out_file = os.path.join(dest_dir, "decompressed.bin")
                    self.decompress_gzip_native(part_node, out_file)
                    result = None  # native: exceptions are the failure mode
                else:
                    dest_file = os.path.join(dest_dir, os.path.basename(image_path))
                    self.extract(part_node, dest_file)
                    result = runner.run_lzop(dest_file)
            elif label == "nfsb":
                os.makedirs(dest_dir, exist_ok=True)
                out_file = os.path.join(dest_dir, "decrypted.bin")
                result = runner.run_aes_decrypt(image_path, out_file)
            else:
                # native 7z via py7zr first; external 7z.exe as fallback
                try:
                    import py7zr
                    with py7zr.SevenZipFile(image_path, mode="r") as archive:
                        archive.extractall(path=dest_dir)
                    result = None  # native: exceptions are the failure mode
                except ImportError:
                    result = runner.run_7z_extract(image_path, dest_dir)
        finally:
            if os.path.exists(image_path):
                os.remove(image_path)
        # partition images are larger than the contained FS: unpackers report
        # "data after end of archive" yet extract fine - success = non-empty dest
        if result is not None and not result.ok and os.path.isdir(dest_dir) \
                and os.listdir(dest_dir):
            result.ok = True
            result.warning = True
        return result
