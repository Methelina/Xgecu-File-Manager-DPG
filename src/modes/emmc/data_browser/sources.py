"""
Data Browser: dump/device reading as partitions and files. Source layer.

Core without GUI: DataSource - range reading abstraction (file-backed dump now,
T48 session later), RangeCache - LRU cache of aligned chunks over a source.

src/modes/emmc/data_browser/sources.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] FileSource: range reading from a dump file.
  [+] RangeCache: LRU cache of aligned 16 KiB chunks, arbitrary range assembly.
  [+] DataSource protocol for future T48 session binding.
  [+] SessionSource: live-chip reading through session.read_sectors (aligned
      16 KiB chunks), stop_event checked before each chunk; dump stays on disk.
  [+] ProgressSource: DataSource wrapper counting bytes read (0..1 progress
      fraction via progress(frac) callback) for GUI progress bars.

Safety policy (firmware dump immutability):
  - dumps are opened read-only ("rb") and never written back;
  - extracted files go to a dedicated output directory, never into the dump;
  - any future write/replace feature must operate on a working COPY of the
    dump, with a fresh backup taken before the first modification.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Protocol


class DataSource(Protocol):
    def size(self) -> int: ...
    def read(self, offset: int, length: int) -> bytes: ...


class FileSource:
    """Range reads from a dump file. Stream stays open for the object lifetime."""

    def __init__(self, path: str):
        self._path = path
        self._f = open(path, "rb")
        self._f.seek(0, 2)
        self._size = self._f.tell()

    def size(self) -> int:
        return self._size

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self._size:
            raise ValueError(f"range out of bounds: {offset}+{length} > {self._size}")
        self._f.seek(offset)
        data = self._f.read(length)
        if len(data) != length:
            raise IOError(f"short read at {offset}: {len(data)}/{length}")
        return data

    def close(self) -> None:
        self._f.close()


class SessionSource:
    """Live eMMC reading via session.read_sectors (aligned chunk engine).

    size_hint must be provided (from EXT_CSD SEC_COUNT * 512 by the caller).
    stop_event (threading.Event) is checked before every chunk read so STOP
    from the GUI interrupts a browse operation; chunk cache upstream reduces
    chip traffic. Alignment: read_sectors already handles chunk alignment.
    """

    CHUNK_SECTORS = 32  # 16 KiB, matches P.CHUNK_SECTORS

    def __init__(self, session, size_hint: int, stop_event=None, sector_size: int = 512):
        self.session = session
        self._size = size_hint
        self.stop_event = stop_event
        self.sector_size = sector_size
        self.reads = 0

    def size(self) -> int:
        return self._size

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self._size:
            raise ValueError(f"range out of bounds: {offset}+{length} > {self._size}")
        if self.stop_event is not None and self.stop_event.is_set():
            raise InterruptedError("STOP requested")
        sectors_per_chunk = self.CHUNK_SECTORS
        parts: list[bytes] = []
        pos = offset
        end = offset + length
        while pos < end:
            if self.stop_event is not None and self.stop_event.is_set():
                raise InterruptedError("STOP requested")
            lba = pos // self.sector_size
            # stay within chunk-aligned 16 KiB window
            block = lba // sectors_per_chunk
            take_sectors = min(sectors_per_chunk - (lba % sectors_per_chunk),
                               (end - pos + self.sector_size - 1) // self.sector_size)
            data = self.session.read_sectors(lba, take_sectors)
            self.reads += 1
            start = pos - lba * self.sector_size
            need = min(len(data) - start, end - pos)
            parts.append(data[start:start + need])
            pos += need
        return b"".join(parts)


class ProgressSource:
    """DataSource wrapper reporting read progress as a 0..1 fraction.

    Sits between the FS backends and the real cache: every read() adds to the
    counter and fires progress(frac) (throttling is the callback's job).
    Also cooperatively yields the GIL periodically: the FS tree walk is
    pure-Python and would otherwise starve the GUI render loop.
    """

    def __init__(self, source: DataSource, progress=None):
        import time
        self._time = time
        self.source = source
        self._progress = progress
        self.bytes_read = 0
        self.reads = 0
        self._last_frac = -1.0

    def size(self) -> int:
        return self.source.size()

    def read(self, offset: int, length: int) -> bytes:
        data = self.source.read(offset, length)
        self.bytes_read += length
        self.reads += 1
        if self.reads % 64 == 0:
            self._time.sleep(0.001)  # yield GIL so the GUI keeps painting
        if self._progress is not None:
            frac = self.bytes_read / max(1, self.source.size())
            if frac - self._last_frac >= 0.02 or frac >= 1.0:
                self._last_frac = frac
                self._progress(frac)
        return data


class RangeCache:
    """LRU cache of aligned chunks over a DataSource.

    chunk_size defaults to 16384 (T48 port: 32 sectors). read() assembles any
    range from cached aligned chunks; repeated reads of the same areas do not
    hit the underlying source.
    """

    def __init__(self, source: DataSource, chunk_size: int = 16384, max_chunks: int = 256):
        self.source = source
        self.chunk_size = chunk_size
        self.max_chunks = max_chunks
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def size(self) -> int:
        return self.source.size()

    def _chunk(self, index: int) -> bytes:
        if index in self._cache:
            self._cache.move_to_end(index)
            self.hits += 1
            return self._cache[index]
        self.misses += 1
        offset = index * self.chunk_size
        length = min(self.chunk_size, self.source.size() - offset)
        if length <= 0:
            raise ValueError(f"chunk {index} beyond end")
        data = self.source.read(offset, length)
        self._cache[index] = data
        while len(self._cache) > self.max_chunks:
            self._cache.popitem(last=False)
        return data

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.source.size():
            raise ValueError(f"range out of bounds: {offset}+{length}")
        parts: list[bytes] = []
        pos = offset
        end = offset + length
        while pos < end:
            index = pos // self.chunk_size
            chunk = self._chunk(index)
            start = pos - index * self.chunk_size
            take = min(len(chunk) - start, end - pos)
            parts.append(chunk[start:start + take])
            pos += take
        return b"".join(parts)

    def clear(self) -> None:
        self._cache.clear()

    def stats(self) -> tuple[int, int]:
        return self.hits, self.misses
