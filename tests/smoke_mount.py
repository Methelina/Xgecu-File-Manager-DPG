"""Smoke: Data Browser drive mounting (mount.py).

Unit: path map, letter validation, busy letters, read ranges over a real
fixture build. E2E: mount a real partition of a real dump read-only as a
drive letter, verify file content through the OS against read_node hashes,
unmount cleanly. Hardware-free; dump is opened read-only.

tests/smoke_mount.py
Version:     0.1.3
Author:      Soror L.'.L.'
Updated:     2026-11-26

Patch Notes v0.1.3 (Soror L.'.L.'.):
  [*] Capture the mounted-letter list before asserting the E2E mount result.

Patch Notes v0.1.1 (Soror L.'.L.'.):
  [*] Letter-safety unit updated for the full A..Z auto-pick (no fixed
      interval): free set must not intersect OS-used letters.

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] unit_tests(): VfsNode map, MountManager letter/busy rules, read
      ranges through RangeCache on the FAT16 fixture.
  [+] e2e_tests(dump_path): full-scan a real dump, mount a FS partition
      as a drive letter, OS-level read + hash match via a fresh browser,
      unmount. Skipped with SKIP when WinFsp or the dump is absent.
"""

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_data_browser as base  # noqa: E402
from modes.emmc.data_browser import DataBrowser, FileSource, RangeCache  # noqa: E402
from modes.emmc.data_browser.mount import (  # noqa: E402
    MountManager, build_path_map, is_available,
)

E2E_DUMP = os.environ.get(
    "EMMC_E2E_DUMP",
    r"K:\drop\XgproV1316_T48_T56_T866II_Setup\XgproV1316_Setup"
    r"\UserData\Emmc_data\UserData.BIN")


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {extra}" if extra else ""))
    return bool(cond)


def unit_tests() -> bool:
    ok = True
    # --- path map on a synthetic tree ---
    from modes.emmc.data_browser import VfsNode
    root = VfsNode(name="/")
    part = VfsNode(name="part", size=100)
    folder = VfsNode(name="dir", is_dir=True)
    file1 = VfsNode(name="a.txt", is_dir=False, size=5, offset=100)
    part.children = [folder]
    folder.children = [file1]
    root.children = [part]
    pmap = build_path_map(part)
    ok &= check("path_map: root + dir + file", sorted(pmap) == ["/", "/dir", "/dir/a.txt"],
                sorted(pmap))
    ok &= check("path_map: file node identity", pmap["/dir/a.txt"] is file1)

    # --- letter safety: user disks are never touched ---
    from modes.emmc.data_browser.mount import free_letters, is_letter_free
    ok &= check("letters: C: is not free", not is_letter_free("C:"))
    ok &= check("letters: '1' is not free", not is_letter_free("1"))
    free = free_letters()
    ok &= check("letters: free set within A..Z and OS-free",
                all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" and is_letter_free(c)
                    for c in free), str(free))
    used = sorted(free_letters.__globals__["system_used_letters"]())
    ok &= check("letters: no used letter in free set",
                not (set(free) & set(used)), f"used={used}")
    manager = MountManager()
    # gate bypassed: WinFsp version must not mask the letter-safety logic
    import modes.emmc.data_browser.mount as mount_mod
    real_gate = mount_mod.is_version_supported
    mount_mod.is_version_supported = lambda: True
    try:
        try:
            manager.mount_tree(None, part, "C")
            user_letter = False
        except (ValueError, RuntimeError):
            user_letter = True
        ok &= check("manager: explicit existing letter refused", user_letter)
        try:
            manager.mount_tree(None, part, "1")
            bad_letter = False
        except ValueError:
            bad_letter = True
        ok &= check("manager: bad letter rejected", bad_letter)
        bare = VfsNode(name="empty", is_dir=True)
        try:
            manager.mount_tree(None, bare, None)
            empty_tree = False
        except ValueError:
            empty_tree = True
        ok &= check("manager: empty tree rejected", empty_tree)
        ok &= check("manager: nothing mounted", manager.list_mounts() == [])
        ok &= check("manager: unmount unknown is False", manager.unmount("Q") is False)
    finally:
        mount_mod.is_version_supported = real_gate

    # --- read ranges: zero-copy unit of the FS read path ---
    from modes.emmc.data_browser.mount import _read_range
    src = base.MemSource(bytes(range(256)) * 4)
    browser = DataBrowser(src)
    node = VfsNode(name="f", is_dir=False, size=64, offset=100)
    ok &= check("read_range: head", _read_range(browser, node, 0, 4) == bytes([100, 101, 102, 103]))
    ok &= check("read_range: mid", _read_range(browser, node, 1, 2) == bytes([101, 102]))
    ok &= check("read_range: tail clamp", len(_read_range(browser, node, 60, 10)) == 4)
    ok &= check("read_range: dir empty", _read_range(browser, folder, 0, 8) == b"")
    return ok


def e2e_tests(dump_path: str = E2E_DUMP, letter: str | None = None) -> bool:
    if not os.path.exists(dump_path):
        print(f"[SKIP] dump not found: {dump_path}")
        return True
    if not is_available():
        print("[SKIP] WinFsp/winfspy unavailable")
        return True
    ok = True
    manager = MountManager()
    src = FileSource(dump_path)
    cache = RangeCache(src, chunk_size=16384, max_chunks=1024)
    browser = DataBrowser(cache)
    print(f"[INFO] scanning {dump_path} ({src.size()} bytes)...")
    root, diag = browser.build()
    # whole dump: every scanned partition becomes a folder of one drive
    target = root
    letter = manager.mount_auto(browser, target, "whole dump")
    mounted = manager.list_mounts()
    print(f"[INFO] auto letter: {letter}:")
    ok &= check("e2e: mounted", len(mounted) == 1, str(mounted))
    if not mounted:
        manager.unmount_all()
        src.close()
        return False
    letter = mounted[0]
    drive_root = f"{letter}:\\"
    ok &= check("e2e: drive visible to OS", os.path.exists(drive_root))
    ok &= check("e2e: partitions as folders", len(os.listdir(drive_root)) > 0,
                f"{len(os.listdir(drive_root))} top-level entries")
    # verify a real file inside a nested partition via the OS + hash match
    import hashlib
    verified = 0
    for part in root.children:
        for f in part.walk():
            if f.is_dir or not (64 <= f.size <= 1_000_000):
                continue
            rel = _rel_path(root, f).lstrip("/")
            os_path = os.path.join(drive_root, rel.replace("/", "\\"))
            if not os.path.exists(os_path):
                continue
            with open(os_path, "rb") as fh:
                h_os = hashlib.sha256(fh.read()).hexdigest()
            h_ref = hashlib.sha256(browser.read_node(f)).hexdigest()
            ok &= check(f"e2e: hash match {rel}", h_os == h_ref)
            verified += 1
            break  # one verified file per partition is enough
        if verified >= 2:
            break
    ok &= check("e2e: at least one OS-verified file", verified >= 1,
                f"{verified} verified")
    manager.unmount_all()
    ok &= check("e2e: unmounted", manager.list_mounts() == [])
    src.close()
    return ok


def _rel_path(part, node) -> str:
    """Path of node relative to partition root via parent links (walk order)."""
    # VfsNode has no parent pointers; rebuild the map
    pmap = build_path_map(part)
    for path, candidate in pmap.items():
        if candidate is node:
            return path.lstrip("/")
    return node.name


if __name__ == "__main__":
    print("=== smoke_mount: unit ===")
    u_ok = unit_tests()
    print("=== smoke_mount: e2e on real dump ===")
    e_ok = e2e_tests()
    total = u_ok and e_ok
    print("=== RESULT:", "PASS" if total else "FAIL", "===")
    sys.exit(0 if total else 1)
