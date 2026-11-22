"""
Data Browser package: dump/device browsing as partitions and files.

Layers: sources (DataSource/RangeCache) -> partmaps (GPT/cmdline/MBR) ->
signatures (content labels via JSON profiles) -> fs_* (per-FS listing) ->
vfs (unified Explorer-style tree). GUI binding comes later as a separate tab.

src/modes/emmc/data_browser/__init__.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Package init with public exports.
"""

from .sources import DataSource, FileSource, RangeCache
from .partmaps import Partition, build_partition_map, read_gpt, scan_cmdline_map
from .signatures import identify
from .profiles import Profiles
from .vfs import DataBrowser, VfsNode

__all__ = [
    "DataSource", "FileSource", "RangeCache",
    "Partition", "build_partition_map", "read_gpt", "scan_cmdline_map",
    "identify", "Profiles", "DataBrowser", "VfsNode",
]
