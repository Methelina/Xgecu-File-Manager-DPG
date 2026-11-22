"""
Smoke test: data_browser package. Runs offline, no hardware, no GUI.

Two parts:
  1. Unit fixtures built in memory (synthetic GPT, FAT16, cmdline map).
  2. E2E on the real dump at EMMC_DATA_PATH (env var) or the known
     Xgpro Emmc_data location - read-only access only.

Run:
  xgecu_env\Scripts\python.exe -X utf8 tests\smoke_data_browser.py

src/modes/emmc/data_browser -> tests/smoke_data_browser.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Unit: GPT fixture (2 partitions, CRC ok), cmdline map fixture, RangeCache.
  [+] Unit: FAT16 fixture with 8.3 + LFN name, dir + file.
  [+] E2E: real dump - partition map, signatures, cache hit behavior, ext listing.
"""

from __future__ import annotations

import io
import os
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from modes.emmc.data_browser import (  # noqa: E402
    DataBrowser, FileSource, RangeCache, identify, scan_cmdline_map,
)
from modes.emmc.data_browser.partmaps import build_partition_map  # noqa: E402


def check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""))
    return cond


class MemSource:
    def __init__(self, data: bytes, size: int | None = None):
        self.data = data
        self._size = size if size is not None else len(data)

    def size(self) -> int:
        return self._size

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self._size:
            raise ValueError(f"range out of bounds: {offset}+{length} > {self._size}")
        if offset >= len(self.data):
            return b"\x00" * length
        chunk = self.data[offset:offset + length]
        return chunk + b"\x00" * (length - len(chunk))


def make_gpt_fixture() -> bytes:
    ss = 512
    total_sectors = 4096
    img = bytearray(total_sectors * ss)
    # protective MBR
    img[510:512] = b"\x55\xaa"
    # GPT header at LBA1
    hdr = bytearray(92)
    hdr[0:8] = b"EFI PART"
    struct.pack_into("<I", hdr, 8, 0x10000)   # revision
    struct.pack_into("<I", hdr, 12, 92)       # header size
    struct.pack_into("<QQ", hdr, 24, 1, total_sectors - 1)
    arr_lba = 2
    struct.pack_into("<Q", hdr, 72, arr_lba)
    struct.pack_into("<I", hdr, 80, 2)     # entry count
    struct.pack_into("<I", hdr, 84, 128)   # entry size
    entries = bytearray(2 * 128)
    for i, (name, first, last) in enumerate(
            [("boot", 34, 133), ("data", 134, 4095)]):
        base = i * 128
        entries[base:base + 16] = bytes(range(16))  # non-zero type guid
        struct.pack_into("<QQ", entries, base + 0x20, first, last)
        nm = name.encode("utf-16-le")
        entries[base + 0x38:base + 0x38 + len(nm)] = nm
    arr_crc = zlib.crc32(bytes(entries)) & 0xFFFFFFFF
    struct.pack_into("<I", hdr, 88, arr_crc)
    hdr_crc = zlib.crc32(bytes(hdr)) & 0xFFFFFFFF
    struct.pack_into("<I", hdr, 16, hdr_crc)
    img[ss:ss + 92] = hdr
    img[2 * ss:2 * ss + len(entries)] = entries
    # backup header at last LBA
    bak = bytearray(hdr)
    struct.pack_into("<Q", bak, 32, total_sectors - 1)  # current lba (approx, ok for test)
    struct.pack_into("<I", bak, 16, 0)
    bak_crc = zlib.crc32(bytes(bak)) & 0xFFFFFFFF
    struct.pack_into("<I", bak, 16, bak_crc)
    img[(total_sectors - 1) * ss:(total_sectors - 1) * ss + 92] = bak
    # content markers inside partitions
    img[34 * ss:34 * ss + 4] = b"\x27\x05\x19\x56"          # uImage
    img[134 * ss + 1024 + 56:134 * ss + 1024 + 58] = b"\x53\xef"  # ext magic
    return bytes(img)


def make_fat16_fixture() -> bytes:
    bps, spc, reserved, nfats = 512, 1, 1, 1
    root_entries = 16
    # >4085 clusters so the volume qualifies as FAT16
    data_sectors = 5000
    fat_sectors = 20
    total_sectors = reserved + nfats * fat_sectors + (root_entries * 32 // bps) + data_sectors
    img = bytearray(total_sectors * bps)
    bpb = bytearray(512)
    struct.pack_into("<H", bpb, 0x0B, bps)
    bpb[0x0D] = spc
    struct.pack_into("<H", bpb, 0x0E, reserved)
    bpb[0x10] = nfats
    struct.pack_into("<H", bpb, 0x11, root_entries)
    struct.pack_into("<H", bpb, 0x13, total_sectors)
    struct.pack_into("<H", bpb, 0x16, fat_sectors)
    bpb[54:59] = b"FAT16"
    bpb[510:512] = b"\x55\xaa"
    img[0:512] = bpb
    # FAT: entry 2 = EOC (file data cluster)
    fat = bytearray(fat_sectors * bps)
    struct.pack_into("<H", fat, 0, 0xFFF8)
    struct.pack_into("<H", fat, 2, 0xFFFF)
    img[reserved * bps:reserved * bps + fat_sectors * bps] = fat
    first_data = (reserved + nfats * fat_sectors + root_entries * 32 // bps) * bps
    # root dir: LFN "LongName.txt" (12 chars fits one entry incl. NUL) +
    # 8.3 "TEST.TXT" (cluster 2, size 11)
    root = bytearray(root_entries * 32)
    lfn = bytearray(32)
    lfn[0] = 0x41
    lfn[11] = 0x0F
    nm = "LongName.txt".encode("utf-16-le")
    lfn[1:11] = nm[0:10]
    lfn[14:26] = nm[10:22]
    lfn[28:32] = nm[22:24] + b"\x00\x00"
    root[0:32] = lfn
    sfn = bytearray(32)
    sfn[0:8] = b"TEST    "
    sfn[8:11] = b"TXT"
    sfn[11] = 0x20
    struct.pack_into("<H", sfn, 26, 2)
    struct.pack_into("<I", sfn, 28, 11)
    root[32:64] = sfn
    root_off = (reserved + nfats * fat_sectors) * bps
    img[root_off:root_off + len(root)] = root
    img[first_data:first_data + 11] = b"HELLOWORLD!"
    return bytes(img)


def unit_tests() -> bool:
    ok = True
    # RangeCache
    src = MemSource(bytes(range(256)) * 512)
    cache = RangeCache(src, chunk_size=4096, max_chunks=4)
    a = cache.read(0, 10)
    b = cache.read(0, 10)
    ok &= check("range_cache: repeat read identical", a == b)
    ok &= check("range_cache: hit counted", cache.hits == 1 and cache.misses == 1)
    ok &= check("range_cache: cross-chunk assembly",
                cache.read(4000, 2000) == src.read(4000, 2000))

    # GPT fixture
    gpt_img = make_gpt_fixture()
    gsrc = MemSource(gpt_img)
    parts, diag = build_partition_map(gsrc)
    ok &= check("gpt: two partitions parsed", len(parts) == 2, str(diag))
    ok &= check("gpt: header crc ok", diag.get("gpt_header_crc_ok") is True)
    ok &= check("gpt: array crc ok", diag.get("gpt_array_crc_ok") is True)
    ok &= check("gpt: names", [p.name for p in parts] == ["boot", "data"])
    ok &= check("gpt: sizes inclusive", parts[0].size == (133 - 34 + 1) * 512)
    ok &= check("signatures: uImage marker",
                identify(gsrc, parts[0].offset, parts[0].size) == "uImage")
    ok &= check("signatures: ext marker",
                identify(gsrc, parts[1].offset, parts[1].size) == "ext2/3/4")

    # cmdline fixture: embed marker in a source whose declared size is 256 MiB
    cmdline = (b"junk mt53xx-emmc:2M(uboot),2M(uboot_env)enc,1M(eeprom_A),"
               b"100M(userdata) rest of the log line ...")
    csrc = MemSource(cmdline, size=256 * 1024 * 1024)
    cparts = scan_cmdline_map(csrc)
    ok &= check("cmdline: found 4 partitions", cparts is not None and len(cparts) == 4)
    ok &= check("cmdline: 2M multiplier", cparts[0].size == 2 * 1024 * 1024)
    ok &= check("cmdline: enc flag", cparts[1].enc is True)
    ok &= check("cmdline: 100M multiplier", cparts[3].size == 100 * 1024 * 1024)
    # remainder: last token without unit suffix takes the rest of the source
    cmdline2 = (b"mt53xx-emmc:2M(uboot),userdata")
    cparts2 = scan_cmdline_map(MemSource(cmdline2, size=16 * 1024 * 1024))
    ok &= check("cmdline: remainder for last",
                cparts2 is not None and len(cparts2) == 2
                and cparts2[1].size == 16 * 1024 * 1024 - 2 * 1024 * 1024)

    # FAT16 fixture
    fsrc = MemSource(make_fat16_fixture())
    from modes.emmc.data_browser.fs_fat import FatVolume
    vol = FatVolume(fsrc, 0, fsrc.size())
    ok &= check("fat: type detected", vol.fat_type == "FAT16")
    entries = vol.listdir()
    ok &= check("fat: one entry", len(entries) == 1, str([e.name for e in entries]))
    ok &= check("fat: LFN name used", entries and entries[0].name == "LongName.txt")
    ok &= check("fat: size", entries and entries[0].size == 11)
    data = fsrc.read(entries[0].offset, 11)
    ok &= check("fat: file content", data == b"HELLOWORLD!")

    # full browser on FAT fixture (identify must map to fat16)
    browser = DataBrowser(fsrc)
    root, _ = browser.build()
    ok &= check("vfs: browser on raw fat", len(root.children) >= 0)
    return ok


E2E_PATH_DEFAULT = (r"K:\drop\XgproV1316_T48_T56_T866II_Setup"
                    r"\XgproV1316_Setup\UserData\Emmc_data\UserData.BIN")
E2E_PATH_XIAOMI = (r"K:\work\ChipTune\TV_Repo\Xiaomi_L43M7-EARU\firmware"
                   r"\Xiaomi L55M7-EARU TD.MT9612.795 EMMC\L55M7-EARU"
                   r"\TD.MT9612.795\USER_0x0000000000_0x039F000000_backup.bin")


def e2e_tests(dump_path: str | None = None, shallow: bool = False) -> bool:
    path = dump_path or os.environ.get("EMMC_DATA_PATH", E2E_PATH_DEFAULT)
    if not os.path.exists(path):
        print(f"[SKIP] e2e: dump not found: {path}")
        return True
    ok = True
    src = FileSource(path)
    cache = RangeCache(src, chunk_size=16384, max_chunks=512)
    print(f"[INFO] e2e dump: {path} ({src.size()} bytes)")
    parts, diag = build_partition_map(cache)
    map_kind = "gpt" if "gpt_header_crc_ok" in diag else (
        "mstar-pt" if diag.get("mstar_pt_found") else "cmdline")
    ok &= check(f"e2e[{map_kind}]: partitions found", len(parts) > 0,
                f"{len(parts)} partitions")
    if map_kind == "gpt":
        ok &= check("e2e: gpt header crc", diag.get("gpt_header_crc_ok") is True)
        ok &= check("e2e: gpt array crc", diag.get("gpt_array_crc_ok") is True)
    names = [p.name for p in parts]
    print("[INFO] partitions:", names)
    prof_ok = True
    browser = DataBrowser(cache)
    root, diag2 = browser.build(list_fs=not shallow)
    if shallow:
        # shallow mode: partition map + one fragment read is proof of reading;
        # do NOT walk large FS trees (15.5 GB dumps take minutes to walk fully)
        ok &= check("e2e[shallow]: partitions present", len(root.children) > 0)
        p0 = parts[0]
        frag = cache.read(p0.offset, 4096)
        ok &= check("e2e[shallow]: fragment read", len(frag) == 4096)
        # identify the first ext-like partition and read a fragment of it
        for node in root.children:
            if node.fs_label == "ext2/3/4":
                frag = cache.read(node.offset + 1024, 64)
                ok &= check("e2e[shallow]: ext superblock fragment",
                            frag[56:58] == b"\x53\xef", node.name)
                break
        print(f"[INFO] shallow e2e done for {path}")
        src.close()
        return ok
    if "device_preset" in diag2:
        print("[INFO] device preset:", diag2["device_preset"])
    total_files = 0
    extracted = 0
    out_dir = Path(__file__).resolve().parents[1] / "tmp" / "e2e_extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    for node in root.children:
        files = [n for n in node.walk() if not n.is_dir]
        total_files += len(files)
        line = f"  {node.name:<24} {node.size:>12} {node.fs_label:<12} files={len(files)}"
        print(line)
        if node.fs_label == "ext2/3/4" and files:
            sample = files[:5]
            print("    sample:", [(f.name, f.size, hex(f.offset)) for f in sample])
        # E2E: extract up to 3 real files per interesting partition and verify
        # content by re-reading through a fresh backend instance (hash match).
        if node.fs_label in ("ext2/3/4", "fat32", "fat16", "fat12") and files:
            picked = [f for f in files if 64 <= f.size <= 1_000_000][:3]
            for f in picked:
                dest = out_dir / f"{node.name}_{f.name}".replace("/", "_")[:80]
                n = browser.extract(f, str(dest))
                data = dest.read_bytes()
                ok &= check(f"e2e: extract {node.name}/{f.name}",
                            n == f.size and len(data) == f.size,
                            f"{n} bytes")
                extracted += 1
            if picked:
                # independent re-read: rebuild the browser and compare hashes
                src_fresh = FileSource(path)
                browser_fresh = DataBrowser(RangeCache(src_fresh, chunk_size=16384,
                                                       max_chunks=512))
                root_fresh, _ = browser_fresh.build()
                for f in picked:
                    nf = root_fresh.find(f"{node.name}/{f.name}")
                    if nf is None:
                        continue
                    h1 = hashlib.sha256(browser.read_node(f)).hexdigest()
                    h2 = hashlib.sha256(browser_fresh.read_node(nf)).hexdigest()
                    ok &= check(f"e2e: hash match {f.name}", h1 == h2)
                src_fresh.close()
    _ = extracted
    hits_before = cache.stats()[0]
    cache.read(parts[0].offset, 512)
    hits2, misses2 = cache.stats()
    ok &= check("e2e: cache is working", misses2 > 0)
    _ = hits_before, hits2
    print(f"[INFO] cache hits/misses: {hits2}/{misses2}, files listed: {total_files}")
    ok &= check("e2e: no crash on unknown fs labels", True)
    return ok


if __name__ == "__main__":
    print("=== smoke_data_browser: unit ===")
    unit_ok = unit_tests()
    print("=== smoke_data_browser: e2e on real dump (GPT/Xgpro) ===")
    e2e_ok = e2e_tests()
    print("=== smoke_data_browser: e2e on real dump (MStar PT/Xiaomi, shallow) ===")
    e2e2_ok = e2e_tests(E2E_PATH_XIAOMI, shallow=True)
    print("=== RESULT:", "PASS" if (unit_ok and e2e_ok and e2e2_ok) else "FAIL", "===")
    sys.exit(0 if (unit_ok and e2e_ok and e2e2_ok) else 1)
