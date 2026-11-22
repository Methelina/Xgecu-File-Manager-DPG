"""
Data Browser: pluggable JSON profiles. Signatures, reference device partition
maps (MStar/LG/Samsung/...), filesystem parameters live in cfg/data_browser/
and extend functionality without code changes.

Schemas (all keys optional; code defaults apply):
  signatures.json: {"signatures": [{"magic": "hsqs", "offset": 0, "label": "squashfs"}, ...]}
  partition_presets.json: {"presets": [{"device": "...", "partition_names": [...], ...}]}
  fs_params.json: {"vdfs": {...}, "fat": {...}}

src/modes/emmc/data_browser/profiles.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Profiles: JSON loading from cfg/data_browser with fallback to code defaults.
  [+] Signature matcher driven by profile (magic/offset/label, hex strings "53 EF").
  [+] Preset matcher: match dump partition list against reference device maps.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

PROFILE_DIR_DEFAULT = os.path.join("cfg", "data_browser")


def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        # fallback: a broken/unreadable profile must not crash the browser
        print(f"[data_browser] fallback: profile {path} not loaded ({exc}), using defaults")
        return {}


@dataclass(frozen=True)
class SignatureRule:
    magic: bytes
    offset: int
    label: str


def _parse_magic(spec: str) -> bytes:
    """'hsqs' - ASCII; '53 EF' / '0x53EF' - hex."""
    if spec.startswith("0x"):
        return bytes.fromhex(spec[2:])
    if all(c in "0123456789abcdefABCDEF " for c in spec) and " " in spec:
        return bytes.fromhex(spec.replace(" ", ""))
    return spec.encode("ascii")


class Profiles:
    """Single loading point for profiles. Reload = new instance."""

    def __init__(self, profile_dir: str | None = None):
        self.dir = profile_dir or PROFILE_DIR_DEFAULT
        sig_doc = _load_json(os.path.join(self.dir, "signatures.json"))
        self.signatures: tuple[SignatureRule, ...] = tuple(
            SignatureRule(
                magic=_parse_magic(rule["magic"]),
                offset=int(rule.get("offset", 0)),
                label=rule["label"],
            )
            for rule in sig_doc.get("signatures", [])
        ) or DEFAULT_SIGNATURES
        self.presets: list[dict] = _load_json(
            os.path.join(self.dir, "partition_presets.json")).get("presets", [])
        self.fs_params: dict = _load_json(os.path.join(self.dir, "fs_params.json"))
        ft_doc = _load_json(os.path.join(self.dir, "file_types.json"))
        self.known_extensions: frozenset[str] = frozenset(
            ft_doc.get("known_extensions",
                       [".txt", ".xml", ".json", ".png", ".jpg", ".gif", ".bmp",
                        ".mp3", ".wav", ".bin", ".cfg", ".conf", ".sh", ".so",
                        ".db", ".dat", ".log", ".list", ".img", ".tar", ".xz"]))

    def is_known_extension(self, filename: str) -> bool:
        """True when the file extension is in the known-types whitelist."""
        low = filename.lower()
        return any(low.endswith(ext.lower()) for ext in self.known_extensions)

    def identify(self, head: bytes) -> str:
        """First matching profile signature; 'unknown' when none match."""
        for rule in self.signatures:
            end = rule.offset + len(rule.magic)
            if end <= len(head) and head[rule.offset:end] == rule.magic:
                return rule.label
        return "unknown"

    def match_preset(self, names: list[str]) -> dict | None:
        """Reference device map whose name list best matches the dump."""
        best: tuple[float, dict] | None = None
        names_set = set(names)
        for preset in self.presets:
            expected = set(preset.get("partition_names", []))
            if not expected:
                continue
            ratio = len(names_set & expected) / max(1, len(expected))
            if best is None or ratio > best[0]:
                best = (ratio, preset)
        if best and best[0] >= 0.5:
            return best[1]
        return None


# Code-level default: used when signatures.json is absent (core magic table).
DEFAULT_SIGNATURES: tuple[SignatureRule, ...] = tuple(
    SignatureRule(magic=m, offset=o, label=l) for m, o, l in (
        (b"hsqs", 0, "squashfs"), (b"sqsh", 0, "squashfs"),
        (b"\x27\x05\x19\x56", 0, "uImage"),
        (b"ANDROID!", 0, "android-boot"),
        (b"MZ", 0, "mz"),
        (b"\x1f\x8b", 0, "gzip"),
        (b"UBI#", 0, "ubi"), (b"UBI!", 0, "ubi"),
        (b"NFSB", 0, "nfsb"),
        (b"LZHS", 0, "lzhs"),
        (b"X935", 0, "X935"), (b"P935", 0, "P935"),
        (b"VDFS2006", 0, "vdfs"), (b"VDFS2007", 0, "vdfs"),
        (b"VDFS1002", 0, "vdfs"), (b"VDFS0001", 0, "vdfs"),
        (b"1eMMCFS", 0, "vdfs"),
    )
)
