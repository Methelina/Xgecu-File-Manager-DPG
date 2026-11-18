"""E2E-style demo: fills the DPG GUI as if a real chip was read.

Press INIT EMMC in the window: the scripted scenario starts from the
click and drives the same orchestrator callbacks (log/table/task/
progress/phase via queue.Queue) the app itself uses - a GPT layout from
a real MT6768 scatter, an EXT_CSD snapshot (512 bytes + CID/CSD tail),
live progress with MiB/s, journal lines in the backend format.

Run: xgecu_env\\Scripts\\python.exe -X utf8 tests\\demo_dpg_e2e.py
Close the window to exit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from gui_dpg import DpgGui

SECTOR = 512

FS_BY_NAME = {
    "boot_a": "Android boot", "vendor_boot_a": "Android boot",
    "super": "f2fs/dm", "userdata": "f2fs/dm", "custpack": "f2fs/dm",
    "metadata": "ext4", "sp_data": "ext4",
    "preloader": "raw", "pgpt": "raw", "misc": "raw", "para": "raw",
    "seccfg": "raw", "lk_a": "raw",
}


# GPT layout from a real MT6768 scatter (29.0 GiB eMMC): start in bytes,
# extent in sectors (from the next partition start in the scatter).
def build_layout():
    entries = [
        ("preloader", 0, 4096), ("pgpt", 0, 34),
        ("misc", 32768, 512), ("countrycode", 557056, 1024),
        ("para", 2654208, 512), ("expdb", 3178496, 8192),
        ("frp", 24150016, 8192), ("gsort", 25198592, 16384),
        ("ffu", 41975808, 8192), ("cust", 50364416, 131072),
        ("blk1", 2197848064, 16384), ("rescue", 2206236672, 16384),
        ("vbmeta_a", 2340454400, 64), ("vbmeta_system_a", 2348843008, 64),
        ("vbmeta_vendor_a", 2357231616, 64), ("vbmeta_b", 2365620224, 64),
        ("vbmeta_system_b", 2374008832, 64), ("vbmeta_vendor_b", 2382397440, 64),
        ("md_udc", 2390786048, 2048), ("metadata", 2414485504, 32768),
        ("nvcfg", 2448039936, 30720), ("nvdata", 2481594368, 65536),
        ("persist", 2548703232, 49152), ("protect1", 2599034880, 8192),
        ("protect2", 2607423488, 8192), ("seccfg", 2617245696, 512),
        ("md1img_a", 2625634304, 24576), ("spmfw_a", 2759852032, 512),
        ("scp_a", 2760900608, 512), ("sspm_a", 2767192064, 512),
        ("gz_a", 2768240640, 1024), ("lk_a", 2785017856, 512),
        ("boot_a", 2789212160, 65536), ("vendor_boot_a", 2856321024, 65536),
        ("dtbo_a", 2923429888, 1024), ("tee_a", 2931818496, 1024),
        ("sec1", 2944401408, 512), ("proinfo", 2946498560, 3072),
        ("efuse", 2949644288, 512), ("naf_token", 2952562688, 2048),
        ("hw_aikey", 2954536960, 512), ("otp", 2956511232, 512),
        ("mcf_log", 2958485504, 8192), ("reserved1", 2960410624, 16384),
        ("sp_data", 2962337792, 262144), ("reserved2", 2964966144, 131072),
        ("reserved3", 2967593472, 131072), ("unk", 2970220800, 512),
        ("super", 2972145920, 33554432), ("custpack", 3276062720, 1048576),
        ("tctpersist", 3286620160, 2048), ("metadata_nvme", 3288622080, 16384),
        ("userdata", 3290112000, 24556346880 // SECTOR),
    ]
    parts = [{"is_table": True, "name": "Таблица (GPT)", "fs": "GPT",
              "first": 0, "last": 33, "size": 34 * SECTOR / 1024 / 1024}]
    for name, start_bytes, sectors in entries:
        first = start_bytes // SECTOR
        fs = FS_BY_NAME.get(name, "ext4")
        parts.append({"name": name, "fs": fs, "first": first,
                      "last": first + sectors - 1,
                      "size": sectors * SECTOR / 1024 / 1024})
    return parts


def build_extcsd_snapshot():
    # 512-byte EXT_CSD of a typical eMMC 5.1 (MTK phone) + 32-byte CID/CSD tail
    d = bytearray(512)
    d[177] = 0x07   # BOOT_BUS_WIDTH: 8-bit, DDR
    d[178] = 0x00   # BOOT_CONFIG_PROT: none
    d[179] = 0x49   # PARTITION_CONFIG: boot from BOOT1, ACK
    d[162] = 0x01   # RST_N_FUNCTION: permanent
    d[160] = 0x01   # PARTITIONING_SUPPORT
    d[212] = 0x57   # SEC_COUNT: 0x572A9DEE sectors = 29.0 GiB
    d[213] = 0x9D
    d[214] = 0x2A
    d[215] = 0xEE
    d[226] = 0x20   # BOOT_SIZE_MULT = 32 -> 4 MiB boot partitions
    d[181] = 0x00   # ERASED_MEM_CONT
    d[168] = 0x60   # EXT_CSD_REV 6.0
    cid = bytes.fromhex("15010050343833314030903032d4c700")
    csd = bytes.fromhex("d07f01320f5903fff6f9cfff8a408000")
    return bytes(d) + cid + csd


class DemoStub:
    """Orchestrator stand-in: INIT triggers the scripted scenario,
    other hardware calls report and stay idle."""

    def __init__(self, gui, on_init):
        self._gui = gui
        self._on_init = on_init

    def set_mode(self, m):
        pass

    def stop_operation(self):
        self._gui.log_cb("[*] STOP: demo mode, nothing to stop.")

    def run_read_info(self, voltage, bus, result_cb=None):
        self._on_init()

    def __getattr__(self, name):
        if name.startswith("run_"):
            def _demo(*args, **kwargs):
                self._gui.log_cb("[!] Demo mode: hardware operations are simulated "
                                 "by the INIT EMMC scenario only.")
            return _demo
        raise AttributeError(name)


def main():
    gui = DpgGui()
    dpg = gui.dpg

    layout = build_layout()
    snapshot = build_extcsd_snapshot()
    user_sectors = 0x572A9DEE

    # scenario: sorted (relative frame from INIT click, callable);
    # cursor guards double-firing when two frame chains are alive
    events = []
    armed = {"start": None}
    cursor = {"i": 0}

    def at(rel, fn):
        events.append((rel, fn))

    def log(msg):
        return lambda: gui.log_cb(msg)

    # --- phase 1: INIT EMMC ---
    at(0, log("[*] INIT EMMC: открытие T48..."))
    at(3, log("[+] T48 найден (WinUSB), версия прошивки 22.09.14"))
    at(5, lambda: gui.task_cb(True))
    at(6, lambda: gui.phase_cb("image analyze"))
    at(6, log("[*] Идёт анализ: чтение CID/CSD/EXT_CSD..."))
    for i in range(7, 37, 6):
        at(i, lambda p=(i - 7) / 30 * 100.0: gui.progress_cb(p, 3.2 + 0.3 * (i % 7)))
    at(21, log("[*] Проверка кандидата: 8 МГц, 4-bit, VCCQ 1.8 В"))
    at(31, log("[+] Кандидат принят: CID совпал, чтение начала/середины/конца OK"))
    at(37, lambda: gui.progress_cb(100.0, 3.0))
    at(39, log("[+] Анализ завершён. Пресет: стандартный, 30 МГц, 4-bit, VCCQ 1.8 В"))

    # --- phase 2: layout (as run_read_info table_cb) ---
    at(42, lambda: gui.table_cb(layout, boot_bytes=4 * 1024 * 1024,
                                user_mb=user_sectors * 512 // (1024 * 1024),
                                user_sectors=user_sectors))
    at(42, log("[+] Разметка GPT: 54 раздела, User Area 29.0 ГиБ, BOOT по 4 МиБ"))

    # --- phase 3: EXT_CSD snapshot (as run_read_info result_cb) ---
    def apply_extcsd():
        cid = snapshot[512:528]
        gui._extcsd_settings = gui._connection_settings()
        gui._show_extcsd(snapshot[:512], "Analyze: CID " + cid.hex(), cid)
        gui._apply_extcsd_import()
    at(45, lambda: gui.q.put(("call", apply_extcsd)))
    at(47, log("[+] EXT_CSD прочитан: 512 байт, CID 15010050...c700"))
    at(49, log("[*] Эталонный файл EXT_CSD не загружен - сравнение недоступно"))

    # --- phase 4: userdata read, live progress ---
    at(55, log("[*] Чтение User Area -> userdata_dump.img (29.0 ГиБ)..."))
    at(55, lambda: gui.phase_cb("read"))
    for i in range(57, 237, 4):
        frac = (i - 57) / 180.0
        at(i, lambda p=frac * 37.5: gui.progress_cb(p, 24.5 + 2.5 * ((i * 7) % 5)))

    # --- phase 5: STOP, verify, finish ---
    at(237, log("[*] Остановка по запросу пользователя..."))
    at(239, lambda: gui.phase_cb("verify"))
    at(239, log("[*] Верификация readback: первые 32 МиБ..."))
    for i in range(241, 297, 4):
        frac = (i - 241) / 56.0
        at(i, lambda p=frac * 100.0: gui.progress_cb(p, 61.0 + 1.5 * ((i * 3) % 4)))
    at(297, log("[+] Верификация: readback совпал"))
    at(299, log("[+] sha256 userdata_dump.img: 9f2c41a7e3d05b68a4f0c2de71b846a5"
                "e9d3c804fa5b217c6de8091b4a3f7e5d"))
    at(301, lambda: gui.task_cb(False))
    at(301, log("[+] Готово. Чтение остановлено на 37.5% User Area, данные валидны."))

    def _tick():
        frame = dpg.get_frame_count()
        start = armed["start"]
        if start is not None:
            while cursor["i"] < len(events):
                rel, fn = events[cursor["i"]]
                if start + rel > frame:
                    break
                cursor["i"] += 1
                fn()
        gui._process_queue()
        gui._update_status_widgets()
        dpg.set_frame_callback(frame + 1, _tick)

    def on_init():
        if armed["start"] is not None:
            gui.log_cb("[*] INIT EMMC: demo already ran once; close and reopen to replay.")
            return
        armed["start"] = dpg.get_frame_count()

    gui.orchestrator = DemoStub(gui, on_init)

    dpg.create_context()
    gui.build()
    gui._append_log_line("[+] Demo E2E: press INIT EMMC to run the simulated chip read "
                         "(MT6768, 29 GiB).")
    gui._log_dirty = True
    dpg.set_frame_callback(dpg.get_frame_count() + 1, _tick)
    try:
        while dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
    finally:
        dpg.destroy_context()


if __name__ == "__main__":
    main()
