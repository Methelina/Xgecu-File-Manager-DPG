"""Xgecu Prog DearPyGui frontend by Soror L.'.L.'.
Version: 2.1.0
Updated: 2026-11-19

Entry point: python src/gui_dpg.py [--demo | -Legacy]
Backend (orchestrator, modes/, t48_usb) is shared with the legacy Kivy
gui.py. UI strings are localized via strings.py (RU/EN); journal lines
arrive from the backend as-is.

Patchnote v2.1.0 (Soror L.'.L.'.):
  [+] RU/EN localization: strings.py, RU/EN buttons in the title row,
      full window rebuild on switch; RU renders in VCR OSD Mono RUS.
  [+] Status lamp (OctoGirl CrisTical pattern) pinned to the title row
      via a stretch table: probed with legacy XGecuT48.open() at 1 s,
      INIT/ERROR states; demo cycles states every 5 s.
  [+] Text progress bar with a dedicated bar font (DejaVu Sans Mono,
      U+25B0/U+25B1) replacing the native progress bar; width follows
      the panel via a resize handler.
  [+] Windows-style multi-row partition selection (click / Ctrl+click /
      Shift+click range) with per-selection DUMP/WRITE/ERASE.
  [*] Fixed lang-switch rebuild (duplicate-tag crashes that dropped the
      NAND/SPI tabs) and the _rebuild_table method lost in a rewrite.
Patchnote v2.0.0 (Soror L.'.L.'.):
  [+] Layout refactor: core moved to src/, project-root resolvers for
      assets/.version.cfg/.lang.cfg (dev vs frozen).
  [+] Kernel synced with upstream: benchmark/firmware/rpmb/service
      modules now importable; --demo scripted chip read moved in from
      tests.
Patchnote v1.1.0 (Soror L.'.L.'.):
  [+] EXT_CSD table with per-field read/write, file compare, modal OTP
      confirmations (162/178) replacing tkinter; blocking plan confirm.
  [+] Journal with level filter, search, per-line coloring and copy from
      the full buffer; progress overlay percent and MiB/s.
Patchnote v1.0.0 (Soror L.'.L.'.):
  [+] Initial DPG frontend: CrisTical dark theme (OctoGirl palette),
      font system (ModeSeven/VCR/JetBrains NF with Cyrillic remap),
      EMMC/NAND/SPI tabs, READ/WRITE/ERASE sub-tabs, thread bridge
      queue -> frame callback, _gui_ready guard.
"""

import queue
import sys
import time
from datetime import datetime
from pathlib import Path

import strings as st
from modes.emmc.write_files import AREA_NAMES, find_write_files
from modes.emmc import protocol as P

def _project_root():
    # dev: src/gui_dpg.py with assets/.version.cfg in the project root;
    # frozen: resources unpack next to __file__ (PyInstaller datas)
    here = Path(__file__).resolve().parent
    return here.parent if here.name == "src" else here


_PROJECT_ROOT = _project_root()
FONTS_DIR = _PROJECT_ROOT / "assets" / "fonts"
ASSETS_DIR = _PROJECT_ROOT / "assets"


def _load_version():
    cfg = _PROJECT_ROOT / ".version.cfg"
    try:
        text = cfg.read_text(encoding="utf-8").strip()
        return text if text else "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _load_version()
APP_TITLE = f"Xgecu Prog v{APP_VERSION}"


def _load_lang():
    cfg = _PROJECT_ROOT / ".lang.cfg"
    try:
        lang = cfg.read_text(encoding="utf-8").strip().lower()
        return lang if lang in ("ru", "en") else "en"
    except OSError:
        return "en"


def _save_lang(lang):
    cfg = _PROJECT_ROOT / ".lang.cfg"
    try:
        cfg.write_text(lang + "\n", encoding="utf-8")
    except OSError:
        pass

_LOG_VIEW_LINES = 400
_EXT_FIELD_ORDER = (177, 178, 179, 162, 160)

# protocol preset keys are Cyrillic; resolve them once at import
_PRESET_STANDARD_KEY = next((k for k in P.PRESET_SETUP if k != "THGA"), "standard")
_PRESET_AUTO_KEY = P.DEFAULT_PRESET if P.DEFAULT_PRESET not in P.PRESET_SETUP else "auto"
_PRESET_DISPLAY_TO_KEY = {"standard": _PRESET_STANDARD_KEY, "THGA": "THGA", "Auto": _PRESET_AUTO_KEY}
_PRESET_KEY_TO_DISPLAY = {v: k for k, v in _PRESET_DISPLAY_TO_KEY.items() if k != "standard"}
_PRESET_KEY_TO_DISPLAY[_PRESET_STANDARD_KEY] = "standard"

# OctoGirl role palette (exact values): warm amber accent, dim/idle grays,
# green = success, red = error, yellow = warn.
COL = {
    "window_bg": (25, 25, 35),
    "child_bg": (20, 22, 26),
    "frame_bg": (40, 42, 50),
    "text": (220, 220, 220),
    "text_dim": (140, 145, 155),
    "lba_blue": (110, 160, 255),
    "idle": (110, 110, 110),
    "header": (50, 50, 80),
    "accent": (255, 200, 100),
    "accent_soft": (235, 205, 130),
    "ok": (80, 210, 100),
    "warn": (240, 200, 60),
    "error": (230, 70, 70),
    "send_btn": (40, 70, 40),
    "send_hover": (50, 120, 50),
    "send_active": (30, 90, 30),
    "reset_btn": (70, 40, 40),
    "reset_hover": (120, 50, 50),
    "reset_active": (90, 30, 30),
    "selection_bg": (45, 40, 29),        # 2D281D
    "selection_hover": (70, 62, 43),
    "selection_active": (58, 51, 36),
    "lamp_online": (76, 175, 80),
    "lamp_init": (255, 200, 100),
    "lamp_error": (211, 47, 47),
}


def find_available_font():
    for name in ("JetBrainsMonoNerdFont-Regular.ttf", "JetBrainsMonoNerdFont-Medium.ttf"):
        p = FONTS_DIR / name
        if p.is_file():
            return p
    for name in ("consola.ttf", "segoeui.ttf", "arial.ttf"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.is_file():
            return p
    return None


def _log_level_of(line):
    stripped = line.lstrip()
    if stripped.startswith(("[!]", "[-]", "ERROR")) or "WRITE_FAILED" in stripped or "MISMATCH" in stripped:
        return "error"
    if stripped.startswith("[+]"):
        return "ok"
    if stripped.startswith("[*]"):
        return "info"
    return "text"


def _clean_text(value):
    # VHS body font lacks dashes/arrows/emoji; normalize to safe ASCII.
    table = {
        "\u2014": "-", "\u2013": "-", "\u2192": "->", "\u2190": "<-",
        "\u00ab": '"', "\u00bb": '"', "\u2026": "...",
    }
    for src, dst in table.items():
        value = value.replace(src, dst)
    return value


class DpgGui:
    def __init__(self):
        import dearpygui.dearpygui as dpg
        self.dpg = dpg
        self._gui_ready = False
        self.q = queue.Queue()
        self._dlg_seq = 0

        self.log_lines = []            # full journal: (text, level)
        self._log_dirty = False
        self.table_rows = []
        self.selected_parts = []       # ordered offsets into table_rows
        self._sel_anchor = None        # anchor row for Shift-range selection
        self._mod_ctrl = False
        self._mod_shift = False

        self.operation_running = False
        self.progress_value = 0.0
        self.progress_speed = 0.0
        self.progress_status = "Ready"
        self._bar_width = 24
        self._lamp_state = "OFFLINE"
        self._lamp_error_ts = 0.0
        self._lamp_poll_ts = 0.0
        self.firmware_text = "-"
        self.boot_size_bytes = 0
        self.user_total_sectors = 0

        self.write_folder = ""
        self._manual_write_files = {}
        self.write_files = find_write_files("", {})

        self.emmc_preset_display = "Auto"
        self._preset_clocks = {"standard": "30 MHz", "THGA": "30 MHz", "Auto": "Auto"}

        self.extcsd_data = None
        self.extcsd_file_tail = b""
        self.extcsd_ready = False
        self.extcsd_chip_ready = False
        self.extcsd_chip_cid = None
        self.extcsd_selected_field = 179
        self.extcsd_values = {}
        self.extcsd_drafts = {}
        self.extcsd_reference = {}
        self._extcsd_settings = None
        self._extcsd_import = None

        self.orchestrator = None

    # ------------------------------------------------------------------
    # Orchestrator bridge (worker thread -> queue -> frame callback)
    # ------------------------------------------------------------------

    def log_cb(self, msg):
        self.q.put(("log", msg))

    def table_cb(self, parts, boot_bytes=0, user_mb=0, user_sectors=None):
        self.q.put(("table", parts, boot_bytes, user_mb, user_sectors))

    def task_cb(self, running):
        self.q.put(("task", running))

    def progress_cb(self, percent, speed):
        self.q.put(("progress", percent, speed))

    def phase_cb(self, action):
        self.q.put(("phase", action))

    def _process_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._on_log(item[1])
                elif kind == "table":
                    self._on_table(*item[1:])
                elif kind == "task":
                    self._on_task(item[1])
                elif kind == "progress":
                    self._on_progress(item[1], item[2])
                elif kind == "phase":
                    self._on_phase(item[1])
                elif kind == "call":
                    item[1]()
        except queue.Empty:
            pass

    @staticmethod
    def _find_bar_font():
        """Locate a monospace font carrying the U+25B0/U+25B1 parallelograms.
        JetBrains Mono NF lacks them (block elements only); DejaVu Sans Mono
        and Cascadia cover the range."""
        candidates = [
            FONTS_DIR / "DejaVuSansMono.ttf",
            Path(r"C:\Windows\Fonts\DejaVuSansMono.ttf"),
            Path(r"C:\Windows\Fonts\CascadiaCodeNF.ttf"),
            Path(r"C:\Windows\Fonts\CascadiaMono.ttf"),
            Path(r"C:\Windows\Fonts\HackNerdFont-Regular.ttf"),
        ]
        for p in candidates:
            if p.is_file():
                return p
        return None

    _bar_font_path = None

    @classmethod
    def _bar_font_ready(cls):
        return cls._bar_font_path is not None

    @classmethod
    def _bar(cls, frac, width=24):
        # OctoGirl text-bar style: [▰▰▱▱▱▱▱▱▱▱] 20% rendered via the
        # dedicated bar font; without it: '#'/'.' degradation.
        full, empty = ("▰", "▱") if cls._bar_font_ready() else ("#", ".")
        frac = max(0.0, min(1.0, frac))
        filled = int(round(frac * width))
        return "[{}{}] {:3.0f}%".format(full * filled, empty * (width - filled),
                                        frac * 100)

    def _on_progress_row_resize(self, sender, app_data):
        # DejaVu Sans Mono advance at 14 px is ~8.4 px per glyph; keep
        # room for the percent + speed labels on the same row.
        dpg = self.dpg
        try:
            w = dpg.get_item_rect_size("progress_row")[0]
        except SystemError:
            return
        self._bar_width = max(10, min(80, int((w - 180) / 8.4)))
        dpg.set_value("progress_textbar", self._bar(self.progress_value / 100.0,
                                                    self._bar_width))

    def _update_lamp(self):
        # CrisTical status-circle lamp (OctoGirl pattern). ONLINE/OFFLINE are
        # probed with the same XGecuT48.open() call the legacy INIT path uses
        # (throttled to 1 s, idle only - never while an operation owns USB);
        # INIT is shown while an operation runs, ERROR for 10 s after a
        # failure journal line.
        dpg = self.dpg
        if not dpg.does_item_exist("t48_lamp"):
            return
        now = time.perf_counter()
        if now - self._lamp_poll_ts < 1.0:
            return
        self._lamp_poll_ts = now
        if isinstance(self.orchestrator, DemoOrchestrator):
            # demo: cycle OFFLINE -> ONLINE -> INIT -> ERROR every 5 s,
            # no real USB probing
            cycle = [("OFFLINE", COL["lamp_error"]), ("ONLINE", COL["lamp_online"]),
                     ("INIT", COL["lamp_init"]), ("ERROR", COL["lamp_error"])]
            state, color = cycle[int(now / 5.0) % len(cycle)]
            self._set_lamp(state, color)
            return
        if self.operation_running:
            state, color = "INIT", COL["lamp_init"]
        elif now - self._lamp_error_ts < 10.0:
            state, color = "ERROR", COL["lamp_error"]
        else:
            try:
                from t48_usb import XGecuT48
                probe = XGecuT48()
                online = probe.open()
                if online:
                    probe.close()
            except Exception:
                online = False
            state, color = ("ONLINE", COL["lamp_online"]) if online \
                else ("OFFLINE", COL["lamp_error"])
        self._set_lamp(state, color)

    def _set_lamp(self, state, color):
        dpg = self.dpg
        self._lamp_state = state
        dpg.configure_item("t48_lamp", fill=color + (255,))
        dpg.set_value("t48_state_value", state)
        dpg.configure_item("t48_state_value", color=color)
        dpg.set_value("t48_fw_value", f"{self.firmware_text} v.")
        dpg.configure_item("t48_fw_value", color=color)

    def _update_status_widgets(self):
        dpg = self.dpg
        if not dpg.does_item_exist("status_phase"):
            return
        self._refresh_log_view_if_dirty()
        self._update_lamp()
        dpg.set_value("status_phase", self.progress_status)
        dpg.set_value("progress_textbar", self._bar(self.progress_value / 100.0,
                                                    self._bar_width))
        dpg.set_value("progress_percent_text", "{:.2f}%".format(self.progress_value))
        dpg.set_value("progress_speed_text", "{:.2f} MiB/s".format(self.progress_speed))

    def _drain_queue(self):
        self._process_queue()
        self._update_status_widgets()
        if self._gui_ready and self.dpg.is_dearpygui_running():
            self.dpg.set_frame_callback(self.dpg.get_frame_count() + 1, self._drain_queue)

    # ------------------------------------------------------------------
    # Queue event handlers (GUI thread)
    # ------------------------------------------------------------------

    def _append_log_line(self, message):
        stamp = "[{}]".format(datetime.now().strftime("%H:%M:%S.%f")[:-3])
        text = _clean_text(str(message))
        self.log_lines.append((stamp + " " + text, _log_level_of(text)))
        self._log_dirty = True

    def _on_log(self, msg):
        message = str(msg).strip()
        if message.startswith(("... Progress:", "... Erased:", "... Written:", "... Wrote segment [")):
            return
        self._append_log_line(message)
        if message.startswith(("[+]",)):
            self._lamp_error_ts = 0.0
        elif message.startswith(("[-]",)) or "ERROR" in message:
            self._lamp_error_ts = time.perf_counter()
        lower = message.lower()
        if message.startswith(("[!]", "[-]")):
            if any(w in lower for w in ("stop", "interrupt", "cancel", "aborted")):
                self.progress_status = "Stopped"
            elif any(w in lower for w in ("error", "timeout", "not found", "no response", "failed")):
                self.progress_status = "Error - see log"
            else:
                self.progress_status = "Check log"

    def _on_task(self, running):
        self.operation_running = bool(running)
        if running:
            self.progress_value = 0.0
            self.progress_speed = 0.0
            self.progress_status = "Running"
        elif self.progress_status.startswith("Running") or self.progress_status == "Finishing":
            self.progress_value = 100.0
            self.progress_status = "Done"
        elif self.progress_status == "Stopping...":
            self.progress_status = "Stopped"
        self._refresh_busy_state()

    def _on_progress(self, percent, speed):
        self.progress_value = max(0.0, min(100.0, float(percent)))
        self.progress_speed = max(0.0, float(speed))

    _PHASE_LABELS = {
        "read": "Reading",
        "write": "Writing",
        "erase": "Erasing",
        "verify": "Verifying",
        "erase check": "Erase check",
        "image analyze": "Image analyze",
    }

    def _on_phase(self, action):
        label = self._PHASE_LABELS.get(action)
        if label and self.progress_status.startswith(("Running", "Reading", "Writing",
                                                      "Erasing", "Verifying")):
            self.progress_status = label
            self.progress_value = 0.0
            self.progress_speed = 0.0

    def _on_table(self, parts, boot_bytes=0, user_mb=0, user_sectors=None):
        dpg = self.dpg
        self.boot_size_bytes = int(boot_bytes)
        if user_sectors is not None:
            self.user_total_sectors = int(user_sectors)
        else:
            self.user_total_sectors = int(user_mb * 1024 * 1024) // P.SECTOR_SIZE
        self.refresh_write_files()
        if dpg.does_item_exist("erase_end") and self.user_total_sectors > 0:
            if self._erase_target_canonical(dpg.get_value("erase_target")) == "USER_ALL":
                dpg.set_value("erase_end", str(self.user_total_sectors - 1))
        self.table_rows = list(parts)
        self.selected_parts = []
        self._sel_anchor = None
        dpg.set_value("selected_part_text", st.S("selected_none"))
        self._rebuild_table()
        self._refresh_write_file_rows()

    # ------------------------------------------------------------------
    # Busy state
    # ------------------------------------------------------------------

    def _refresh_busy_state(self):
        dpg = self.dpg
        idle = not self.operation_running
        for tag in ("chk_voltage", "combo_bus", "combo_clock", "combo_preset",
                    "chk_verify_read", "chk_verify_write", "chk_erase_before_write",
                    "btn_init_emmc", "btn_read_userdata", "btn_read_boot1", "btn_read_boot2",
                    "btn_full_read", "btn_refresh_files", "btn_select_write_folder",
                    "btn_scatter_gpt", "btn_dump_sel", "btn_write_sel", "btn_erase_sel",
                    "btn_erase_run", "btn_extcsd_open", "btn_extcsd_compare", "btn_extcsd_save"):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=idle)
        for key in ("boot1", "boot2", "userdata", "extcsd"):
            ready = self.write_files.get(
                {"boot1": "BOOT1", "boot2": "BOOT2", "userdata": "USER", "extcsd": "EXTCSD"}[key],
                {}).get("ready", False)
            if dpg.does_item_exist(f"btn_write_{key}"):
                dpg.configure_item(f"btn_write_{key}", enabled=idle and ready)
            if dpg.does_item_exist(f"btn_pick_{key}"):
                dpg.configure_item(f"btn_pick_{key}", enabled=idle)
        if dpg.does_item_exist("btn_write_all"):
            all_ready = all(self.write_files[a]["ready"] for a in ("BOOT1", "BOOT2", "USER"))
            dpg.configure_item("btn_write_all", enabled=idle and all_ready)
        self._refresh_extcsd_rows()

    # ------------------------------------------------------------------
    # Journal
    # ------------------------------------------------------------------

    def _refresh_log_view_if_dirty(self):
        dpg = self.dpg
        if not self._log_dirty or not dpg.does_item_exist("log_lines_group"):
            return
        level = dpg.get_value("combo_log_level")
        query = str(dpg.get_value("input_log_search")).strip().lower()
        level_map = {st.S("log_level_all"): None, "INFO": "text", "OK": "ok", "WARN": "warn", "ERROR": "error"}
        want = level_map.get(level)
        shown = []
        for text, lvl in self.log_lines:
            if want is not None and lvl != want:
                continue
            if query and query not in text.lower():
                continue
            shown.append((text, lvl))
        view = shown[-_LOG_VIEW_LINES:]
        dpg.delete_item("log_lines_group", children_only=True)
        for text, lvl in view:
            dpg.add_text(text, color=COL.get(lvl, COL["text"]), parent="log_lines_group",
                         wrap=self._log_wrap_width())
        dpg.set_value("log_stats_text", st.S("log_lines_fmt").format(len(shown), len(self.log_lines)))
        self._log_dirty = False

    def _log_wrap_width(self):
        dpg = self.dpg
        try:
            w = dpg.get_item_rect_size("log_scroll")[0]
            return max(200, int(w) - 40)
        except SystemError:
            return 520

    def copy_log(self):
        full = "\n".join(text for text, _ in self.log_lines)
        self.dpg.set_clipboard_text(full)
        self._append_log_line("[+] Journal copied ({} lines)".format(len(self.log_lines)))

    def clear_log(self):
        self.log_lines.clear()
        self._log_dirty = True

    # ------------------------------------------------------------------
    # Presets / clock
    # ------------------------------------------------------------------

    _CLOCK_KEYS = ("clock_8", "clock_16", "clock_20", "clock_30", "clock_30_exp")

    def _clock_values(self):
        values = [st.S(k) for k in self._CLOCK_KEYS[:4]]
        if self.emmc_preset_display == "THGA":
            values.append(st.S("clock_30_exp"))
        return values

    def _preset_values(self):
        return [st.S("preset_standard"), "THGA", st.S("preset_auto")]

    def _preset_display(self):
        # canonical display name -> localized combo entry
        return {st.S("preset_standard"): st.S("preset_standard"),
                "THGA": "THGA",
                "Auto": st.S("preset_auto")}[self.emmc_preset_display]

    def on_preset_changed(self, sender, value):
        canonical = {st.S("preset_standard"): "standard",
                     "THGA": "THGA",
                     st.S("preset_auto"): "Auto"}.get(value)
        if canonical is None:
            return
        protocol_preset = _PRESET_DISPLAY_TO_KEY[canonical]
        previous = self.emmc_preset_display
        if previous != "Auto":
            self._preset_clocks[previous] = self.dpg.get_value("combo_clock")
        self.emmc_preset_display = canonical
        clock = self._preset_clocks.get(canonical, "30 MHz")
        values = self._clock_values()
        if clock not in values:
            clock = st.S("clock_30")
        P.DEFAULT_PRESET = protocol_preset
        self.dpg.configure_item("combo_clock", items=values, enabled=(canonical != "Auto"),
                                default_value=clock)
        self.dpg.set_value("combo_preset", self._preset_display())
        self.on_clock_changed(None, clock, force=True)
        if previous != canonical:
            if canonical == "Auto":
                self._append_log_line("[*] Auto: preset and clock are probed before each operation.")
            else:
                self._append_log_line(
                    f"[*] eMMC preset: {canonical}, {clock}. Applies from the next operation.")

    def on_clock_changed(self, sender, value, force=False):
        if self.emmc_preset_display == "Auto":
            return
        try:
            clock_mhz = int(value.split()[0])
        except (ValueError, AttributeError):
            return
        if clock_mhz not in P.CLOCK_SELECTORS:
            raise ValueError(f"Unsupported eMMC clock: {clock_mhz} MHz")
        experimental = "exp" in value or "эксп" in value
        if experimental and (self.emmc_preset_display != "THGA" or clock_mhz != 30):
            raise ValueError("Experimental 30 MHz is THGA-only")
        P.DEFAULT_CLOCK_MHZ = clock_mhz
        P.DEFAULT_LEGACY_30 = experimental
        if force:
            self.dpg.set_value("combo_clock", value)

    def _connection_settings(self):
        return (self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                P.DEFAULT_PRESET, self.dpg.get_value("combo_clock"))

    # ------------------------------------------------------------------
    # Actions: init / dumps / partitions
    # ------------------------------------------------------------------

    def _need_idle(self):
        if self.operation_running:
            self._append_log_line("[!] Operation is already running.")
            return False
        return True

    def start_analyze(self):
        if not self._need_idle():
            return
        from modes.emmc.autoconfig import forget
        forget()
        self.clear_log()
        self.boot_size_bytes = 0
        self.user_total_sectors = 0
        self.refresh_write_files()
        self.table_rows = []
        self.selected_parts = []
        self._sel_anchor = None
        self._rebuild_table()
        self.extcsd_chip_ready = False
        self.extcsd_chip_cid = None
        self.extcsd_ready = False
        self._refresh_extcsd_rows()
        voltage = self.dpg.get_value("chk_voltage")
        bus = self.dpg.get_value("combo_bus")

        def result(info):
            def apply():
                self._extcsd_settings = self._connection_settings()
                self._show_extcsd(info["extcsd"], "Analyze: CID " + info["cid"].hex(), info["cid"], clear_reference=True)
                self._apply_extcsd_import()
            self.q.put(("call", apply))
        self.orchestrator.run_read_info(voltage, bus, result_cb=result)

    def dump_userdata(self):
        if not self._need_idle():
            return
        self._file_dialog(st.S("dlg_save_userdata"), save=True, default_filename="userdata_dump.img",
                          extensions=[".img", ".bin", ".raw"],
                          callback=lambda p: self.orchestrator.run_dump_userdata(
                              self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                              p, verify=self.dpg.get_value("chk_verify_read")))

    def dump_boot(self, name):
        if not self._need_idle():
            return
        self._file_dialog(st.S("dlg_save_part").format(name), save=True, default_filename=f"{name}.bin",
                          extensions=[".bin"],
                          callback=lambda p: self.orchestrator.run_dump_boot(
                              self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                              name, None, p, verify=self.dpg.get_value("chk_verify_read")))

    def dump_all(self):
        if not self._need_idle():
            return
        self._file_dialog(st.S("dlg_dump_folder"), directory=True,
                          callback=self._start_dump_all)

    def _start_dump_all(self, folder):
        self.operation_running = True
        try:
            started = self.orchestrator.run_dump_all(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                folder, verify=self.dpg.get_value("chk_verify_read"))
            if started is False:
                self.operation_running = False
        except Exception:
            self.operation_running = False
            raise

    @staticmethod
    def _default_dump_name(name):
        if "GPT" in name:
            return "gpt_table.bin"
        if "MBR" in name:
            return "mbr_table.bin"
        clean = "".join(c for c in name if c.isalnum() or c in ("_", "-")) or "partition"
        return f"{clean}.img"

    def action_read_part(self):
        rows = self._selected_rows()
        if not rows:
            return
        if len(rows) == 1:
            row = rows[0]
            self._file_dialog(
                st.S("dlg_save_part").format(row['name']), save=True,
                default_filename=self._default_dump_name(row['name']),
                extensions=[".img", ".bin", ".raw"],
                callback=lambda p: self.orchestrator.run_dump_part(
                    self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                    row["name"], row["first"], row["last"], p,
                    verify=self.dpg.get_value("chk_verify_read")))
            return
        # multi-row: pick a folder once, one image per row (auto names)
        self._file_dialog(
            st.S("dlg_dump_n").format(len(rows)), directory=True,
            callback=lambda folder: self._dump_rows_to_folder(rows, folder))

    def _dump_rows_to_folder(self, rows, folder):
        voltage = self.dpg.get_value("chk_voltage")
        bus = self.dpg.get_value("combo_bus")
        verify = self.dpg.get_value("chk_verify_read")
        used = set()
        for row in rows:
            name = self._default_dump_name(row["name"])
            stem, ext = name.rsplit(".", 1)
            candidate, n = name, 2
            while stem.upper() in used:
                candidate = f"{stem}_{n}.{ext}"
                n += 1
            used.add(stem.upper())
            path = str(Path(folder) / candidate)
            self.orchestrator.run_dump_part(voltage, bus, row["name"],
                                            row["first"], row["last"], path, verify=verify)

    def action_write_part(self):
        rows = self._selected_rows()
        if not rows:
            return
        if len(rows) > 1:
            self._append_log_line("[!] WRITE applies to a single row; "
                                  "select one partition (plain click).")
            return
        row = rows[0]
        self._file_dialog(
            st.S("dlg_image_for").format(row['name']),
            extensions=[".img", ".bin", ".raw"],
            callback=lambda p: self.orchestrator.run_write_part(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                row["name"], row["first"], row["last"], p,
                verify=self.dpg.get_value("chk_verify_write"),
                erase_before=self.dpg.get_value("chk_erase_before_write")))

    def action_erase_part(self):
        rows = self._selected_rows()
        if not rows:
            return
        if len(rows) == 1:
            row = rows[0]
            self._append_log_line(
                f"[*] Erasing partition {row['name']} [LBA {row['first']}..{row['last']}]...")
            self.orchestrator.run_erase_task(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                "USER", row["first"], row["last"])
            return
        lines = [f"{r['name']}  LBA {r['first']}..{r['last']}" for r in rows]
        self._confirm("Hardware erase of {} partitions:\n\n{}\n\nErase ALL selected ranges?"
                      .format(len(rows), "\n".join(lines[:20])),
                      lambda: self._erase_rows(rows), danger=True)

    def _erase_rows(self, rows):
        voltage = self.dpg.get_value("chk_voltage")
        bus = self.dpg.get_value("combo_bus")
        for row in rows:
            self._append_log_line(
                f"[*] Erasing partition {row['name']} [LBA {row['first']}..{row['last']}]...")
            self.orchestrator.run_erase_task(voltage, bus, "USER",
                                             row["first"], row["last"])

    def _selected_rows(self):
        if not self.selected_parts:
            self._append_log_line("[!] Select a partition row first (click, "
                                  "Ctrl+click to add, Shift+click for a range).")
            return []
        valid = [i for i in self.selected_parts if i < len(self.table_rows)]
        return [self.table_rows[i] for i in valid]

    def on_part_selected(self, sender, app_data, user_data):
        dpg = self.dpg
        try:
            ctrl = (dpg.is_key_down(dpg.mvKey_LControl)
                    or dpg.is_key_down(dpg.mvKey_RControl) or self._mod_ctrl)
            shift = (dpg.is_key_down(dpg.mvKey_LShift)
                     or dpg.is_key_down(dpg.mvKey_RShift) or self._mod_shift)
        except (AttributeError, SystemError):
            ctrl, shift = self._mod_ctrl, self._mod_shift
        index = user_data
        if shift and self._sel_anchor is not None:
            lo, hi = sorted((self._sel_anchor, index))
            base = self.selected_parts if ctrl else []
            self.selected_parts = sorted(set(base) | set(range(lo, hi + 1)))
        elif ctrl:
            if index in self.selected_parts:
                self.selected_parts.remove(index)
            else:
                self.selected_parts.append(index)
            self._sel_anchor = index
        else:
            self.selected_parts = [index]
            self._sel_anchor = index
        # keep internal selectable state in sync (click already toggled
        # the clicked row itself; range/other rows are set programmatically)
        self._apply_row_selection()

    def _apply_row_selection(self):
        dpg = self.dpg
        for j in range(len(self.table_rows)):
            tag = f"part_row_{j}"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, j in self.selected_parts)
        if not self.selected_parts:
            dpg.set_value("selected_part_text", st.S("selected_none"))
        elif len(self.selected_parts) == 1:
            row = self.table_rows[self.selected_parts[0]]
            dpg.set_value("selected_part_text",
                          st.S("selected_one").format(row['name'], row['first'], row['last']))
        else:
            rows = [self.table_rows[i] for i in self.selected_parts if i < len(self.table_rows)]
            lba_lo = min(r["first"] for r in rows)
            lba_hi = max(r["last"] for r in rows)
            dpg.set_value("selected_part_text",
                          st.S("selected_many").format(len(rows), lba_lo, lba_hi))

    # ------------------------------------------------------------------
    # Write files
    # ------------------------------------------------------------------

    def select_write_folder(self):
        self._file_dialog(st.S("dlg_images_folder"), directory=True,
                          callback=self._set_write_folder)

    def _set_write_folder(self, folder):
        self.write_folder = folder
        self.dpg.set_value("txt_write_folder", folder)
        self._manual_write_files.clear()
        self.refresh_write_files()

    def select_write_file(self, part):
        if self.operation_running or part not in AREA_NAMES:
            return
        self._file_dialog(
            st.S("dlg_image_area").format(AREA_NAMES[part]),
            extensions=[".bin", ".img", ".raw"],
            callback=lambda p: self._set_write_file(part, p))

    def _set_write_file(self, part, path):
        self._manual_write_files[part] = path
        self.refresh_write_files()
        if part == "EXTCSD":
            self.open_extcsd(path=path)

    def refresh_write_files(self):
        self.write_files = find_write_files(self.write_folder, {
            "BOOT1": self.boot_size_bytes,
            "BOOT2": self.boot_size_bytes,
            "USER": self.user_total_sectors * P.SECTOR_SIZE,
        }, selected=self._manual_write_files)
        if self.dpg.does_item_exist("txt_write_boot1"):
            self._refresh_write_file_rows()

    _WRITE_ROW_KEYS = (("BOOT1", "boot1"), ("BOOT2", "boot2"),
                       ("USER", "userdata"), ("EXTCSD", "extcsd"))

    def _refresh_write_file_rows(self):
        dpg = self.dpg
        for key, suffix in self._WRITE_ROW_KEYS:
            row = self.write_files[key]
            dpg.set_value(f"txt_write_{suffix}", row["path"])
            dpg.set_value(f"status_txt_write_{suffix}", st.T(_clean_text(row["status"])))
            dpg.configure_item(f"btn_write_{suffix}",
                               enabled=not self.operation_running and row["ready"])
        all_ready = all(self.write_files[a]["ready"] for a in ("BOOT1", "BOOT2", "USER"))
        dpg.configure_item("btn_write_all",
                           enabled=not self.operation_running and all_ready)

    def start_write(self, part):
        if part == "EXTCSD":
            return self.start_write_extcsd_file()
        if not self._need_idle() or part not in AREA_NAMES:
            return
        self.refresh_write_files()
        row = self.write_files[part]
        if not row["ready"]:
            self._append_log_line(f"[!] {part}: {row['status']}")
            return
        self.operation_running = True
        try:
            self.orchestrator.run_write_task(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                part, row["path"], verify=self.dpg.get_value("chk_verify_write"),
                erase_before=self.dpg.get_value("chk_erase_before_write"))
        except Exception:
            self.operation_running = False
            raise

    def start_write_all(self):
        if not self._need_idle():
            return
        self.refresh_write_files()
        for area in ("BOOT1", "BOOT2", "USER"):
            if not self.write_files[area]["ready"]:
                self._append_log_line(f"[!] {area}: {self.write_files[area]['status']}")
                return
        files = {area: self.write_files[area]["path"] for area in ("BOOT1", "BOOT2", "USER")}
        row = self.write_files["EXTCSD"]
        payload = None
        if row["path"]:
            payload = self._prepare_write_extcsd_file()
            if payload is None:
                return
            files["EXTCSD"] = row["path"]
        else:
            self._append_log_line("[*] No EXT_CSD file selected; BOOT1, BOOT2 and Userdata will be written.")
        self.operation_running = True
        try:
            started = self.orchestrator.run_write_all(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                files, verify=self.dpg.get_value("chk_verify_write"),
                erase_before=self.dpg.get_value("chk_erase_before_write"),
                extcsd=payload, result_cb=self._write_extcsd_file_result)
            if started is False:
                self.operation_running = False
        except Exception:
            self.operation_running = False
            raise

    # ------------------------------------------------------------------
    # EXT_CSD
    # ------------------------------------------------------------------

    _EXT_HINTS = {
        179: "Bit 6: BOOT_ACK; bits 5:3: BOOT_ENABLE (0/1/2/7). Keep bits 2:0 unchanged.",
        177: "Bits 1:0: BOOT bus width (0=1-bit, 1=4-bit, 2=8-bit); bit 2: RESET; bits 4:3: BOOT mode.",
        178: "01 - boot protection until power-off; 10 - permanent NON-REVERSIBLE protection.",
        160: "PARTITIONING_SUPPORT: bit 0 partitioning; bit 1 enhanced; bit 2 extended. Read-only.",
        162: "NON-REVERSIBLE: 01 enable RST_n forever; 02 disable forever.",
    }

    def _show_extcsd(self, data, source, cid=None, file_tail=b"", clear_reference=True):
        from modes.emmc.extcsd import validate, describe
        data = validate(data)
        dpg = self.dpg
        self.extcsd_data = data
        self.extcsd_values = {i: f"{data[i]:02X}" for i in _EXT_FIELD_ORDER}
        self.extcsd_drafts = dict(self.extcsd_values)
        if clear_reference:
            self.extcsd_reference = {}
        self.extcsd_file_tail = bytes(file_tail)
        dpg.set_value("txt_extcsd_source", _clean_text(source))
        text = describe(data)
        if file_tail:
            text += "\n\nCID: " + file_tail[:16].hex(" ") + "\nCSD: " + file_tail[16:].hex(" ")
        dpg.set_value("txt_extcsd_dump", _clean_text(text))
        self.extcsd_ready = True
        self.extcsd_chip_cid = cid
        self.extcsd_chip_ready = cid is not None
        self.select_extcsd_field(self.extcsd_selected_field)

    def _refresh_extcsd_rows(self):
        dpg = self.dpg
        for index in _EXT_FIELD_ORDER:
            if not dpg.does_item_exist(f"ext_chip_{index}"):
                continue
            dpg.set_value(f"ext_chip_{index}",
                          self.extcsd_values.get(index, "--") if self.extcsd_ready else "--")
            dpg.set_value(f"ext_file_{index}",
                          self.extcsd_reference.get(index, "--") if self.extcsd_ready else "--")
            if self.extcsd_ready and index in self.extcsd_drafts and index != self.extcsd_selected_field:
                dpg.set_value(f"ext_new_{index}", self.extcsd_drafts[index])
            editable = self.extcsd_ready and not self.operation_running and index != 160
            dpg.configure_item(f"ext_new_{index}", enabled=editable)
            writable = self.extcsd_chip_ready and not self.operation_running and index != 160
            dpg.configure_item(f"ext_write_{index}", enabled=writable)
            selected = index == self.extcsd_selected_field
            dpg.bind_item_theme(f"ext_field_{index}",
                                "ext_field_selected" if selected else "ext_field_unselected")

    def select_extcsd_field(self, index, *_args):
        self.extcsd_selected_field = index
        self.dpg.set_value("txt_extcsd_hint", self._EXT_HINTS[index])
        if self.extcsd_ready:
            self.dpg.set_value(f"ext_new_{index}", f"{self.extcsd_data[index]:02X}")
        self._refresh_extcsd_rows()

    def edit_extcsd_value(self, index, text):
        if not self.operation_running and index != 160 and self.extcsd_ready:
            if self.extcsd_drafts.get(index) != text:
                self.extcsd_drafts[index] = text

    def read_extcsd(self):
        if not self._need_idle():
            return
        voltage = self.dpg.get_value("chk_voltage")
        bus = self.dpg.get_value("combo_bus")

        def started():
            def apply():
                self.extcsd_data = None
                self.extcsd_ready = False
                self.extcsd_chip_ready = False
                self.extcsd_chip_cid = None
                self.dpg.set_value("txt_extcsd_source", "Reading EXT_CSD...")
                self.dpg.set_value("txt_extcsd_dump", "Waiting for result. Retry on error.")
                self._refresh_extcsd_rows()
            self.q.put(("call", apply))

        def result(data, cid):
            source = f"Chip CID: {cid.hex()} | {self._connection_settings()}"
            def apply():
                self._extcsd_settings = self._connection_settings()
                self._show_extcsd(data, source, cid, clear_reference=False)
            self.q.put(("call", apply))

        self.orchestrator.run_read_extcsd(voltage, bus, result, started)

    def write_extcsd(self, index):
        if self.operation_running or not self.extcsd_chip_ready:
            return
        from modes.emmc.extcsd import WRITE_FIELDS, validate_write
        if index not in WRITE_FIELDS:
            return
        try:
            value = int(str(self.dpg.get_value(f"ext_new_{index}")).strip(), 16)
            data, cid = self.extcsd_data, self.extcsd_chip_cid
            settings = self._connection_settings()
            if settings != self._extcsd_settings:
                raise ValueError("Connection settings changed; read EXT_CSD again")
            old = validate_write(data, index, value, allow_otp=True)
        except ValueError as error:
            self._append_log_line(f"[-] EXT_CSD write parameters: {error}")
            return
        if old == value:
            self._append_log_line("[*] EXT_CSD: value already set.")
            return
        prompt_lines = [
            f"Chip CID: {cid.hex()}",
            f"EXT_CSD [{index}] {WRITE_FIELDS[index]}: {old:02X} -> {value:02X}",
            "",
        ]
        if index == 178 and (value & 0x10) and not (old & 0x10):
            prompt_lines += ["Permanent NON-REVERSIBLE boot settings protection. Cannot be undone.", ""]
        if index == 162:
            prompt_lines += [
                "RST_n is one-time: 01/02 may lock NON-REVERSIBLY. The chip may reject a change",
                "of an already-set value or a return to 00; readback follows.", ""]
        prompt_lines.append("Write the field and verify by readback?")
        self._confirm("\n".join(prompt_lines),
                      lambda: self._run_write_extcsd(index, value, data, cid),
                      danger=index in (162, 178))

    def _run_write_extcsd(self, index, value, data, cid):
        source = self.dpg.get_value("txt_extcsd_source")

        def started():
            def apply():
                self.extcsd_chip_ready = False
                self.extcsd_chip_cid = None
                self.extcsd_ready = False
                self.extcsd_data = None
                self.dpg.set_value("txt_extcsd_source", "Writing EXT_CSD; re-read on error")
                self.dpg.set_value("txt_extcsd_dump", "Waiting for write verification.")
                self._refresh_extcsd_rows()
            self.q.put(("call", apply))

        pending = dict(self.extcsd_drafts)
        reference = dict(self.extcsd_reference)

        def result(actual, actual_cid):
            def apply():
                self._show_extcsd(actual, source, actual_cid, clear_reference=True)
                self.extcsd_drafts.update({i: v for i, v in pending.items() if i != index})
                self.extcsd_reference = reference
                self._refresh_extcsd_rows()
            self.q.put(("call", apply))

        self.orchestrator.run_write_extcsd(
            self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
            index, value, data, cid, result, started_cb=started,
            allow_otp=(index in (162, 178)))

    def open_extcsd(self, compare=False, path=None):
        if self.operation_running or (compare and not self.extcsd_ready):
            return
        if path is None:
            self._file_dialog(st.S("dlg_extcsd_file"), extensions=[".bin"],
                              callback=lambda p: self.open_extcsd(compare=compare, path=p))
            return
        try:
            from modes.emmc.extcsd import load_file, describe, compare as compare_data
            data, tail = load_file(path)
            if compare:
                text = (describe(self.extcsd_data) + "\n\nCompared with: " + str(path)
                        + "\n" + compare_data(self.extcsd_data, data))
                self.dpg.set_value("txt_extcsd_dump", _clean_text(text))
                self.extcsd_reference = {i: f"{data[i]:02X}" for i in _EXT_FIELD_ORDER}
                count = sum(a != b for a, b in zip(self.extcsd_data, data))
                self.dpg.set_value("txt_extcsd_source",
                                   f"Compare: {path}\nDiffering bytes: {count} of 512.")
            else:
                if not self.extcsd_chip_ready:
                    self._show_extcsd(data, "File loaded. Read EXT_CSD from the chip to enable writing.",
                                      file_tail=tail, clear_reference=True)
                    self.extcsd_values = {}
                self._extcsd_import = (data, str(path))
                self._apply_extcsd_import()
                self._manual_write_files["EXTCSD"] = str(path)
                self.refresh_write_files()
        except (OSError, ValueError) as error:
            self._append_log_line(f"[-] EXT_CSD open: {error}")
        self._refresh_extcsd_rows()

    def save_extcsd(self):
        if self.operation_running or not self.extcsd_ready:
            return
        self._file_dialog(st.S("dlg_save_extcsd"), save=True, default_filename="extcsd.bin",
                          extensions=[".bin"], callback=self._save_extcsd_to)

    def _save_extcsd_to(self, path):
        try:
            raw = self.extcsd_data + self.extcsd_file_tail
            Path(path).write_bytes(raw)
            self._append_log_line(f"[+] EXT_CSD saved ({len(raw)} bytes): {path}")
        except OSError as error:
            self._append_log_line(f"[-] EXT_CSD save: {error}")

    def _apply_extcsd_import(self):
        if self._extcsd_import is None:
            return
        data, path = self._extcsd_import
        self.extcsd_reference = {i: f"{data[i]:02X}" for i in _EXT_FIELD_ORDER}
        self.extcsd_drafts = dict(self.extcsd_reference)
        comparison = "File: " + path
        if self.extcsd_chip_ready and self.extcsd_data is not None:
            count = sum(a != b for a, b in zip(self.extcsd_data, data))
            comparison += f"\nDiffering bytes: {count} of 512."
        self.dpg.set_value("txt_extcsd_source", _clean_text(comparison))
        self._refresh_extcsd_rows()

    def _prepare_write_extcsd_file(self):
        from modes.emmc.extcsd import load_file, write_plan, WRITE_FIELDS
        row = self.write_files["EXTCSD"]
        if not row["ready"]:
            self._append_log_line("[!] EXT_CSD: " + row["status"])
            return None
        settings = self._connection_settings()
        if not self.extcsd_chip_ready or settings != self._extcsd_settings:
            self._append_log_line("[!] Run chip analyze or read EXT_CSD from the chip first.")
            return None
        try:
            target, _ = load_file(row["path"])
            snapshot, cid = bytes(self.extcsd_data), bytes(self.extcsd_chip_cid)
            plan = write_plan(snapshot, target)
        except (OSError, ValueError) as error:
            self._append_log_line(f"[-] EXT_CSD: {error}")
            return None
        if plan:
            lines = [f"CID: {cid.hex()}", f"File: {row['path']}", ""]
            lines += [f"[{i}] {WRITE_FIELDS[i]}: {old:02X} -> {value:02X}"
                      for i, old, value in plan]
            if any(i == 162 for i, _, _ in plan):
                lines.append("RST_N_FUNCTION: 01/02 may lock NON-REVERSIBLY; readback follows.")
            if any(i == 178 and value & 0x10 for i, _, value in plan):
                lines.append("Permanent boot protection is NON-REVERSIBLE.")
            lines += ["", "Field 160 is never written; PARTITION_ACCESS is preserved.",
                      "Apply these EXT_CSD settings with readback check?"]
            # Modal confirmation is asynchronous in DPG; the write itself is
            # queued from the Yes handler, so this path only needs to know
            # that the plan was shown and NOT accepted yet. To keep the
            # legacy one-shot contract, run a nested mini-loop over the DPG
            # render until the user answers.
            if not self._confirm_blocking("\n".join(lines)):
                return None
        self._extcsd_import = (target, row["path"])
        self._apply_extcsd_import()
        return snapshot, cid, target

    def start_write_extcsd_file(self):
        if not self._need_idle():
            return
        self.refresh_write_files()
        payload = self._prepare_write_extcsd_file()
        if payload is None:
            return
        self.operation_running = True
        try:
            started = self.orchestrator.run_write_extcsd_file(
                self.dpg.get_value("chk_voltage"), self.dpg.get_value("combo_bus"),
                payload, result_cb=self._write_extcsd_file_result)
            if started is False:
                self.operation_running = False
        except Exception:
            self.operation_running = False
            raise

    def _write_extcsd_file_result(self, data, cid):
        def apply():
            self._show_extcsd(data, "Chip CID: " + cid.hex(), cid, clear_reference=True)
            self._apply_extcsd_import()
        self.q.put(("call", apply))

    # ------------------------------------------------------------------
    # Erase tab
    # ------------------------------------------------------------------

    _ERASE_CANONICAL = {st.S("area_user_all"): "USER_ALL", "BOOT1": "BOOT1",
                        "BOOT2": "BOOT2", "Custom LBA": "CUSTOM"}

    def _erase_target_canonical(self, value):
        return self._ERASE_CANONICAL.get(value, "USER_ALL")

    def on_erase_target_changed(self, sender, value):
        dpg = self.dpg
        target = self._erase_target_canonical(value)
        if target in ("BOOT1", "BOOT2"):
            sec_count = (self.boot_size_bytes // P.SECTOR_SIZE) if self.boot_size_bytes > 0 else 8192
            dpg.set_value("erase_start", "0")
            dpg.set_value("erase_end", str(sec_count - 1))
        elif target == "USER_ALL":
            dpg.set_value("erase_start", "0")
            dpg.set_value("erase_end", str(self.user_total_sectors - 1) if self.user_total_sectors > 0 else "0")

    def start_erase(self):
        dpg = self.dpg
        target = self._erase_target_canonical(dpg.get_value("erase_target"))
        raw_start = str(dpg.get_value("erase_start")).strip()
        raw_end = str(dpg.get_value("erase_end")).strip()
        try:
            start_lba = int(raw_start)
        except ValueError:
            start_lba = 0
        if target == "USER_ALL" and not raw_end.isdigit():
            end_lba = self.user_total_sectors - 1 if self.user_total_sectors > 0 else 0
        else:
            try:
                end_lba = int(raw_end)
            except ValueError:
                end_lba = 0
        if end_lba > 0 and end_lba < start_lba:
            self._append_log_line("[!] End LBA must not be lower than start LBA.")
            return
        part_type = "BOOT1" if target == "BOOT1" else ("BOOT2" if target == "BOOT2" else "USER")
        self.orchestrator.run_erase_task(
            dpg.get_value("chk_voltage"), dpg.get_value("combo_bus"),
            part_type, start_lba, end_lba)

    # ------------------------------------------------------------------
    # Scatter -> GPT
    # ------------------------------------------------------------------

    def create_gpt_from_scatter(self):
        self._file_dialog(st.S("dlg_scatter"), extensions=[".xml", ".txt"],
                          callback=self._scatter_picked)

    def _scatter_picked(self, scatter_path):
        self._file_dialog(st.S("dlg_save_gpt"), save=True,
                          default_filename="gpt.bin", extensions=[".bin"],
                          callback=lambda p: self._scatter_to_gpt(scatter_path, p))

    def _scatter_to_gpt(self, scatter_path, out_path):
        user_mb = (self.user_total_sectors * P.SECTOR_SIZE) // (1024 * 1024) \
            if self.user_total_sectors > 0 else 0
        self.orchestrator.run_scatter_to_gpt(scatter_path, out_path, user_mb)

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def _file_dialog(self, title, save=False, directory=False, extensions=None,
                     default_filename="", callback=None):
        # Native Windows dialogs through tkinter (familiar to the user),
        # same withdraw/topmost pattern the legacy Kivy gui used. The
        # call blocks the DPG render loop until the dialog closes, which
        # is safe: nothing else in the GUI is interactive while a file
        # operation is being set up.
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if directory:
                path = filedialog.askdirectory(title=title)
            elif save:
                ext = (extensions or [".bin"])[0].lstrip(".")
                path = filedialog.asksaveasfilename(
                    title=title, initialfile=default_filename,
                    defaultextension="." + ext,
                    filetypes=self._filetypes(extensions))
            else:
                path = filedialog.askopenfilename(
                    title=title, filetypes=self._filetypes(extensions))
        finally:
            root.destroy()
        if path:
            callback(path)

    @staticmethod
    def _filetypes(extensions):
        if not extensions:
            return [("All files", "*.*")]
        pairs = [("Images", " ".join("*" + e.lstrip(".") for e in extensions))]
        pairs.append(("All files", "*.*"))
        return pairs

    def _confirm(self, message, on_yes, danger=False):
        dpg = self.dpg
        self._dlg_seq += 1
        tag = f"confirm_{self._dlg_seq}"

        def _yes():
            dpg.delete_item(tag)
            on_yes()

        def _no():
            dpg.delete_item(tag)

        with dpg.window(modal=True, title=st.S("confirm"), tag=tag, width=560, no_resize=True):
            color = COL["error"] if danger else COL["text"]
            for line in message.splitlines():
                t = dpg.add_text(_clean_text(line), color=color)
                self._bind_cyr(t)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label=st.S("yes"), width=90, callback=_yes)
                dpg.add_button(label=st.S("no"), width=90, callback=_no)

    def _confirm_blocking(self, message):
        # A one-shot synchronous ask over the DPG render loop: needed where
        # the caller must branch immediately (EXT_CSD write plan).
        dpg = self.dpg
        self._dlg_seq += 1
        tag = f"confirm_block_{self._dlg_seq}"
        answer = {"yes": False}

        def _yes():
            answer["yes"] = True
            dpg.delete_item(tag)

        def _no():
            dpg.delete_item(tag)

        with dpg.window(modal=True, title=st.S("confirm_plan"), tag=tag, width=560,
                        no_resize=True):
            for line in message.splitlines():
                t = dpg.add_text(_clean_text(line), color=COL["error"])
                self._bind_cyr(t)
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label=st.S("yes"), width=90, callback=_yes)
                dpg.add_button(label=st.S("no"), width=90, callback=_no)
        while dpg.does_item_exist(tag) and dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
        return answer["yes"]

    # ------------------------------------------------------------------
    # Theme / fonts
    # ------------------------------------------------------------------

    def _theme(self):
        dpg = self.dpg
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, COL["window_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, COL["child_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 55, 70))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (65, 80, 100))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (85, 100, 120))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, COL["frame_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_Text, COL["text"])
                # Header drives the selected/hovered background of selectables
                # (partition rows): amber, not the legacy bluish header.
                dpg.add_theme_color(dpg.mvThemeCol_Header, COL["selection_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, COL["selection_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, COL["selection_active"])
                # tabs: amber selected/unfocused, dimmed otherwise
                dpg.add_theme_color(dpg.mvThemeCol_TabSelected, COL["send_btn"])
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered, COL["send_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_Tab, COL["frame_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_TabUnfocused, COL["frame_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_TabUnfocusedActive, (35, 55, 35))
                dpg.add_theme_color(dpg.mvThemeCol_TabDimmedSelected, COL["send_btn"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, COL["window_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (30, 32, 40))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 4)
        dpg.bind_theme(global_theme)
        with dpg.theme(tag="button_theme_send"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL["send_btn"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL["send_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL["send_active"])
        with dpg.theme(tag="button_theme_reset"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL["reset_btn"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL["reset_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL["reset_active"])
        with dpg.theme(tag="ext_field_selected"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL["header"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL["header"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL["header"])
        with dpg.theme(tag="ext_field_unselected"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL["frame_bg"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (50, 60, 75))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL["frame_bg"])

    def _bind_send(self, tag):
        self.dpg.bind_item_theme(tag, "button_theme_send")

    def _bind_reset(self, tag):
        self.dpg.bind_item_theme(tag, "button_theme_reset")

    def _header(self, text):
        dpg = self.dpg
        t = dpg.add_text(text, color=COL["accent"])
        font_tag = "font_header_cyr" if st.get_lang() == "ru" else "font_header"
        if dpg.does_item_exist(font_tag):
            dpg.bind_item_font(t, font_tag)
        return t

    def _bind_cyr(self, tag, size="chat"):
        # any widget that can show Cyrillic must use the VCR OSD Mono RUS
        # font; the default ModeSeven body font is Latin-only
        dpg = self.dpg
        font_tag = "font_log" if size == "log" else "font_chat"
        if dpg.does_item_exist(tag) and dpg.does_item_exist(font_tag):
            dpg.bind_item_font(tag, font_tag)

    def _rebuild_table(self):
        # DPG tables own their columns as children, so clearing rows alone
        # would drop the header too; the whole table is rebuilt instead.
        dpg = self.dpg
        if not dpg.does_item_exist("parts_table_body"):
            return
        if dpg.does_item_exist("parts_table"):
            dpg.delete_item("parts_table")
        with dpg.table(tag="parts_table", parent="parts_table_body", header_row=True,
                       row_background=True, borders_innerH=True, borders_outerH=True,
                       context_menu_in_body=False, policy=dpg.mvTable_SizingStretchProp,
                       scrollY=False, delay_search=True):
            dpg.add_table_column(label="#", width_fixed=True)
            dpg.add_table_column(label=st.S("col_name"))
            dpg.add_table_column(label="FS")
            dpg.add_table_column(label=st.S("col_lba"))
            dpg.add_table_column(label=st.S("col_size"))
            if not self.table_rows:
                with dpg.table_row():
                    dpg.add_selectable(label="No partition data - run INIT EMMC first",
                                       span_columns=True, enabled=False)
                return
            start_idx = 0 if (self.table_rows and self.table_rows[0].get("is_table")) else 1
            for offset, part in enumerate(self.table_rows):
                idx = start_idx + offset if not part.get("is_table") else 0
                size_mb = float(part.get("size", 0.0))
                if size_mb < 0.1:
                    size_kb = size_mb * 1024
                    size_txt = f"{size_kb:.1f} KB" if size_kb >= 1.0 else f"{int(size_mb * 1024 * 1024)} B"
                else:
                    size_txt = f"{size_mb:.1f} MB"
                with dpg.table_row():
                    sel = dpg.add_selectable(label=str(idx), tag=f"part_row_{offset}",
                                             span_columns=True,
                                             callback=self.on_part_selected, user_data=offset)
                    dpg.bind_item_theme(sel, "part_row_theme")
                    name_txt = dpg.add_text(part.get("name", "(unnamed)"),
                                            tag=f"part_name_{offset}")
                    self._bind_cyr(f"part_name_{offset}")
                    dpg.add_text(part.get("fs", "?"), color=COL["ok"])
                    dpg.add_text(f"{part.get('first', 0)}..{part.get('last', 0)}",
                                 color=COL["lba_blue"])
                    dpg.add_text(size_txt, color=COL["warn"])
            self._apply_row_selection()

    def _build_fonts(self):
        dpg = self.dpg
        try:
            with dpg.font_registry():
                header_font = FONTS_DIR / "ModeSevenBETAVHS20212.ttf"
                body_font = FONTS_DIR / "ModeSevenBETAVHS.ttf"
                chat_font = FONTS_DIR / "VCR_OSD_Mono_RUS-VHS.ttf"
                if header_font.is_file():
                    dpg.add_font(str(header_font), 22, tag="font_header")
                if body_font.is_file():
                    dpg.add_font(str(body_font), 16, tag="font_body")
                if chat_font.is_file():
                    with dpg.font(str(chat_font), 16, tag="font_chat"):
                        pass
                    with dpg.font(str(chat_font), 11, tag="font_log"):
                        pass
                    with dpg.font(str(chat_font), 22, tag="font_header_cyr"):
                        pass
                nerd_font = FONTS_DIR / "JetBrainsMonoNerdFont-Regular.ttf"
                if nerd_font.is_file():
                    # DPG loads no Cyrillic by default; map the Cyrillic
                    # block onto the free Latin-1 supplement range.
                    with dpg.font(str(nerd_font), 15, tag="font_nerd"):
                        big_let_start = 0x00C0
                        big_let_end = 0x00DF
                        remap_big_let = 0x0410
                        alph_len = big_let_end - big_let_start + 1
                        biglet = remap_big_let
                        for i in range(big_let_start, big_let_end + 1):
                            dpg.add_char_remap(i, biglet)
                            dpg.add_char_remap(i + alph_len, biglet + alph_len)
                            biglet += 1
                    bar_font = DpgGui._find_bar_font()
                    if bar_font:
                        with dpg.font(str(bar_font), 14, tag="font_bar"):
                            pass
                        DpgGui._bar_font_path = bar_font
                    else:
                        DpgGui._bar_font_path = None
            if dpg.does_item_exist("font_body"):
                dpg.bind_font("font_body")
            else:
                fallback = find_available_font()
                if fallback:
                    with dpg.font_registry():
                        with dpg.font(str(fallback), 16, tag="font_fallback"):
                            pass
                    dpg.bind_font("font_fallback")
        except Exception as e:
            print(f"[GUI] font registration failed ({e}); using DPG default font", flush=True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_static(self):
        dpg = self.dpg
        with dpg.texture_registry(show=False):
            logo_path = ASSETS_DIR / "xgecu_prog_cool2.png"
            if not logo_path.is_file():
                logo_path = ASSETS_DIR / "xgecu_prog.png"
            if logo_path.is_file():
                from PIL import Image
                img = Image.open(logo_path).convert("RGBA")
                self._logo_ratio = img.size[0] / img.size[1]
                dpg.add_dynamic_texture(img.size[0], img.size[1],
                                        [b / 255.0 for b in img.tobytes("raw", "RGBA")],
                                        tag="logo_tex")
        self._theme()
        self._build_fonts()

        def _set_flag(name, value):
            def _cb(sender, app_data):
                setattr(self, name, value)
            return _cb
        with dpg.handler_registry():
            for key in (dpg.mvKey_LShift, dpg.mvKey_RShift):
                dpg.add_key_down_handler(key, callback=_set_flag("_mod_shift", True))
                dpg.add_key_release_handler(key, callback=_set_flag("_mod_shift", False))
            for key in (dpg.mvKey_LControl, dpg.mvKey_RControl):
                dpg.add_key_down_handler(key, callback=_set_flag("_mod_ctrl", True))
                dpg.add_key_release_handler(key, callback=_set_flag("_mod_ctrl", False))

    def _build_window(self):
        dpg = self.dpg
        # RU interface renders in VCR OSD Mono RUS; ModeSeven is Latin-only
        dpg.bind_font("font_chat" if st.get_lang() == "ru" else "font_body")
        with dpg.window(tag="main_window", no_title_bar=True, no_move=True,
                        no_scrollbar=True):
            dpg.set_primary_window("main_window", True)

            # header
            with dpg.child_window(tag="header_child", height=62, border=False,
                                  no_scrollbar=True):
                with dpg.table(tag="header_table", header_row=False, borders_innerH=False,
                               borders_outerH=False, context_menu_in_body=False,
                               policy=dpg.mvTable_SizingFixedFit):
                    dpg.add_table_column(width_stretch=True, init_width_or_weight=1)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=560,
                                         no_resize=True)
                    with dpg.table_row():
                        with dpg.group(horizontal=True):
                            if dpg.does_item_exist("logo_tex"):
                                logo_h = 44
                                logo_w = int(logo_h * getattr(self, "_logo_ratio", 1.0))
                                dpg.add_image("logo_tex", height=logo_h, width=logo_w)
                            title = dpg.add_text(f"XGECU PROG v{APP_VERSION} - T48 eMMC FLASHER",
                                                 color=COL["accent"])
                            if dpg.does_item_exist("font_header"):
                                dpg.bind_item_font(title, "font_header")
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=-1)
                            lang_ru = dpg.add_button(label="RU", tag="btn_lang_ru", width=34,
                                                     callback=lambda s, a: self.set_lang("ru"))
                            lang_en = dpg.add_button(label="EN", tag="btn_lang_en", width=34,
                                                     callback=lambda s, a: self.set_lang("en"))
                            self._refresh_lang_buttons()
                            dpg.add_spacer(width=12)
                            with dpg.drawlist(width=16, height=16):
                                dpg.draw_circle(center=(8, 8), radius=5, tag="t48_lamp",
                                                color=COL["text"] + (255,),
                                                fill=COL["lamp_error"] + (255,))
                            dpg.add_spacer(width=6)
                            dpg.add_text(st.S("state_label"))
                            dpg.add_text("OFFLINE", tag="t48_state_value", color=COL["lamp_error"])
                            dpg.add_spacer(width=10)
                            dpg.add_text(st.S("firmware_label"))
                            dpg.add_text("-", tag="t48_fw_value", color=COL["idle"])

            # mode tabs
            with dpg.child_window(border=False, height=-56, no_scrollbar=True):
                with dpg.tab_bar(tag="mode_pages", callback=self._on_mode_tab):
                    with dpg.tab(label=st.S("tab_emmc"), tag="tab_emmc"):
                        self._build_emmc_page()
                    with dpg.tab(label=st.S("tab_nand"), tag="tab_nand"):
                        dpg.add_text(st.S("mode_nand_soon"), color=COL["idle"])
                    with dpg.tab(label=st.S("tab_spi"), tag="tab_spi"):
                        dpg.add_text(st.S("mode_spi_soon"), color=COL["idle"])

            # bottom bar: state + STOP
            with dpg.child_window(height=50, border=False, no_scrollbar=True):
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=10)
                    dpg.add_text("State:", color=COL["idle"])
                    dpg.add_text("Ready", tag="status_phase", color=COL["idle"])
                    dpg.add_spacer(width=-1)
                    stop_btn = dpg.add_button(label="STOP / RESET", width=180, height=30,
                                              callback=self.stop_operation)
                    self._bind_reset(stop_btn)
                    dpg.add_spacer(width=10)
        self._rebuild_table()
        self._refresh_busy_state()
        self._refresh_write_file_rows()
        self._refresh_extcsd_rows()
        self._log_dirty = True

    def build(self):
        self._build_static()
        self._build_window()
        # Initialize preset state (disable clock for Auto preset)
        self.on_preset_changed(None, self._preset_display())
        dpg = self.dpg
        dpg.create_viewport(title=APP_TITLE, width=1280, height=820, resizable=True)
        icon_path = ASSETS_DIR / "xgecu_prog.ico"
        if icon_path.is_file():
            try:
                dpg.set_viewport_small_icon(str(icon_path))
                dpg.set_viewport_large_icon(str(icon_path))
            except Exception:
                pass
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_frame_callback(dpg.get_frame_count() + 1, self._first_frame)

    def set_lang(self, lang):
        if st.get_lang() == lang:
            return
        st.set_lang(lang)
        _save_lang(lang)
        dpg = self.dpg
        if dpg.does_item_exist("main_window"):
            dpg.delete_item("main_window")
        self._build_window()
        self._rebuild_table()
        self._log_dirty = True
        self._refresh_busy_state()
        self._refresh_write_file_rows()
        self._refresh_extcsd_rows()

    def _refresh_lang_buttons(self):
        dpg = self.dpg
        active = {"ru": "btn_lang_ru", "en": "btn_lang_en"}[st.get_lang()]
        other = {"ru": "btn_lang_en", "en": "btn_lang_ru"}[st.get_lang()]
        if dpg.does_item_exist(active):
            dpg.bind_item_theme(active, "button_theme_send")
        if dpg.does_item_exist(other):
            dpg.bind_item_theme(other, 0)

    def _on_mode_tab(self, sender, value):
        mapping = {"tab_emmc": "eMMC", "tab_nand": "NAND", "tab_spi": "SPI"}
        mode = mapping.get(value)
        if mode and self.orchestrator:
            self.orchestrator.set_mode(mode)

    def _first_frame(self):
        self._gui_ready = True
        self._log_dirty = True
        self._rebuild_table()
        self._refresh_busy_state()
        self._refresh_extcsd_rows()
        print("[GUI] render ready", flush=True)
        self.dpg.set_frame_callback(self.dpg.get_frame_count() + 1, self._drain_queue)

    def _build_emmc_page(self):
        dpg = self.dpg
        with dpg.child_window(border=False, no_scrollbar=True, height=-1):
            # toolbar
            with dpg.child_window(height=46, border=False, no_scrollbar=True):
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=10)
                    dpg.add_text(st.S("vccq"))
                    dpg.add_checkbox(tag="chk_voltage", default_value=True)
                    dpg.add_spacer(width=10)
                    dpg.add_text(st.S("bus"))
                    dpg.add_combo(["1-bit", "4-bit"], tag="combo_bus", default_value="4-bit", width=90)
                    dpg.add_spacer(width=10)
                    dpg.add_text(st.S("clock"))
                    dpg.add_combo(self._clock_values(), tag="combo_clock",
                                  default_value=(self._preset_clocks.get(self.emmc_preset_display)
                                                  if self._preset_clocks.get(self.emmc_preset_display)
                                                  in self._clock_values() else st.S("clock_30")),
                                  width=130,
                                  enabled=(self.emmc_preset_display != "Auto"),
                                  callback=lambda s, a: self.on_clock_changed(s, a))
                    dpg.add_spacer(width=10)
                    dpg.add_text(st.S("preset"))
                    dpg.add_combo(self._preset_values(), tag="combo_preset",
                                  default_value=self._preset_display(),
                                  width=120,
                                  callback=lambda s, a: self.on_preset_changed(s, a))
                    dpg.add_spacer(width=10)
                    dpg.add_button(label="Scatter -> GPT", tag="btn_scatter_gpt",
                                   callback=self.create_gpt_from_scatter)

            # horizontal split: work area | log
            with dpg.group(horizontal=True):
                # LEFT: sub-tabs READ / WRITE / ERASE
                with dpg.child_window(width=-570, border=False):
                    with dpg.tab_bar(tag="emmc_subtabs"):
                        with dpg.tab(label=st.S("sub_read"), tag="sub_read"):
                            with dpg.group(horizontal=True):
                                dpg.add_checkbox(tag="chk_verify_read", default_value=False)
                                dpg.add_text(st.S("verify_read"))
                            with dpg.group(horizontal=True):
                                init_btn = dpg.add_button(label=st.S("btn_init"), tag="btn_init_emmc",
                                                          callback=self.start_analyze, height=30)
                                self._bind_send(init_btn)
                                dpg.add_button(label=st.S("btn_read_userdata"), tag="btn_read_userdata",
                                               callback=self.dump_userdata)
                                dpg.add_button(label="BOOT1", tag="btn_read_boot1",
                                               callback=lambda: self.dump_boot("BOOT1"))
                                dpg.add_button(label="BOOT2", tag="btn_read_boot2",
                                               callback=lambda: self.dump_boot("BOOT2"))
                            dpg.add_button(label=st.S("btn_full_read"),
                                           tag="btn_full_read", width=-1, callback=self.dump_all)
                            dpg.add_spacer(height=6)
                            self._header(st.S("partitions"))
                            with dpg.child_window(tag="parts_table_body", height=-80, border=True):
                                pass
                            dpg.add_text(st.S("selected_none"), tag="selected_part_text",
                                         color=COL["accent"])
                            dpg.add_text(st.S("sel_hint"), color=COL["idle"])
                            with dpg.group(horizontal=True):
                                dpg.add_button(label=st.S("btn_dump"), tag="btn_dump_sel",
                                               callback=lambda s, a: self.action_read_part())
                                dpg.add_button(label=st.S("btn_write"), tag="btn_write_sel",
                                               callback=lambda s, a: self.action_write_part())
                                erase_sel = dpg.add_button(label=st.S("btn_erase"), tag="btn_erase_sel",
                                                           callback=lambda s, a: self.action_erase_part())
                                self._bind_reset(erase_sel)

                        with dpg.tab(label=st.S("sub_write"), tag="sub_write"):
                            with dpg.child_window(height=-1, border=False):
                                with dpg.group(horizontal=True):
                                    dpg.add_checkbox(tag="chk_verify_write", default_value=True)
                                    dpg.add_text(st.S("verify_write"))
                                with dpg.group(horizontal=True):
                                    dpg.add_checkbox(tag="chk_erase_before_write", default_value=True)
                                    dpg.add_text(st.S("erase_before"))
                                dpg.add_spacer(height=6)
                                dpg.add_text(st.S("images_folder"), color=COL["accent"])
                                with dpg.group(horizontal=True):
                                    folder_input = dpg.add_input_text(tag="txt_write_folder", default_value="",
                                                                      hint=st.S("no_folder"), width=-130,
                                                                      readonly=True)
                                    self._bind_cyr("txt_write_folder")
                                    dpg.add_button(label=st.S("browse"), tag="btn_select_write_folder",
                                                   width=110, callback=lambda s, a: self.select_write_folder())
                                with dpg.group(horizontal=True):
                                    dpg.add_button(label=st.S("btn_refresh"), tag="btn_refresh_files",
                                                   callback=lambda s, a: self.refresh_write_files())
                                    init_btn2 = dpg.add_button(label=st.S("btn_init"),
                                                               callback=lambda s, a: self.start_analyze())
                                    self._bind_send(init_btn2)
                                dpg.add_button(
                                    label=st.S("btn_write_chip"),
                                    tag="btn_write_all", width=-1,
                                    callback=lambda s, a: self.start_write_all(), enabled=False)
                                dpg.add_text(st.S("write_rules"), color=COL["idle"], wrap=480)
                                dpg.add_spacer(height=6)
                                for key, title, tag in (
                                        ("BOOT1", "BOOT1", "boot1"),
                                        ("BOOT2", "BOOT2", "boot2"),
                                        ("USER", "Userdata", "userdata"),
                                        ("EXTCSD", "EXT_CSD (512 / 544 bytes)", "extcsd")):
                                    with dpg.group(horizontal=True):
                                        dpg.add_text(title)
                                        dpg.add_spacer(width=70)
                                        file_input = dpg.add_input_text(tag=f"txt_write_{tag}", default_value="",
                                                                        width=-200, readonly=True,
                                                                        hint=st.S("not_selected").format(AREA_NAMES[key]))
                                        self._bind_cyr(f"txt_write_{tag}")
                                        dpg.add_button(label="File...", tag=f"btn_pick_{tag}", width=80,
                                                       user_data=key,
                                                       callback=lambda s, a, u: self.select_write_file(u))
                                        dpg.add_button(label=st.S("btn_write"), tag=f"btn_write_{tag}",
                                                       width=90, enabled=False, user_data=key,
                                                       callback=lambda s, a, u: self.start_write(u))
                                    dpg.add_text("", tag=f"status_txt_write_{tag}", color=COL["idle"])
                                    self._bind_cyr(f"status_txt_write_{tag}")
                                dpg.add_spacer(height=6)
                                self._header(st.S("extcsd_fields"))
                                self._build_extcsd_table()

                        with dpg.tab(label=st.S("sub_erase"), tag="sub_erase"):
                            dpg.add_spacer(height=6)
                            self._header(st.S("hardware_erase"))
                            with dpg.group(horizontal=True):
                                dpg.add_text(st.S("area"))
                                dpg.add_combo([st.S("area_user_all"), "BOOT1", "BOOT2", "Custom LBA"],
                                              tag="erase_target",
                                              default_value=st.S("area_user_all"),
                                              width=180,
                                              callback=lambda s, a: self.on_erase_target_changed(s, a))
                            with dpg.group(horizontal=True):
                                dpg.add_text(st.S("start_lba"))
                                dpg.add_input_text(tag="erase_start", default_value="0", width=110)
                                dpg.add_text(st.S("end_lba"))
                                dpg.add_input_text(tag="erase_end", default_value="0", width=140)
                            dpg.add_spacer(height=8)
                            erase_btn = dpg.add_button(label=st.S("btn_erase_area"), width=280,
                                                       height=36, tag="btn_erase_run",
                                                       callback=lambda s, a: self.start_erase())
                            self._bind_reset(erase_btn)

                # RIGHT: journal + progress
                with dpg.child_window(width=560, border=False):
                    with dpg.group(horizontal=True):
                        self._header(st.S("operation_log"))
                        dpg.add_spacer(width=-1)
                        dpg.add_button(label=st.S("btn_copy"), width=80,
                                       callback=lambda s, a: self.copy_log())
                        dpg.add_button(label=st.S("btn_clear"), width=80,
                                       callback=lambda s, a: self.clear_log())
                    with dpg.group(horizontal=True):
                        dpg.add_combo([st.S("log_level_all"), "INFO", "OK", "WARN", "ERROR"],
                                      tag="combo_log_level",
                                      default_value=st.S("log_level_all"), width=90,
                                      callback=lambda s, a: setattr(self, "_log_dirty", True))
                        dpg.add_input_text(tag="input_log_search", hint="Search in log",
                                           width=-1,
                                           callback=lambda s, a: setattr(self, "_log_dirty", True))
                    dpg.add_text("", tag="log_stats_text", color=COL["idle"])
                    with dpg.child_window(tag="log_scroll", height=-70, border=True):
                        with dpg.group(tag="log_lines_group"):
                            dpg.add_text("Ready. Select memory and mode.", color=COL["idle"])
                    self._bind_cyr("log_lines_group", size="log")
                    # OctoGirl-style: the text bar IS the progress display
                    # (native add_progress_bar removed); width follows the
                    # panel via a resize handler so it spans the same row.
                    with dpg.group(horizontal=True, tag="progress_row"):
                        textbar = dpg.add_text("[▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱]   0%",
                                               tag="progress_textbar", color=COL["accent"])
                        if dpg.does_item_exist("font_bar"):
                            dpg.bind_item_font(textbar, "font_bar")
                        dpg.add_spacer(width=-1)
                        dpg.add_text("0.00%", tag="progress_percent_text", color=COL["idle"])
                        dpg.add_text("0.00 MiB/s", tag="progress_speed_text", color=COL["idle"])
                    with dpg.item_handler_registry() as progress_reg:
                        dpg.add_item_resize_handler(callback=self._on_progress_row_resize)
                    dpg.bind_item_handler_registry("progress_row", progress_reg)

    def _build_extcsd_table(self):
        dpg = self.dpg
        from modes.emmc.extcsd import WRITE_FIELDS
        labels = dict(WRITE_FIELDS)
        labels[160] = "PARTITIONING_SUPPORT (RO)"
        with dpg.table(header_row=True, row_background=True, borders_innerH=True,
                       borders_outerH=True, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label=st.S("col_field"))
            dpg.add_table_column(label=st.S("col_chip"))
            dpg.add_table_column(label=st.S("col_file"))
            dpg.add_table_column(label=st.S("col_new"))
            dpg.add_table_column(label=st.S("col_action"))
            for index in _EXT_FIELD_ORDER:
                with dpg.table_row():
                    dpg.add_button(label=f"{index} {labels[index]}", tag=f"ext_field_{index}",
                                   user_data=index,
                                   callback=lambda s, a, u: self.select_extcsd_field(u))
                    dpg.add_text("--", tag=f"ext_chip_{index}")
                    dpg.add_text("--", tag=f"ext_file_{index}")
                    dpg.add_input_text(tag=f"ext_new_{index}", default_value="", width=64,
                                       enabled=False, user_data=index,
                                       callback=lambda s, a, u: self.edit_extcsd_value(u, a))
                    write_btn = dpg.add_button(
                        label=st.S("btn_field_read") if index == 160 else st.S("btn_field_write"),
                        tag=f"ext_write_{index}", width=70, enabled=False, user_data=index,
                        callback=lambda s, a, u: (self.read_extcsd() if u == 160
                                                  else self.write_extcsd(u)))
                    if index == 160:
                        self._bind_send(write_btn)
                    else:
                        self._bind_reset(write_btn)
        dpg.add_text("", tag="txt_extcsd_hint", color=COL["warn"], wrap=480)
        dpg.add_text("", tag="txt_extcsd_source", color=COL["text_dim"], wrap=480)
        self._bind_cyr("txt_extcsd_source")
        with dpg.group(horizontal=True):
            dpg.add_button(label=st.S("btn_open_file"), tag="btn_extcsd_open",
                           callback=lambda s, a: self.open_extcsd(compare=False))
            dpg.add_button(label=st.S("btn_compare"), tag="btn_extcsd_compare",
                           callback=lambda s, a: self.open_extcsd(compare=True))
            dpg.add_button(label=st.S("btn_save_snapshot"), tag="btn_extcsd_save",
                           callback=lambda s, a: self.save_extcsd())
        dpg.add_spacer(height=4)
        with dpg.child_window(height=520, border=True):
            dpg.add_text("", tag="txt_extcsd_dump", wrap=520)
        self._bind_cyr("txt_extcsd_dump")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def stop_operation(self):
        self.orchestrator.stop_operation()

    def _demo_tick(self):
        orch = self.orchestrator
        if isinstance(orch, DemoOrchestrator):
            orch.tick()
        else:
            self._drain_queue()
        if self.dpg.is_dearpygui_running():
            self.dpg.set_frame_callback(self.dpg.get_frame_count() + 1, self._demo_tick)

    def run(self, demo=False):
        dpg = self.dpg
        dpg.create_context()
        if demo:
            self.orchestrator = DemoOrchestrator(self)
        else:
            from orchestrator import AppOrchestrator
            self.orchestrator = AppOrchestrator(
                log_cb=self.log_cb, table_cb=self.table_cb, task_cb=self.task_cb,
                progress_cb=self.progress_cb, phase_cb=self.phase_cb)
        self.build()
        if demo:
            self._append_log_line("[+] DEMO MODE: hardware calls are simulated.")
            self._append_log_line("[*] Press INIT EMMC to run the scripted chip read.")
        else:
            self._append_log_line("[+] Xgecu Prog started (DearPyGui frontend).")
            self._append_log_line("[*] Press INIT EMMC to probe the chip.")
        self._log_dirty = True
        if demo:
            dpg.set_frame_callback(dpg.get_frame_count() + 1, self._demo_tick)
        try:
            while dpg.is_dearpygui_running():
                dpg.render_dearpygui_frame()
        finally:
            dpg.destroy_context()


# ======================================================================
# Demo mode (--demo): scripted chip read through the real GUI callbacks.
# ======================================================================

_SECTOR = 512

_DEMO_LAYOUT_ENTRIES = [
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
    ("userdata", 3290112000, 24556346880 // _SECTOR),
]

_DEMO_FS_BY_NAME = {
    "boot_a": "Android boot", "vendor_boot_a": "Android boot",
    "super": "f2fs/dm", "userdata": "f2fs/dm", "custpack": "f2fs/dm",
    "metadata": "ext4", "sp_data": "ext4",
    "preloader": "raw", "pgpt": "raw", "misc": "raw", "para": "raw",
    "seccfg": "raw", "lk_a": "raw",
}


class DemoOrchestrator:
    """Orchestrator stand-in: INIT EMMC replays a scripted chip read
    (real MT6768 scatter layout, synthetic EXT_CSD) through the same
    GUI callbacks the backend uses; other run_* calls report idle."""

    def __init__(self, gui):
        self._gui = gui
        self._dpg = gui.dpg
        self._events = []
        self._cursor = 0
        self._start = None

    def set_mode(self, mode):
        pass

    def stop_operation(self):
        self._gui.log_cb("[*] STOP: demo mode, nothing to stop.")

    def run_read_info(self, voltage, bus, result_cb=None):
        if self._start is not None:
            self._gui.log_cb("[*] INIT EMMC: demo already ran; restart to replay.")
            return
        self._build_scenario()
        self._start = self._dpg.get_frame_count()

    def __getattr__(self, name):
        if name.startswith("run_"):
            def _demo(*args, **kwargs):
                self._gui.log_cb("[!] Demo mode: only the INIT EMMC scenario is scripted.")
            return _demo
        raise AttributeError(name)

    def _build_scenario(self):
        gui = self._gui
        events = self._events
        at = lambda rel, fn: events.append((rel, fn))
        log = lambda msg: (lambda: gui.log_cb(msg))
        snapshot = self._build_extcsd_snapshot()
        user_sectors = 0x03A00000   # 29.0 GiB User Area

        at(0, log("[*] INIT EMMC: T48 discovery..."))
        at(3, log("[+] T48 found (WinUSB), firmware version 22.09.14"))
        at(5, lambda: gui.task_cb(True))
        at(6, lambda: gui.phase_cb("image analyze"))
        at(6, log("[*] Analyzing: reading CID/CSD/EXT_CSD..."))
        for i in range(7, 37, 6):
            at(i, lambda p=(i - 7) / 30 * 100.0: gui.progress_cb(p, 3.2 + 0.3 * (i % 7)))
        at(21, log("[*] Candidate check: 8 MHz, 4-bit, VCCQ 1.8 V"))
        at(31, log("[+] Candidate accepted: CID match, head/mid/tail reads OK"))
        at(37, lambda: gui.progress_cb(100.0, 3.0))
        at(39, log("[+] Analyze complete. Preset: standard, 30 MHz, 4-bit, VCCQ 1.8 V"))

        def layout():
            parts = [{"is_table": True, "name": "Layout (GPT)", "fs": "GPT",
                      "first": 0, "last": 33, "size": 34 * _SECTOR / 1024 / 1024}]
            for name, start_bytes, sectors in _DEMO_LAYOUT_ENTRIES:
                first = start_bytes // _SECTOR
                parts.append({"name": name, "fs": _DEMO_FS_BY_NAME.get(name, "ext4"),
                              "first": first, "last": first + sectors - 1,
                              "size": sectors * _SECTOR / 1024 / 1024})
            gui.table_cb(parts, boot_bytes=4 * 1024 * 1024,
                         user_mb=user_sectors * _SECTOR // (1024 * 1024),
                         user_sectors=user_sectors)
        at(42, layout)
        at(42, log("[+] GPT layout: 54 partitions, User Area 29.0 GiB, BOOT 4 MiB each"))

        def apply_extcsd():
            cid = snapshot[512:528]
            gui._extcsd_settings = gui._connection_settings()
            gui._show_extcsd(snapshot[:512], "Analyze: CID " + cid.hex(), cid)
            gui._apply_extcsd_import()
        at(45, lambda: gui.q.put(("call", apply_extcsd)))
        at(47, log("[+] EXT_CSD read: 512 bytes, CID 15010050...c700"))

        at(55, log("[*] Reading User Area -> userdata_dump.img (29.0 GiB)..."))
        at(55, lambda: gui.phase_cb("read"))
        for i in range(57, 237, 4):
            frac = (i - 57) / 180.0
            at(i, lambda p=frac * 37.5: gui.progress_cb(p, 24.5 + 2.5 * ((i * 7) % 5)))
        at(237, log("[*] Stop requested by user..."))
        at(239, lambda: gui.phase_cb("verify"))
        at(239, log("[*] Readback verify: first 32 MiB..."))
        for i in range(241, 297, 4):
            frac = (i - 241) / 56.0
            at(i, lambda p=frac * 100.0: gui.progress_cb(p, 61.0 + 1.5 * ((i * 3) % 4)))
        at(297, log("[+] Verify: readback matches"))
        at(299, log("[+] sha256 userdata_dump.img: 9f2c41a7e3d05b68a4f0c2de71b846a5"
                    "e9d3c804fa5b217c6de8091b4a3f7e5d"))
        at(301, lambda: gui.task_cb(False))
        at(301, log("[+] Done. Read stopped at 37.5% of User Area, data valid."))

    @staticmethod
    def _build_extcsd_snapshot():
        d = bytearray(512)
        d[177] = 0x07   # BOOT_BUS_WIDTH: 8-bit, DDR
        d[178] = 0x00   # BOOT_CONFIG_PROT: none
        d[179] = 0x49   # PARTITION_CONFIG: boot from BOOT1, ACK
        d[162] = 0x01   # RST_N_FUNCTION: permanent
        d[160] = 0x01   # PARTITIONING_SUPPORT
        d[212] = 0x00   # SEC_COUNT: 0x03A00000 = 60817408 sectors = 29.0 GiB
        d[213] = 0x00
        d[214] = 0xA0
        d[215] = 0x03
        d[226] = 0x20   # BOOT_SIZE_MULT = 32 -> 4 MiB boot partitions
        d[181] = 0x00   # ERASED_MEM_CONT
        d[168] = 0x60   # EXT_CSD_REV 6.0
        cid = bytes.fromhex("15010050343833314030903032d4c700")
        csd = bytes.fromhex("d07f01320f5903fff6f9cfff8a408000")
        return bytes(d) + cid + csd

    def tick(self):
        # called every frame while the demo scenario is running
        dpg = self._dpg
        frame = dpg.get_frame_count()
        if self._start is not None:
            while self._cursor < len(self._events):
                rel, fn = self._events[self._cursor]
                if self._start + rel > frame:
                    break
                self._cursor += 1
                fn()
        gui = self._gui
        gui._process_queue()
        gui._update_status_widgets()


def main():
    demo = "--demo" in sys.argv
    gui = DpgGui()
    gui.run(demo=demo)


if __name__ == "__main__":
    main()
