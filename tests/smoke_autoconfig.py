import sys, pathlib
from pathlib import Path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
"""Read-only auto detection: selection, fallback, identity, STOP and GUI."""
from types import SimpleNamespace
from threading import Event
from modes.emmc.autoconfig import detect
from modes.emmc import protocol as P


class FakeSession:
    def __init__(self, mode="ok"):
        self.preset, self.clock_mhz, self.legacy_30 = "Авто", 30, False
        self.dev = SimpleNamespace(stop_event=Event(), power_off=lambda: None)
        self.mode = mode
        self.attempts = []
        self.logs = []
        self.log = self.logs.append
        self._reference_done = False
    def init_hw(self, voltage, width):
        self.attempts.append((self.preset, self.clock_mhz, self.legacy_30))
        if self.mode == "cancel":
            self.dev.stop_event.set()
            raise RuntimeError("cancel")
        if self.mode == "none":
            raise RuntimeError("init failed")
        # First probe is always standard 8 (reference) - allow it to succeed
        if not self._reference_done and self.preset == "стандартный" and self.clock_mhz == 8:
            self._reference_done = True
            return
        # After reference, apply mode-specific failures
        # For is_18v=True: candidates = THGA 30, standard 30, standard 20, standard 8
        # For is_18v=False: candidates = standard 20, standard 8
        if self.mode == "ok" and self.preset == "THGA" and self.clock_mhz == 30:
            return  # THGA 30 succeeds for "ok"
        if self.mode == "standard" and self.preset == "стандартный" and self.clock_mhz == 30:
            return  # standard 30 succeeds for "standard"
        if self.mode == "fallback" and self.preset == "стандартный" and self.clock_mhz == 20:
            return  # standard 20 succeeds for "fallback"
        if self.mode == "dirty" and self.preset == "стандартный" and self.clock_mhz == 8:
            return  # standard 8 succeeds for "dirty"
        if self.mode == "identity" and self.preset == "стандартный" and self.clock_mhz == 8:
            return  # standard 8 succeeds for "identity"
        # For is_18v=False case (standard 20, standard 8)
        if self.mode == "ok" and self.preset == "стандартный" and self.clock_mhz == 20:
            return  # standard 20 succeeds for "ok" when is_18v=False
        # All other cases fail
        raise RuntimeError("init failed")
    def wake_registers(self, width):
        ext = bytearray(512)
        ext[212:216] = (4096).to_bytes(4, "little")
        cid = b"other" if self.mode == "identity" and self.clock_mhz > 8 else b"cid"
        return cid, b"csd", bytes(ext)
    def select_user(self): pass
    def read_sectors(self, lba, sectors):
        if self.mode == "dirty" and self.clock_mhz > 8:
            return b"b" * (sectors * P.SECTOR_SIZE)
        return b"a" * (sectors * P.SECTOR_SIZE)
    def read_single_sector(self, lba):
        if self.mode == "dirty" and self.clock_mhz > 8:
            return b"b" * P.SECTOR_SIZE
        return b"a" * P.SECTOR_SIZE


for mode, expected in (
        ("ok", ("THGA", 30, True)),
        ("standard", ("стандартный", 30, False)),
        ("fallback", ("стандартный", 20, False)),
        ("dirty", ("стандартный", 8, False)),
        ("identity", ("стандартный", 8, False))):
    s = FakeSession(mode)
    detect(s, True, "4-bit")
    assert (s.preset, s.clock_mhz, s.legacy_30) == expected, (mode, s.attempts)
s = FakeSession()
detect(s, False, "4-bit")
assert s.clock_mhz == 20 and all(clock != 30 for _, clock, _ in s.attempts)
for mode in ("none", "cancel"):
    s = FakeSession(mode)
    try:
        detect(s, True, "4-bit")
    except RuntimeError:
        pass
    else:
        raise AssertionError(mode)
    assert s.preset == "Авто"
    if mode == "cancel":
        assert len(s.attempts) == 1
print("PASS: auto mode ranking, fallback, data/identity mismatch, voltage and STOP")

# DPG GUI autoconfig tests
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gui_dpg import DpgGui
from modes.emmc import protocol as P
from strings import S as st

gui = DpgGui()
dpg = gui.dpg
dpg.create_context()
gui.build()

# Test default preset is "Auto"
assert P.DEFAULT_PRESET == "Авто"
assert gui.emmc_preset_display == "Auto"
assert dpg.get_value("combo_preset") == st("preset_auto")
assert not dpg.get_item_configuration("combo_clock")["enabled"]

# Test setting preset to THGA
gui.on_preset_changed(None, "THGA")
assert gui.emmc_preset_display == "THGA"
assert dpg.get_value("combo_preset") == "THGA"
assert dpg.get_item_configuration("combo_clock")["enabled"]

# Test setting preset to standard
gui.on_preset_changed(None, st("preset_standard"))
assert gui.emmc_preset_display == "standard"
assert dpg.get_value("combo_preset") == st("preset_standard")
assert dpg.get_item_configuration("combo_clock")["enabled"]

# Test setting preset to Auto
gui.on_preset_changed(None, st("preset_auto"))
assert gui.emmc_preset_display == "Auto"
assert dpg.get_value("combo_preset") == st("preset_auto")
assert not dpg.get_item_configuration("combo_clock")["enabled"]

dpg.destroy_context()
print("PASS: auto preset GUI, disabled manual frequency and independent manual settings")
