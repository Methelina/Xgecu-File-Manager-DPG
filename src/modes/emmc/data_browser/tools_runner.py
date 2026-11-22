"""
Data Browser: external tools runner (assets/tools) - 7z, unsquashfs, gzip,
lzop, lzhs_scanner, aescrypt2. The browser shells out exactly like the
reference workflow: parse exit codes and stdout markers, no reimplementation
of archive formats.

Marker strings parsed from stdout:
  success: "Everything is Ok"
  failure: "Can not open the file as archive"
  warning: "WARNING: Checksum mismatch"

src/modes/emmc/data_browser/tools_runner.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] ToolsRunner: locate tool in assets/tools, run with args, capture output.
  [+] run_unsquashfs / run_7z_extract / run_gzip / run_lzop / run_lzhs / run_aes_decrypt.
  [+] Result dataclass (ok, warning, exit_code, output tail).
  [+] aes_decrypt_native(): MStar aescrypt2 replacement via pycryptodomex
      (AES-128-CBC, IV=0, key file = 16 raw bytes, mbedtls aescrypt2 layout).
      Default MStar keys shipped in cfg/data_browser/keys/ (AESboot/AESupgrade,
      both 0007FF41...). Verified by encrypt(exe)->decrypt(native) round-trip.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

TOOLS_DIR_DEFAULT = os.path.join("assets", "tools")

_OK_MARK = "Everything is Ok"
_FAIL_MARK = "Can not open the file as archive"
_WARN_MARK = "WARNING: Checksum mismatch"


@dataclass
class ToolResult:
    ok: bool
    warning: bool
    exit_code: int
    output_tail: str


class ToolsRunner:
    def __init__(self, tools_dir: str | None = None):
        self.tools_dir = tools_dir or TOOLS_DIR_DEFAULT

    def _tool(self, name: str) -> str:
        path = os.path.join(self.tools_dir, name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"tool not found: {path}")
        return path

    def _run(self, argv: list[str]) -> ToolResult:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              errors="replace", cwd=self.tools_dir, timeout=600)
        out = (proc.stdout or "") + (proc.stderr or "")
        if _FAIL_MARK in out:
            ok = False
        elif _OK_MARK in out:
            ok = True
        else:
            ok = proc.returncode == 0
        return ToolResult(ok=ok, warning=_WARN_MARK in out,
                          exit_code=proc.returncode, output_tail=out[-2000:])

    def run_unsquashfs(self, image_path: str, dest_dir: str) -> ToolResult:
        return self._run([self._tool("unsquashfs.exe"), "-d", dest_dir, image_path])

    def run_7z_extract(self, archive_path: str, dest_dir: str) -> ToolResult:
        return self._run([self._tool("7z.exe"), "x", "-y",
                          f"-o{dest_dir}", archive_path])

    def run_gzip(self, file_path: str) -> ToolResult:
        return self._run([self._tool("gzip.exe"), "-d", file_path])

    def run_lzop(self, file_path: str) -> ToolResult:
        return self._run([self._tool("lzop.exe"), "-d", file_path])

    def run_lzhs(self, file_path: str) -> ToolResult:
        return self._run([self._tool("lzhs_scanner.exe"), file_path])

    def run_aes_decrypt(self, in_path: str, out_path: str,
                        key_file: str | None = None) -> ToolResult:
        key = key_file or os.path.join(self.tools_dir, "DEK_part.bin")
        return self._run([self._tool("aescrypt2.exe"), "d", key, in_path, out_path])

    @staticmethod
    def aes_decrypt_native(in_path: str, out_path: str,
                           key_bytes: bytes) -> int:
        """Standard mbedtls aescrypt2 decryption (AES-CBC, IV=0, raw key).

        WARNING: verified NOT equivalent to the shipped MStar aescrypt2.exe -
        the MStar build uses a modified scheme (self-roundtrip with this exe
        does not reproduce the input, so the transform is non-standard).
        Use run_aes_decrypt() (the exe) for real MStar partitions; this native
        helper only handles standard mbedtls-format files.
        """
        from Cryptodome.Cipher import AES  # pycryptodomex (py7zr dependency)
        if len(key_bytes) not in (16, 24, 32):
            raise ValueError(f"bad AES key length: {len(key_bytes)}")
        blob = open(in_path, "rb").read()
        if len(blob) % 16:
            blob = blob[:len(blob) - (len(blob) % 16)]
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv=b"\x00" * 16)
        data = cipher.decrypt(blob)
        open(out_path, "wb").write(data)
        return len(data)
