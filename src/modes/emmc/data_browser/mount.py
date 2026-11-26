"""Data Browser: mount a scanned partition tree as a Windows drive letter.

User-mode FS via WinFsp (winfspy); read-only by construction. The tree is
the VfsNode subtree produced by DataBrowser.build(); file reads go straight
to the dump through RangeCache within the node's offset/size - the dump is
never written and never fully copied. Linux/macOS are out of scope for this
module (pyfuse3 path stays a research note in recon).

src/modes/emmc/data_browser/mount.py
Version:     0.4.3
Author:      Soror L.'.L.'
Updated:     2026-11-26

Patch Notes v0.4.3 (Soror L.'.L.'.):
  [*] Resolve the dump path through the whole source wrapper chain
      (ProgressSource -> RangeCache -> FileSource) without mutating the
      caller's browser; a single-level getattr misclassified GUI-wrapped
      dumps as live chips and refused every mount from the GUI.
  [+] progress callback on mount_tree/mount_auto: stage strings for the
      GUI status bar (letter pick, indexing, host start, READY wait).

Patch Notes v0.4.2 (Soror L.'.L.'.):
  [*] Pass the bare drive letter to mount_host; it adds the colon when
      constructing the WinFsp mount point.

Patch Notes v0.4.0 (Soror L.'.L.'.):
  [+] Process isolation: the mount runs in a child python (mount_host.py);
      a native winfspy crash can no longer take down the GUI, and the
      manager watches the child instead of hosting FS threads.
  [+] Known-bad combo gate: WinFsp >= 2.1 with winfspy 0.8.4 is refused
      (from_handle(garbage) class of crashes); tagged warning states the
      fix (WinFsp 2.0.x or a winfspy release supporting WinFsp 2.x).

Patch Notes v0.2.1 (Soror L.'.L.'.):
  [*] Auto-pick scans the full A..Z alphabet instead of a fixed R..Z
      interval; the only skip rule is "letter exists in the OS", so user
      disks can never collide.

Patch Notes v0.3.0 (Soror L.'.L.'.):
  [+] Prebuilt mount cache (single pass, no per-request recursion):
      dir_index {dir_path: [(name, node)]} -> O(children) read_directory;
      info_cache {path: ready file-info dict} -> O(1) get_file_info.
      The FS answers from the cache; the dump is read only for file bytes.

Patch Notes v0.2.0 (Soror L.'.L.'):
  [+] Letter safety: system_used_letters()/is_letter_free() via
      GetLogicalDrives + QueryDosDevice; auto-pick scans R..Z and picks
      only a letter that is absent from the OS; an explicit letter that
      exists in the system is refused - user disks can never be touched.
  [*] mount_tree(letter=None) auto-selects; fail-fast start with
      _MountEntry.start_error; entry removed on start failure.

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] MountManager: mount_tree/unmount/unmount_all/list_mounts, one daemon
      thread per drive letter, availability probe for WinFsp.
  [+] TreeOps: path-based winfspy operations over a VfsNode map; file reads
      served as range reads (offset+size), graceful zeros on read errors.
  [+] Tagged fallback logging per project error policy.
"""

import subprocess
import sys
import tempfile

import atexit
import ctypes
import json
import logging
import os
import stat
import threading
import time

log = logging.getLogger("xgecu.mount")

_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_NORMAL = 0x80

_WINFSP_DLL = "C:\\Program Files (x86)\\WinFsp\\bin\\winfsp-x64.dll"

_READ_CHUNK = 1 << 20


def _attrs_for(is_dir: bool) -> int:
    return _FILE_ATTRIBUTE_DIRECTORY if is_dir else _FILE_ATTRIBUTE_NORMAL


def build_path_map(root) -> dict[str, object]:
    """Map posix-style path -> VfsNode for the whole subtree of root."""
    out: dict[str, object] = {}

    def _walk(node, prefix: str):
        out[prefix or "/"] = node
        for child in getattr(node, "children", []) or []:
            child_path = f"{prefix.rstrip('/')}/{child.name}" if prefix else f"/{child.name}"
            if child.is_dir:
                _walk(child, child_path)
            else:
                out[child_path] = child

    _walk(root, "/" if root.is_dir else "")
    if not root.is_dir:
        out["/"] = root
    return out


def is_available() -> bool:
    """True when WinFsp runtime + winfspy bindings are importable."""
    if os.name != "nt":
        return False
    if not os.path.exists(_WINFSP_DLL):
        return False
    try:
        import winfspy  # noqa: F401
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[mount] fallback: winfspy import failed (%s)", exc)
        return False


def system_used_letters() -> set[str]:
    """Letters the OS currently exposes (local, network, subst - all)."""
    if os.name != "nt":
        return set()
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return {chr(ord("A") + i) for i in range(26) if mask >> i & 1}


def is_letter_free(letter: str) -> bool:
    """True when the OS has no drive or DOS-device mapping on `letter`."""
    letter = letter.upper().rstrip(":")
    if letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" or len(letter) != 1:
        return False
    if letter in system_used_letters():
        return False
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.QueryDosDeviceW(letter + ":", buf, 260)
    return ctypes.windll.kernel32.GetLastError() == 2  # ERROR_FILE_NOT_FOUND


def free_letters() -> list[str]:
    """All OS-free letters, first-fit order over the full A..Z alphabet.

    No fixed interval: a letter qualifies if the OS has neither a drive
    nor a DOS-device mapping on it - that is the safety guarantee, user
    disks are skipped by this check alone.
    """
    return [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if is_letter_free(c)]


def remove_letter(letter: str) -> None:
    """Force-remove a DOS-device definition for `letter` (zombie janitor).

    WinFsp leaves a defined (but dead) DOS device behind when fs.start()
    fails mid-mount; every later process touching that letter hangs. This
    removes up to five stacked definitions.
    """
    if os.name != "nt":
        return
    letter = letter.upper().rstrip(":")
    kernel32 = ctypes.windll.kernel32
    for _ in range(5):
        if not kernel32.DefineDosDeviceW(1, letter + ":", None):
            break


def _winfsp_version() -> tuple[int, int, int, int] | None:
    """File version of winfsp-x64.dll, or None when it cannot be read."""
    try:
        kernel32 = ctypes.windll.version
        path = _WINFSP_DLL
        size = kernel32.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not kernel32.GetFileVersionInfoW(path, 0, size, data):
            return None
        ptr = ctypes.c_void_p()
        val_len = ctypes.c_uint()
        if not kernel32.VerQueryValueW(data, "\\", ctypes.byref(ptr),
                                       ctypes.byref(val_len)):
            return None
        # VS_FIXEDFILEINFO: dwFileVersionMS/LS at offsets 8/12 (after
        # dwSignature+dwStrucVersion at 0/4)
        raw = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 6)).contents
        ms, ls = raw[2], raw[3]
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception as exc:  # noqa: BLE001
        log.warning("[mount] fallback: cannot read WinFsp version (%s)", exc)
        return None


def is_version_supported() -> bool:
    """False on WinFsp versions that empirically fail with winfspy 0.8.4.

    Empirics of 2026-11-26 on this stack: WinFsp 2.2.26323 mounted dozens
    of drives successfully with winfspy 0.8.4; WinFsp 2.0.23075 failed
    every mount with STATUS_OBJECT_PATH_NOT_FOUND (elevated or not).
    Allowed: >= 2.2. Refused: 2.0.x (the failed downgrade) and unknown.
    """
    version = _winfsp_version()
    if version is None:
        log.warning("[mount] fallback: WinFsp version unknown - mount "
                    "allowed, but report any crash immediately")
        return True
    if version < (2, 2, 0, 0):
        log.warning("[mount] fallback: WinFsp %s fails mounting with "
                    "winfspy 0.8.4 (install WinFsp >= 2.2) - mount refused",
                    ".".join(map(str, version)))
        return False
    return True


def _read_range(browser, node, offset: int, length: int) -> bytes:
    """Range read of a file node; never raises to the FS caller."""
    if length <= 0 or node.is_dir:
        return b""
    try:
        if node.offset and node.size:
            length = min(length, max(0, node.size - offset))
            if length <= 0:
                return b""
            return browser.src.read(node.offset + offset, length)
        data = browser.read_node(node)
        return data[offset:offset + length]
    except Exception as exc:  # noqa: BLE001
        log.warning("[mount] fallback: read error at %s+%d (%s)",
                    getattr(node, "name", "?"), offset, exc)
        return b"\x00" * length


def _build_operations_class():
    """Import winfspy lazily and return a bound operations class."""
    import datetime

    from winfspy import NTStatusError
    from winfspy.file_system import BaseFileSystemOperations, FileSystem
    from winfspy.plumbing import dt_to_filetime
    from winfspy.plumbing.security_descriptor import SecurityDescriptor
    try:
        from winfspy.memfs import operation
    except ImportError:
        operation = None

    _EPOCH = datetime.datetime(1970, 1, 1)

    def _filetime(ts: float) -> int:
        if ts <= 0:
            return 0
        return dt_to_filetime(_EPOCH + datetime.timedelta(seconds=ts))

    class TreeOps(BaseFileSystemOperations):
        def __init__(self, manager, letter):
            if operation is None:
                raise RuntimeError("winfspy operation decorator unavailable")
            self._thread_lock = threading.RLock()
            super().__init__()
            self._manager = manager
            self._letter = letter
            self._sec = SecurityDescriptor.from_string(
                "O:BAG:SYD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
                "(A;OICIIO;FA;;;CO)(A;OICI;FA;;;WD)"
            )
            self._handle_bytes = self._sec.handle
            self._handle_size = self._sec.size

        def _norm(self, file_name: str) -> str:
            return "/" + file_name.replace("\\", "/").lstrip("/")

        @operation
        def get_volume_info(self):
            entry = self._manager._mounts.get(self._letter)
            return {
                "total_size": entry.total_size,
                "free_size": 0,
                "volume_label": entry.label[:32] or "XGECU_DUMP",
            }

        @operation
        def get_security_by_name(self, file_name):
            path = self._norm(file_name)
            node = self._manager._mounts[self._letter].path_map.get(path)
            if node is None:
                raise NTStatusError(0xC0000034)  # OBJECT_NAME_NOT_FOUND
            return _attrs_for(node.is_dir), self._handle_bytes, self._handle_size

        @operation
        def get_security(self, file_context):
            return self._handle_bytes, self._handle_size

        @operation
        def open(self, file_name, create_options, granted_access):
            path = self._norm(file_name)
            entry = self._manager._mounts[self._letter]
            node = entry.path_map.get(path)
            if node is None:
                raise NTStatusError(0xC0000034)
            context = {"path": path, "is_dir": node.is_dir, "node": node}
            # Keep contexts alive for the whole session (capped): a freed
            # cffi handle address can be recycled while a duplicate
            # cleanup/close is still in flight on another thread, which
            # winfspy 0.8.4 + WinFsp 2.2 turns into from_handle(garbage).
            entry.open_contexts.add(context)
            return context

        @operation
        def close(self, file_context):
            entry = self._manager._mounts[self._letter]
            if len(entry.open_contexts) > 200_000:
                entry.open_contexts.clear()

        @operation
        def cleanup(self, file_context, file_name, flags):
            if flags & 0x01:  # FspCleanupDelete - read-only volume
                raise NTStatusError(0xC00000A5)  # ACCESS_DENIED

        @operation
        def flush(self, file_context):
            return {}

        @operation
        def get_file_info(self, file_context):
            entry = self._manager._mounts[self._letter]
            info = entry.info_cache.get(file_context["path"])
            if info is None:
                raise NTStatusError(0xC0000034)
            return dict(info)

        @operation
        def read(self, file_context, offset, length):
            node = file_context["node"]
            return _read_range(self._manager._mounts[self._letter].browser,
                               node, offset, length)

        @operation
        def read_directory(self, file_context, marker):
            path = file_context["path"]
            entry = self._manager._mounts[self._letter]
            children = entry.dir_index.get(path, ())
            out = []
            for name, node in children:
                if marker is not None and name <= marker:
                    continue
                child_path = (path.rstrip("/") + "/" + name) if path != "/" \
                    else "/" + name
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

    return FileSystem, TreeOps


class _MountEntry:
    def __init__(self, letter, browser, root_node, path_map, label,
                 total_size, fs_obj, thread):
        self.letter = letter
        self.browser = browser
        self.root_node = root_node
        self.path_map = path_map
        self.label = label
        self.total_size = total_size
        self.fs_obj = fs_obj
        self.thread = thread
        self.stop_event = threading.Event()
        self.start_error = None
        self.dir_index: dict[str, list] = {}
        self.info_cache: dict[str, dict] = {}
        self.open_contexts: set = set()
        self.cache_path: str | None = None


class MountManager:
    """Owns all drive-letter mounts; one daemon thread per mount."""

    def __init__(self):
        self._mounts: dict[str, _MountEntry] = {}
        self._failed_letters: set[str] = set()
        self._lock = threading.Lock()
        atexit.register(self.unmount_all)

    def list_mounts(self) -> list[str]:
        with self._lock:
            return sorted(self._mounts)

    def is_mounted(self, letter: str) -> bool:
        return letter.upper() in self._mounts

    def unmount(self, letter: str) -> bool:
        letter = letter.upper().rstrip(":")
        with self._lock:
            entry = self._mounts.pop(letter, None)
        if entry is None:
            return False
        if entry.stop_event is not None:
            entry.stop_event.set()
        child = getattr(entry, "fs_obj", None)
        if child is not None and hasattr(child, "poll"):
            child.terminate()
            try:
                child.wait(timeout=10)
            except Exception:  # noqa: BLE001
                child.kill()
        if entry.thread is not None:
            entry.thread.join(timeout=10)
        remove_letter(letter)
        if entry.cache_path:
            try:
                os.remove(entry.cache_path)
            except OSError:
                pass
        return True

    def unmount_all(self) -> int:
        count = 0
        for letter in self.list_mounts():
            if self.unmount(letter):
                count += 1
        return count

    def mount_tree(self, browser, root_node, letter: str | None = None,
                   label: str = "", progress=None) -> str:
        """Mount a VfsNode subtree read-only; returns the drive letter.

        letter=None auto-picks the first OS-free candidate from R..Z.
        An explicit letter that exists in the system (a user disk!) is
        refused - this mount can never collide with user storage.
        progress(stage: str) is called at each stage for a status bar.
        """
        def _stage(text: str):
            if progress is not None:
                try:
                    progress(text)
                except Exception:  # noqa: BLE001
                    pass

        if os.name != "nt" or not is_available():
            log.warning("[mount] fallback: WinFsp/winfspy unavailable, "
                        "drive mount refused")
            raise RuntimeError("WinFsp mount unavailable")
        if not is_version_supported():
            log.warning("[mount] fallback: known-bad WinFsp/winfspy combo - "
                        "mount refused")
            raise RuntimeError("WinFsp version not supported")
        _stage("checking drive letters")
        if os.name != "nt" or not is_available():
            log.warning("[mount] fallback: WinFsp/winfspy unavailable, "
                        "drive mount refused")
            raise RuntimeError("WinFsp mount unavailable")
        if not is_version_supported():
            log.warning("[mount] fallback: known-bad WinFsp/winfspy combo - "
                        "mount refused")
            raise RuntimeError("WinFsp version not supported")
        with self._lock:
            if letter is None:
                # Legacy floppy letters cannot be mounted on systems
                # without a floppy drive (OBJECT_PATH_NOT_FOUND) and
                # letters that already failed this session are skipped;
                # both go to the very end of the candidate order.
                candidates = [c for c in free_letters()
                              if c not in self._mounts
                              and c not in self._failed_letters]
                tail = [c for c in candidates if c in "AB"]
                candidates = ([c for c in candidates if c not in "AB"]
                              + tail)
                if not candidates:
                    log.warning("[mount] fallback: no free letter in A..Z "
                                "(all used by the system or busy)")
                    raise RuntimeError("no free drive letter in A..Z")
                letter = candidates[0]
            else:
                letter = letter.upper().rstrip(":")
                if len(letter) != 1 or not letter.isalpha():
                    log.warning("[mount] fallback: bad drive letter %r",
                                letter)
                    raise ValueError(f"bad drive letter: {letter!r}")
                if not is_letter_free(letter):
                    log.warning("[mount] fallback: letter %s: exists in the "
                                "system - refused to touch user storage",
                                letter)
                    raise ValueError(f"drive {letter}: exists in the system")
            if letter in self._mounts:
                log.warning("[mount] fallback: drive %s: busy", letter)
                raise ValueError(f"drive {letter}: busy")
        if root_node is None or not root_node.is_dir:
            log.warning("[mount] fallback: mount needs a directory node")
            raise ValueError("mount needs a directory node with a tree")
        path_map = build_path_map(root_node)
        _stage(f"indexing tree ({len(path_map)} entries)")
        # Prebuilt cache: one pass, then O(children)/O(1) per OS request.
        dir_index: dict[str, list] = {}
        info_cache: dict[str, dict] = {}
        for path_key, node in path_map.items():
            info_cache[path_key] = {
                "file_attributes": _attrs_for(node.is_dir),
                "allocation_size": node.size,
                "file_size": node.size,
                "creation_time": 0,
                "last_access_time": 0,
                "last_write_time": 0,
                "change_time": 0,
                "index_number": 0,
                "hard_links": 1,
            }
            if path_key == "/":
                continue
            parent = path_key.rsplit("/", 1)[0] or "/"
            name = path_key.rsplit("/", 1)[-1]
            dir_index.setdefault(parent, []).append((name, node))
        if len(path_map) <= 1:
            log.warning("[mount] fallback: empty tree (scan without FS walk?)")
            raise ValueError("empty tree: rescan partitions first")

        # Serialize the tree for the isolated child process (mount_host.py):
        # all winfspy/native work happens there; a crash can never take
        # down the GUI, and WinFsp removes the letter with the process.
        dump_path = getattr(browser.src, "_path", None)
        src_obj = browser.src
        seen = 0
        while dump_path is None and seen < 10:
            inner = getattr(src_obj, "source", None)
            if inner is None or inner is src_obj:
                break
            src_obj = inner
            dump_path = getattr(inner, "_path", None)
            seen += 1
        if not dump_path:
            log.warning("[mount] fallback: live-chip sources cannot be "
                        "mounted from a child process yet")
            raise RuntimeError("mount of a live chip is not supported")
        cache_path = os.path.join(
            tempfile.gettempdir(), f"xgecu_mount_{letter}_{os.getpid()}.json")
        serial = {
            "letter": letter,
            "label": label or root_node.name,
            "total_size": root_node.size,
            "dump_path": dump_path,
            "paths": {
                path_key: [node.is_dir, node.size, node.offset]
                for path_key, node in path_map.items()
            },
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(serial, f, ensure_ascii=False)

        host_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "mount_host.py")
        cmd = [sys.executable, "-X", "utf8", host_py, cache_path, letter]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        child = subprocess.Popen(
            cmd, cwd=os.path.dirname(host_py),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=creationflags)
        _stage(f"starting FS host for {letter}:")

        def _watch():
            child.wait()
            if not entry.stop_event.is_set():
                log.warning("[mount] fallback: host for %s: exited "
                            "unexpectedly (code %s)", letter, child.returncode)
                with self._lock:
                    self._mounts.pop(letter, None)
                    self._failed_letters.add(letter)

        entry = _MountEntry(letter, browser, root_node, path_map,
                            label or root_node.name,
                            root_node.size, child, None)
        entry.cache_path = cache_path
        thread = threading.Thread(target=_watch, name=f"mount-watch-{letter}",
                                  daemon=True)
        entry.thread = thread
        with self._lock:
            self._mounts[letter] = entry
        thread.start()
        # fail fast: READY handshake, then the drive must be OS-visible.
        # A pump thread reads child output (readline would block forever
        # on a silent child); its tail is reported on failure.
        ready = False
        start_error = None
        out_buf: list[str] = []
        out_ready = threading.Event()

        def _pump():
            try:
                for line in child.stdout:
                    out_buf.append(line)
                    if "READY" in line:
                        out_ready.set()
                        return
                    if len(out_buf) > 400:
                        del out_buf[:200]
            except Exception:  # noqa: BLE001
                pass

        pump = threading.Thread(target=_pump, name="mount-pump", daemon=True)
        pump.start()
        for i in range(30):
            _stage(f"waiting FS READY on {letter}: ({i + 1}/30 s)")
            if out_ready.is_set():
                ready = True
                break
            if child.poll() is not None:
                start_error = f"host died before READY (code {child.returncode})"
                break
            time.sleep(1)
        if ready:
            try:
                os.stat(letter + ":\\")
            except OSError as exc:
                ready = False
                start_error = str(exc)
        if not ready:
            entry.stop_event.set()
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
            with self._lock:
                self._mounts.pop(letter, None)
                self._failed_letters.add(letter)
            remove_letter(letter)
            try:
                os.remove(cache_path)
            except OSError:
                pass
            tail = "".join(out_buf[-12:]).strip()
            start_error = start_error or "no READY handshake in 30 s"
            if tail:
                start_error += " | child output tail: " + tail[:800]
            log.warning("[mount] fallback: mount %s: failed (%s)",
                        letter, start_error)
            raise RuntimeError(f"mount {letter}: failed: {start_error}")
        log.info("[mount] %s: <- %s (%d entries, read-only, child pid %d)",
                 letter, label or root_node.name, len(path_map), child.pid)
        return letter

    def mount_auto(self, browser, root_node, label: str = "",
                   max_attempts: int = 3, progress=None) -> str:
        """mount_tree with automatic letter retries.

        Some letters (legacy A:/B:, or letters poisoned by earlier failed
        mounts) hang or refuse at fs.start(); this tries up to
        max_attempts OS-free letters in turn and returns the first one
        that actually came up. Every failed attempt is cleaned (child
        killed, DOS device removed) by mount_tree's failure path.
        """
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                if progress is not None and attempt:
                    try:
                        progress(f"letter attempt {attempt + 1}/{max_attempts}")
                    except Exception:  # noqa: BLE001
                        pass
                return self.mount_tree(browser, root_node, None, label,
                                       progress=progress)
            except RuntimeError as exc:
                last_error = exc
                log.warning("[mount] fallback: letter attempt failed, "
                            "trying the next free letter (%s)", exc)
        raise RuntimeError(f"mount failed on all letter attempts: "
                           f"{last_error}")
