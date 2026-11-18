"""Headless-ish smoke: DPG partition table renders rows from table_cb data.

Run: xgecu_env\\Scripts\\python.exe -X utf8 tests\\smoke_dpg_table.py
Requires a desktop session (DPG creates a real viewport for 60 frames).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui_dpg import DpgGui


FAKE_PARTS = [
    {"is_table": True, "name": "GPT", "fs": "GPT", "first": 0, "last": 33, "size": 0.016},
    {"name": "boot", "fs": "ext4", "first": 34, "last": 2047, "size": 0.98},
    {"name": "userdata", "fs": "f2fs", "first": 2048, "last": 60778973, "size": 28771.5},
]


def main():
    gui = DpgGui()
    dpg = gui.dpg
    from orchestrator import AppOrchestrator
    gui.orchestrator = AppOrchestrator(
        log_cb=gui.log_cb, table_cb=gui.table_cb, task_cb=gui.task_cb,
        progress_cb=gui.progress_cb, phase_cb=gui.phase_cb)
    dpg.create_context()
    gui.build()
    gui.table_cb(FAKE_PARTS, boot_bytes=4096, user_sectors=60778974)
    gui._log_dirty = True

    frames = {"n": 0}

    def tick():
        # replaces DpgGui._drain_queue: processes the bridge queue, then
        # keeps a single self-rescheduling frame ticker
        try:
            while True:
                item = gui.q.get_nowait()
                kind = item[0]
                if kind == "table":
                    gui._on_table(*item[1:])
                elif kind == "call":
                    item[1]()
        except Exception:
            pass
        frames["n"] += 1
        if frames["n"] == 5:
            gui._first_frame()
        if frames["n"] >= 30:
            check()
            dpg.stop_dearpygui()
            return
        dpg.set_frame_callback(dpg.get_frame_count() + 1, tick)

    gui._drain_queue = tick

    def check():
        assert dpg.does_item_exist("parts_table"), "parts_table was not created"
        rows = dpg.get_item_children("parts_table", 1)
        # data rows only; the header row is generated from the columns
        assert len(rows) == 3, f"expected 3 data rows, got {len(rows)}"
        cells = [dpg.get_value(c) for c in dpg.get_item_children(rows[1], 1)]
        assert cells[0] == "1" and cells[1] == "boot", f"unexpected cells: {cells}"
        print("[SMOKE] partition table OK: 3 data rows, cells populated")

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_frame_callback(dpg.get_frame_count() + 1, tick)
    while dpg.is_dearpygui_running() and frames["n"] < 200:
        dpg.render_dearpygui_frame()
    else:
        if frames["n"] < 30:
            print("[SMOKE] render loop ended early")
            sys.exit(1)
    dpg.destroy_context()
    print("[SMOKE] PASS")


if __name__ == "__main__":
    main()
