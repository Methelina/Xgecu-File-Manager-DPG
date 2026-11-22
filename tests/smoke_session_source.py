"""
Smoke test: data_browser SessionSource (live-chip path) with a mock session.

Covers: chunked reads through session.read_sectors, alignment across chunk
boundaries, STOP via threading.Event (InterruptedError), RangeCache reuse.

Run:
  xgecu_env\Scripts\python.exe -X utf8 tests\smoke_session_source.py

Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] MockSession: sector-addressed fake with patterned content.
  [+] Cases: fragment read, cross-chunk read, STOP mid-range, cache hit.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from modes.emmc.data_browser.sources import RangeCache, SessionSource  # noqa: E402

SECTOR = 512
CHUNK = 32  # sectors per 16 KiB chunk


class MockSession:
    def __init__(self, total_sectors: int, stop_after_reads: int | None = None):
        self.total = total_sectors
        self.stop_after = stop_after_reads
        self.calls = 0

    def read_sectors(self, start_lba: int, n_blocks: int) -> bytes:
        self.calls += 1
        if self.stop_after is not None and self.calls > self.stop_after:
            raise AssertionError("read issued after STOP")
        out = bytearray()
        for i in range(n_blocks):
            lba = start_lba + i
            if lba >= self.total:
                out.extend(b"\x00" * SECTOR)
            else:
                out.extend(bytes([(lba * 7 + j) & 0xFF for j in range(SECTOR)]))
        return bytes(out)


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return cond


def main() -> int:
    ok = True
    session = MockSession(total_sectors=512)
    stop = threading.Event()
    src = SessionSource(session, size_hint=512 * SECTOR, stop_event=stop)

    frag = src.read(0, 64)
    ok &= check("fragment read", len(frag) == 64 and frag[:4] == bytes([(0 * 7 + j) & 0xFF for j in range(4)]))

    cross = src.read(SECTOR * 30, SECTOR * 8)  # spans chunk boundary (sector 32)
    expected = session.read_sectors(30, 8)
    ok &= check("cross-chunk read matches", cross == expected)

    cache = RangeCache(src, chunk_size=16384, max_chunks=8)
    a = cache.read(0, 4096)
    b = cache.read(0, 4096)
    ok &= check("cache repeat", a == b and cache.stats()[0] == 1)

    # STOP: request a range covering several chunks, set event after first read
    src2 = SessionSource(MockSession(total_sectors=512), size_hint=512 * SECTOR,
                         stop_event=stop)
    src2.read(0, 512)  # warm-up read before STOP
    stop.set()
    try:
        src2.read(SECTOR * 64, SECTOR * 64)
        ok &= check("STOP interrupts", False, "no exception raised")
    except InterruptedError:
        ok &= check("STOP interrupts", True)
    stop.clear()

    print("=== RESULT:", "PASS" if ok else "FAIL", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
