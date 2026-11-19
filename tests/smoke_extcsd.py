import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
"""Offline checks for EXT_CSD inspection; no USB device is opened."""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_root = Path(__file__).resolve().parents[1]
for path in ("src/gui_dpg.py", "src/orchestrator.py", "src/modes/emmc_mode.py",
             "src/modes/emmc/operations.py", "src/modes/emmc/extcsd.py"):
    ast.parse((_root / path).read_text(encoding="utf-8-sig"))

from modes.emmc.extcsd import validate, describe, compare, load_file

data = bytearray(512)
data[192] = 8
data[212:216] = (122142720).to_bytes(4, "little")
data[226] = 32
assert "MMC 5.1" in describe(data)
assert "122142720" in describe(data)
other = bytearray(data)
other[179] = 72
assert "[179] PARTITION_CONFIG: 00 → 48" in compare(data, other)
assert "0 из 512" in compare(data, data)
for invalid in (b"", bytes(511), bytes(513)):
    try:
        validate(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid size accepted")

from modes.emmc import operations


class FakeSession:
    closed = False

    def __init__(self, *args):
        pass

    def open(self):
        return True

    def init_hw(self, *args):
        pass

    def wake_registers(self, *args):
        return b"cid", b"csd", bytes(data)

    def close(self):
        FakeSession.closed = True


with patch.object(operations, "EmmcSession", FakeSession):
    assert operations.read_extcsd(lambda m: None, True, "4-bit") == (bytes(data), b"cid")
    assert FakeSession.closed
    assert operations.read_extcsd(lambda m: None, True, "4-bit", lambda: True) is None
    FakeSession.closed = False
    with patch.object(FakeSession, "wake_registers", side_effect=RuntimeError("test")):
        try:
            operations.read_extcsd(lambda m: None, True, "4-bit")
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected read failure")
    assert FakeSession.closed

# DPG GUI EXT_CSD tests
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gui_dpg import DpgGui

gui = DpgGui()
dpg = gui.dpg
dpg.create_context()
gui.build()

# Create orchestrator for tests that need it
from orchestrator import AppOrchestrator
gui.orchestrator = AppOrchestrator(
    log_cb=gui.log_cb, table_cb=gui.table_cb, task_cb=gui.task_cb,
    progress_cb=gui.progress_cb, phase_cb=gui.phase_cb)

# Test EXT_CSD table rows exist
assert dpg.does_item_exist("ext_field_177")
assert dpg.does_item_exist("ext_field_178")
assert dpg.does_item_exist("ext_field_179")
assert dpg.does_item_exist("ext_field_162")
assert dpg.does_item_exist("ext_field_160")

# Test _show_extcsd populates values
data = bytearray(512)
data[177] = 0x02
data[178] = 0x00
data[179] = 0x48
data[162] = 0x01
data[160] = 0x07
data[192] = 8  # EXT_CSD_REV for validate_write
cid = b"\x07\x00" + bytes(30)

gui._show_extcsd(bytes(data), "test", cid)
assert gui.extcsd_ready
assert gui.extcsd_chip_ready
assert gui.extcsd_chip_cid == cid

# Check chip values are populated
for index in (177, 178, 179, 162, 160):
    assert dpg.get_value(f"ext_chip_{index}") == f"{data[index]:02X}"

# Test select_extcsd_field
gui.select_extcsd_field(177)
assert gui.extcsd_selected_field == 177
assert dpg.get_value("ext_new_177") == "02"

# Test field 160 is read-only (disabled)
assert not dpg.get_item_configuration("ext_new_160")["enabled"]
assert not dpg.get_item_configuration("ext_write_160")["enabled"]

# Test write buttons enabled for chip-ready fields
print(f"DEBUG: extcsd_chip_ready={gui.extcsd_chip_ready}, operation_running={gui.operation_running}, selected_field={gui.extcsd_selected_field}")
for index in (177, 178, 179, 162):
    enabled = dpg.get_item_configuration(f"ext_write_{index}")["enabled"]
    print(f"DEBUG: ext_write_{index} enabled={enabled}")
    assert enabled

# Test open_extcsd with file (compare=False) - no chip ready
gui.extcsd_chip_ready = False
gui.extcsd_ready = False
gui.extcsd_data = None
gui.extcsd_values = {}
gui.extcsd_drafts = {}
gui.extcsd_reference = {}
gui._refresh_extcsd_rows()

with TemporaryDirectory() as folder:
    p = Path(folder) / "config.bin"
    imported = bytearray(data)
    imported[177] = 0x03
    imported[179] = 0x49
    p.write_bytes(imported + bytes(32))
    
    print(f"DEBUG: before open_extcsd compare=False data[192] = {data[192]}")
    gui.open_extcsd(compare=False, path=str(p))
    print(f"DEBUG: after open_extcsd compare=False data[192] = {data[192]}")
    
    # File values should be populated, chip values should be --
    for index in (177, 178, 179, 162, 160):
        assert dpg.get_value(f"ext_file_{index}") == f"{imported[index]:02X}"
        # Selected field shows imported value in "New" column (since no chip, imported becomes the base)
        # Non-selected fields show draft (which is also imported)
        assert dpg.get_value(f"ext_new_{index}") == f"{imported[index]:02X}"
        assert not dpg.get_item_configuration(f"ext_write_{index}")["enabled"]  # disabled when no chip
    
    assert len(gui.extcsd_file_tail) == 32

    # Test open_extcsd with compare=True (same file, still in temp dir)
    print(f"DEBUG: before _show_extcsd data[192] = {data[192]}")
    gui._show_extcsd(bytes(data), "chip", cid)  # Re-establish chip data
    print(f"DEBUG: after _show_extcsd data[192] = {data[192]}")
    print(f"DEBUG: before open_extcsd compare: extcsd_ready={gui.extcsd_ready}, extcsd_chip_ready={gui.extcsd_chip_ready}")
    gui.open_extcsd(compare=True, path=str(p))
    print(f"DEBUG: after open_extcsd compare: extcsd_ready={gui.extcsd_ready}, extcsd_chip_ready={gui.extcsd_chip_ready}")

    # Compare should show differences
    print(f"DEBUG: ext_file_177 = {dpg.get_value(f'ext_file_177')}")
    print(f"DEBUG: txt_extcsd_source = {dpg.get_value('txt_extcsd_source')}")
    assert dpg.get_value(f"ext_file_177") == "03"
    assert "2 из 512" in dpg.get_value("txt_extcsd_source") or "Differing bytes: 2" in dpg.get_value("txt_extcsd_source")

    # Test invalid file sizes rejected
    for invalid_size in (0, 511, 513, 543):
        p.write_bytes(bytes(invalid_size))
        try:
            load_file(p)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid size {invalid_size} accepted")

# Test validate_write constraints
from modes.emmc.extcsd import validate_write

print(f"DEBUG: data[192] = {data[192]}")

# Reset RST_N_FUNCTION to 0 for testing (original test did this)
data[162] = 0

# Valid writes
for index, value in ((177, 2), (178, 1), (179, 0x48)):
    validate_write(data, index, value)

# Invalid writes rejected
for index, value in ((160, 7), (178, 0x10), (178, 2), (162, 1)):
    try:
        validate_write(data, index, value)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Invalid write accepted: index={index}, value={value}")

# OTP writes allowed
validate_write(data, 178, 0x10, True)
validate_write(data, 162, 1, True)

# Protected writes rejected
protected = bytearray(data)
print(f"DEBUG: before protected[178] = {protected[178]:02X}")
protected[178] = 0x10
print(f"DEBUG: after protected[178] = {protected[178]:02X}")
print(f"DEBUG: protected[179] = {protected[179]:02X}")
try:
    # Write a different value to trigger the protection check
    validate_write(protected, 179, 0x49)
except ValueError:
    pass
else:
    raise AssertionError("Protected write accepted")

try:
    validate_write(protected, 178, 0)
except ValueError:
    pass
else:
    raise AssertionError("Protected write accepted")

# RST_N_FUNCTION one-time
protected[162] = 1
for old_rst in (0, 1, 2):
    rst_snapshot = bytearray(data)
    rst_snapshot[162] = old_rst
    for new_rst in (0, 1, 2):
        if old_rst != new_rst:
            try:
                validate_write(rst_snapshot, 162, new_rst)
            except ValueError:
                pass
            else:
                raise AssertionError(f"RST change accepted: {old_rst} -> {new_rst}")
        assert validate_write(rst_snapshot, 162, new_rst, True) == old_rst

try:
    validate_write(data, 162, 3, True)
except ValueError:
    pass
else:
    raise AssertionError("Invalid RST value accepted with OTP")

# Test write_extcsd flow with mocked session
from unittest.mock import patch, Mock
from modes.emmc import operations

class WriteSession:
    def __init__(self, log_cb=None):
        pass
    current = bytes(data)
    readback = None
    identity = cid
    sent = []
    def open(self):
        return True
    def init_hw(self, *args):
        pass
    def wake_registers(self, *args):
        return self.identity, b"csd", self.current
    def write_extcsd_byte(self, index, value, delay):
        self.sent.append((index, value))
        changed = bytearray(self.current)
        changed[index] = value
        self.current = bytes(changed)
    def read_extcsd(self):
        return self.current if self.readback is None else self.readback
    def close(self):
        pass

with patch.object(operations, "EmmcSession", WriteSession):
    WriteSession.sent.clear()
    # Write a different value (BOOT_ENABLE=2) to trigger the actual write
    result = operations.write_extcsd(lambda m: None, True, "4-bit",
                                    179, 0x50, bytes(data), cid)
    print(f"DEBUG: WriteSession.sent = {WriteSession.sent}")
    assert result[0][179] == 0x50 and WriteSession.sent == [(179, 0x50)]
    
    for failure in ("cid", "stale", "verify", "cancel"):
        WriteSession.sent.clear()
        WriteSession.identity = b"wrong" if failure == "cid" else cid
        WriteSession.current = bytes(protected) if failure == "stale" else bytes(data)
        if failure == "stale":
            altered = bytearray(data)
            altered[179] = 8
            WriteSession.current = bytes(altered)
        WriteSession.readback = bytes(data) if failure == "verify" else None
        if failure == "cancel":
            assert operations.write_extcsd(lambda m: None, True, "4-bit",
                179, 0x48, bytes(data), cid, lambda: True) is None
        elif failure == "verify":
            errors = []
            actual, _ = operations.write_extcsd(errors.append, True, "4-bit",
                                               179, 0x50, bytes(data), cid)
            assert actual == bytes(data)
            assert any("Ошибка верификации" in message for message in errors)
            assert not any("подтверждена" in message for message in errors)
        else:
            try:
                operations.write_extcsd(lambda m: None, True, "4-bit",
                    179, 0x48, bytes(data), cid)
            except RuntimeError:
                pass
            else:
                raise AssertionError(failure)
        assert len(WriteSession.sent) == (1 if failure == "verify" else 0)

# Confirmed RST_n changes are attempted; a chip retaining its OTP value fails verification.
rst_before = bytearray(data)
rst_before[162] = 1
WriteSession.identity = cid
for requested in (0, 2):
    WriteSession.current, WriteSession.readback = bytes(rst_before), None
    WriteSession.sent.clear()
    with patch.object(operations, "EmmcSession", WriteSession):
        actual, _ = operations.write_extcsd(
            lambda m: None, True, "4-bit", 162, requested, rst_before, cid, allow_otp=True)
    assert actual[162] == requested and WriteSession.sent == [(162, requested)]
    WriteSession.current = WriteSession.readback = bytes(rst_before)
    with patch.object(operations, "EmmcSession", WriteSession):
        errors = []
        actual, _ = operations.write_extcsd(errors.append, True, "4-bit",
                                           162, requested, rst_before, cid, allow_otp=True)
        assert actual[162] == 1
        assert any("Ошибка верификации EXT_CSD [162]" in message for message in errors)
        assert not any("подтвержден" in message for message in errors)
WriteSession.readback = None

# Test DPG GUI: open_extcsd populates File/New, not Chip
gui.extcsd_chip_ready = False
gui.extcsd_ready = False
with TemporaryDirectory() as folder:
    p = Path(folder) / "config.bin"
    for tail_size in (0, 32):
        gui.extcsd_chip_ready = False
        gui.extcsd_ready = False
        p.write_bytes(imported + bytes(tail_size))
        gui.open_extcsd(path=str(p))
        
        assert not gui.extcsd_chip_ready
        for index in (177, 178, 179, 162, 160):
            assert dpg.get_value(f"ext_chip_{index}") == "--"
            assert dpg.get_value(f"ext_file_{index}") == f"{imported[index]:02X}"
            assert dpg.get_value(f"ext_new_{index}") == f"{imported[index]:02X}"
            assert not dpg.get_item_configuration(f"ext_write_{index}")["enabled"]
        assert len(gui.extcsd_file_tail) == tail_size

# Test read_extcsd populates chip values
def fake_read(*args, **kwargs):
    print(f"DEBUG fake_read: len(args)={len(args)}")
    # args: (voltage, bus, result_cb, started_cb)
    if len(args) >= 4:
        result_cb = args[2]
        started_cb = args[3]
    else:
        return
    started_cb()
    result_cb(bytes(data), cid)

with patch.object(gui.orchestrator, "run_read_extcsd", side_effect=fake_read):
    gui.read_extcsd()

# Process queue to apply results
print(f"DEBUG: queue size before = {gui.q.qsize()}")
gui._process_queue()
print(f"DEBUG: queue size after = {gui.q.qsize()}")
print(f"DEBUG: extcsd_drafts = {gui.extcsd_drafts}")

for index in (177, 178, 179, 162, 160):
    chip_val = dpg.get_value(f"ext_chip_{index}")
    file_val = dpg.get_value(f"ext_file_{index}")
    new_val = dpg.get_value(f"ext_new_{index}")
    print(f"DEBUG: index={index}, chip={chip_val}, file={file_val}, new={new_val}, selected={index == gui.extcsd_selected_field}")
    assert chip_val == f"{data[index]:02X}"
    assert file_val == f"{imported[index]:02X}"
    # After read_extcsd, chip data becomes the base, so New column shows chip values
    assert new_val == f"{data[index]:02X}"
assert gui.extcsd_chip_ready

# Combined chip write: preflight, images first, irreversible protection last.
from modes.emmc.extcsd import write_plan
from modes.emmc.write_files import find_write_files
from orchestrator import AppOrchestrator
from unittest.mock import Mock

baseline = bytearray(512)
baseline[192] = 8
target = bytearray(baseline)
target[177], target[179], target[162], target[178], target[160] = 2, 0x48, 1, 0x10, 7
assert [i for i, _, _ in write_plan(baseline, target)] == [177, 179, 162, 178]
assert not write_plan(target, target)
bad = bytearray(target)
bad[162] = 3
try:
    write_plan(baseline, bad)
except ValueError:
    pass
else:
    raise AssertionError("Invalid batch accepted")

events, messages = [], []
worker = AppOrchestrator(messages.append, lambda *a, **kw: None)
worker.run_task = lambda fn, *a, **kw: fn(*a)
current = bytes(baseline)
identity = cid
def read_config(*a):
    events.append("read")
    return current, identity
def write_config(voltage, bus, index, value, expected, expected_cid, abort, allow_otp):
    global current
    assert expected == current and expected_cid == cid and allow_otp
    validate_write(current, index, value, allow_otp=True)
    events.append(index)
    updated = bytearray(current)
    updated[index] = value
    current = bytes(updated)
    return current, cid
def write_image(voltage, bus, area, path, **kw):
    events.append(area)
    return True
worker.emmc_driver = Mock()
worker.emmc_driver.read_extcsd.side_effect = read_config
worker.emmc_driver.write_extcsd.side_effect = write_config
worker.emmc_driver.write_partition.side_effect = write_image
payload = (bytes(baseline), cid, bytes(target))
with TemporaryDirectory() as folder:
    paths = {}
    for area, filename in (("BOOT1", "Boot1.bin"), ("BOOT2", "Boot2.bin"), ("USER", "userdata.img")):
        path = Path(folder) / filename
        path.write_bytes(bytes(16384))
        paths[area] = str(path)
    config_path = Path(folder) / "ECSD_CSD.BIN"
    config_path.write_bytes(target + bytes(32))
    paths["EXTCSD"] = str(config_path)
    found = find_write_files(folder, {"BOOT1": 16384, "BOOT2": 16384, "USER": 16384})
    assert found["EXTCSD"]["ready"] and found["EXTCSD"]["path"] == str(config_path.resolve())
    
    # Test DPG GUI start_write_all with EXT_CSD
    gui.boot_size_bytes = 16384
    gui.user_total_sectors = 32
    gui.write_folder = folder
    gui._manual_write_files.clear()
    gui._show_extcsd(baseline, "chip", cid)
    # Use the same preset as _connection_settings() returns
    from modes.emmc import protocol as P
    gui.emmc_preset_display = P.DEFAULT_PRESET
    gui._extcsd_settings = (gui.dpg.get_value("chk_voltage"), gui.dpg.get_value("combo_bus"),
                           gui.emmc_preset_display, gui.dpg.get_value("combo_clock"))
    gui.refresh_write_files()
    assert gui.write_files["EXTCSD"]["ready"]
    
    # Mock _confirm_blocking to return True (simulate user confirmation)
    with patch.object(gui, "_confirm_blocking", return_value=True):
        with patch.object(gui.orchestrator, "run_write_all") as launch:
            gui.start_write_all()
            assert launch.call_args.kwargs["extcsd"] == payload
            assert launch.call_args.args[2]["EXTCSD"] == str(config_path.resolve())
    
    result = Mock()
    worker.run_write_all(True, "4-bit", paths, extcsd=payload, result_cb=result)
    assert events == ["read", "BOOT1", "BOOT2", "USER", "read", 177, 179, 162, 178], events
    assert result.call_args.args[0][178] == 0x10
    current = bytes(baseline)
    events.clear()
    def refuse_rst(*args, **kwargs):
        global current
        actual, actual_cid = write_config(*args, **kwargs)
        if args[2] == 162:
            unchanged = bytearray(actual)
            unchanged[162] = baseline[162]
            current = bytes(unchanged)
        return current, actual_cid
    worker.emmc_driver.write_extcsd.side_effect = refuse_rst
    worker.run_write_all(True, "4-bit", paths, extcsd=payload)
    assert events[-2:] == [162, 178]
    assert current[162] == baseline[162] and current[178] == 0x10
    assert any("завершена с ошибками верификации" in message for message in messages)
    worker.emmc_driver.write_extcsd.side_effect = write_config
    for failure in ("cid", "invalid", "image", "cancel"):
        current = bytes(baseline)
        identity = b"wrong" if failure == "cid" else cid
        events.clear()
        worker.stop_event.clear()
        worker.emmc_driver.write_partition.side_effect = write_image
        test_payload = (bytes(baseline), cid, bytes(bad)) if failure == "invalid" else payload
        if failure == "image":
            worker.emmc_driver.write_partition.side_effect = lambda *a, **kw: False
        if failure == "cancel":
            worker.stop_event.set()
        try:
            worker.run_write_all(True, "4-bit", paths, extcsd=test_payload)
        except (ValueError, RuntimeError):
            assert failure in ("cid", "invalid")
        else:
            assert failure in ("image", "cancel")
        assert not any(isinstance(event, int) for event in events), (failure, events)
        if failure in ("cid", "invalid"):
            assert "BOOT1" not in events
    config_path.write_bytes(bytes(543))
    assert not find_write_files(folder, {})["EXTCSD"]["ready"]

# Analysis must expose the hardware snapshot and all five settings in its log.
WriteSession.identity, WriteSession.current = cid, bytes(baseline)
with patch.object(operations, "EmmcSession", WriteSession), \
     patch.object(WriteSession, "rpmb_probe", return_value=bytes(16), create=True), \
     patch.object(WriteSession, "select_user", create=True), \
     patch.object(WriteSession, "read_sectors", return_value=bytes(32768), create=True), \
     patch.object(operations.parts_mod, "parse", return_value=[]):
    info, _ = operations.read_info_and_partitions(lambda m: None, True, "4-bit")
assert info["extcsd"] == bytes(baseline) and info["cid"] == cid
for index in (177, 178, 179, 162, 160):
    assert f"[{index}]" in info["report"]

dpg.destroy_context()
print("EXT_CSD smoke: OK (file columns, combined write, preflight, OTP order, analysis, readback)")

