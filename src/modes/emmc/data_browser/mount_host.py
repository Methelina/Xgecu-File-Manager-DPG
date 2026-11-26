"""WinFsp mount host: serves one dump tree as a drive in this process.

Started by data_browser.mount (MountManager) as an isolated child: a
native winfspy crash kills only this process, never the GUI. Reads file
bytes straight from the dump (read-only); the tree index arrives via a
JSON cache file, so no recursive scans happen at runtime.

src/modes/emmc/data_browser/mount_host.py
Version:     0.2.0
Author:      Soror L.'.L.'
Updated:     2026-11-26

Patch Notes v0.2.0 (Soror L.'.L.'.):
  [*] Volume params switched to the memfs-proven set under WinFsp 2.0 -
      the previous flag combination hung fs.start() indefinitely on
      fresh letters (which is how zombie letters were born).
  [+] Bounded lifetime: the host self-stops gracefully after
      EMMC_MOUNT_IDLE_S (default 900 s) without any request.

Patch Notes v0.1.2 (Soror L.'.L.'.):
  [*] sys.path bootstrap: when started by absolute path with another cwd,
      the src root (parents[3]) is inserted so `modes.*` imports resolve.

Patch Notes v0.1.1 (Soror L.'.L.'.):
  [*] sys.path bootstrap added.

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Cache-file driven TreeOps (dirs/files/index built once at load),
      dump bytes via FileSource+RangeCache, read-only volume, READY
      handshake on stdout, stop when stdin closes or on SIGTERM.
"""

import json
import logging
import os
import stat
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

log = logging.getLogger("xgecu.mount_host")

_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_NORMAL = 0x80
_IDLE_S = int(os.environ.get("EMMC_MOUNT_IDLE_S", "900"))


def _attrs_for(is_dir: bool) -> int:
    return _FILE_ATTRIBUTE_DIRECTORY if is_dir else _FILE_ATTRIBUTE_NORMAL


class _Entry:
    """Immutable mount index built once from the cache file."""

    def __init__(self, cache: dict):
        self.dump_path = cache["dump_path"]
        self.label = cache.get("label", "XGECU_DUMP")
        self.total_size = cache.get("total_size", 0)
        self.last_activity = time.time()
        self.dir_index: dict[str, list] = {}
        self.info_cache: dict[str, dict] = {}
        self.path_map: dict[str, dict] = {}
        for path_key, spec in cache["paths"].items():
            is_dir, size, offset = spec
            self.info_cache[path_key] = {
                "file_attributes": _attrs_for(is_dir),
                "allocation_size": size,
                "file_size": size,
                "creation_time": 0,
                "last_access_time": 0,
                "last_write_time": 0,
                "change_time": 0,
                "index_number": 0,
                "hard_links": 1,
            }
            self.path_map[path_key] = {
                "path": path_key, "is_dir": is_dir,
                "size": size, "offset": offset,
            }
            if path_key == "/":
                continue
            parent = path_key.rsplit("/", 1)[0] or "/"
            name = path_key.rsplit("/", 1)[-1]
            self.dir_index.setdefault(parent, []).append((name, path_key))

    def touch(self):
        self.last_activity = time.time()


def _build_operations_class(entry, src, letter):
    from winfspy import NTStatusError
    from winfspy.file_system import BaseFileSystemOperations
    from winfspy.operations import SecurityDescriptor
    from winfspy.memfs import operation

    class HostOps(BaseFileSystemOperations):
        def __init__(self):
            self._thread_lock = threading.RLock()
            super().__init__()
            self._sec = SecurityDescriptor.from_string(
                "O:BAG:SYD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
                "(A;OICIIO;FA;;;CO)(A;OICI;FA;;;WD)"
            )
            self._sec_handle = self._sec.handle
            self._sec_size = self._sec.size

        @operation
        def get_volume_info(self):
            entry.touch()
            return {"total_size": entry.total_size, "free_size": 0,
                    "volume_label": entry.label[:32] or "XGECU_DUMP"}

        @operation
        def get_security_by_name(self, file_name):
            entry.touch()
            path = "/" + file_name.replace("\\", "/").lstrip("/")
            info = entry.info_cache.get(path)
            if info is None:
                raise NTStatusError(0xC0000034)
            return info["file_attributes"], self._sec_handle, self._sec_size

        @operation
        def get_security(self, file_context):
            entry.touch()
            return self._sec_handle, self._sec_size

        @operation
        def open(self, file_name, create_options, granted_access):
            entry.touch()
            path = "/" + file_name.replace("\\", "/").lstrip("/")
            spec = entry.path_map.get(path)
            if spec is None:
                raise NTStatusError(0xC0000034)
            return {"path": path, "spec": spec}

        @operation
        def close(self, file_context):
            pass

        @operation
        def cleanup(self, file_context, file_name, flags):
            if flags & 0x01:  # FspCleanupDelete - read-only volume
                raise NTStatusError(0xC00000A5)

        @operation
        def flush(self, file_context):
            return {}

        @operation
        def get_file_info(self, file_context):
            entry.touch()
            info = entry.info_cache.get(file_context["path"])
            if info is None:
                raise NTStatusError(0xC0000034)
            return dict(info)

        @operation
        def read(self, file_context, offset, length):
            entry.touch()
            spec = file_context["spec"]
            size, off0 = spec["size"], spec["offset"]
            if length <= 0 or offset >= size:
                return b""
            length = min(length, size - offset)
            try:
                return src.read(off0 + offset, length)
            except Exception as exc:  # noqa: BLE001
                log.warning("[mount_host] fallback: read error %s+%d (%s)",
                            spec["path"], offset, exc)
                return b"\x00" * length

        @operation
        def read_directory(self, file_context, marker):
            entry.touch()
            children = entry.dir_index.get(file_context["path"], ())
            out = []
            for name, child_path in children:
                if marker is not None and name <= marker:
                    continue
                out.append({"file_name": name,
                            **entry.info_cache[child_path]})
            return out

        @operation
        def set_volume_label(self, volume_label):
            raise NTStatusError(0xC00000A5)

        @operation
        def overwrite(self, file_context, file_attributes, replace_if,
                      allocation_size, end_of_file):
            raise NTStatusError(0xC00000A5)

        @operation
        def can_delete(self, file_context):
            raise NTStatusError(0xC00000A5)

        @operation
        def write(self, file_context, buffer, offset, write_to_end_of_file,
                  constrained_io, write_maximum_offset, write_maximum_length):
            raise NTStatusError(0xC00000A5)

    return HostOps


def main():
    cache_path = sys.argv[1]
    letter = sys.argv[2]
    logging.basicConfig(level=logging.ERROR)
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)
    from modes.emmc.data_browser.sources import FileSource, RangeCache
    from winfspy.file_system import FileSystem
    from winfspy.plumbing import filetime_now

    src = RangeCache(FileSource(cache["dump_path"]),
                     chunk_size=16384, max_chunks=1024)
    entry = _Entry(cache)
    HostOps = _build_operations_class(entry, src, letter)
    # memfs-proven volume param set under WinFsp 2.0: the alternative flag
    # combination hangs fs.start() indefinitely on fresh letters.
    fs = FileSystem(
        letter + ":",
        HostOps(),
        sector_size=512,
        sectors_per_allocation_unit=1,
        volume_creation_time=filetime_now(),
        volume_serial_number=0,
        file_info_timeout=1000,
        case_sensitive_search=1,
        case_preserved_names=1,
        unicode_on_disk=1,
        persistent_acls=1,
        post_cleanup_when_modified_only=1,
        um_file_context_is_user_context2=1,
        prefix="",
        reject_irp_prior_to_transact0=0,
        # NOTE: read_only_volume=1 is deliberately NOT set here - under
        # WinFsp 2.0 + winfspy 0.8.4 it breaks FspFileSystemSetMountPoint
        # with STATUS_OBJECT_PATH_NOT_FOUND. Read-only is enforced by the
        # operations layer (every write/delete raises ACCESS_DENIED).
        file_system_name="XGECU_DUMP",
    )
    fs.start()
    if not cache.get("no_handshake"):
        os.stat(letter + ":\\")
    print("READY", flush=True)
    stop = threading.Event()
    # stdin closed by the parent on unmount - graceful stop
    watcher = threading.Thread(
        target=lambda: (sys.stdin.buffer.read(), stop.set()), daemon=True)
    watcher.start()
    while not stop.wait(1):
        if time.time() - entry.last_activity > _IDLE_S:
            log.info("[mount_host] idle over %d s: stopping %s:",
                     _IDLE_S, letter)
            break
    fs.stop()


if __name__ == "__main__":
    main()
