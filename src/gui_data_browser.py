"""
Data Browser GUI tab for the DPG frontend (Explorer-style file view).

Self-contained module: builds a 'Data Browser' tab into the mode_pages tab
bar, owns its state (source, VfsNode tree), and talks to data_browser core.
Two input modes: a dump file (always available, read-only) or the live chip
SessionSource after Init eMMC. The dump is never written to.

src/gui_data_browser.py
Version:     0.1.0
Author:      Soror L.'.L.'
Updated:     2026-11-22

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Tab builder: source buttons (open dump / use live chip), scan button,
      tree view (partitions -> folders/files), save-selected, status line.
  [+] Tree population from VfsNode.walk() with depth cap; lazy: FS listing
      runs in build() (worker thread planned in GUI-phase 2).
  [+] Extraction: backend read_node + save dialog via existing pattern.
"""

from __future__ import annotations

import os
import threading

import dearpygui.dearpygui as dpg

import strings as st

TAG = {
    "tab": "tab_data_browser",  # reserved; runtime ids live in self.ids
}


class DataBrowserTab:
    """Holds browser state; methods are DPG callbacks (main GUI thread only)."""

    def __init__(self, app):
        self.app = app  # main app: session access, log_cb, busy state
        self.source = None
        self.browser = None
        self.root_node = None
        self.selected = None
        self.ids = {}
        self._progress_frac = 0.0

    # --- callbacks ---------------------------------------------------------
    def on_open_dump(self):
        def _worker():
            try:
                from tkinter import Tk, filedialog
                tk = Tk()
                tk.withdraw()
                path = filedialog.askopenfilename(
                    title="Open dump",
                    filetypes=[("Dumps", "*.bin *.img"), ("All files", "*.*")])
                tk.destroy()
                if not path:
                    return
                self.app.q.put(("call",
                                lambda: self._set_status(os.path.basename(path) + "...")))
                from modes.emmc.data_browser import FileSource, RangeCache
                src = FileSource(path)
                self.source = RangeCache(src, chunk_size=16384, max_chunks=512)
                self._scan_worker()
            except Exception as exc:  # noqa: BLE001
                self.app.q.put(("call",
                                lambda: self._set_status(f"error: {exc}")))

        threading.Thread(target=_worker, daemon=True).start()

    def on_use_chip(self):
        orch = getattr(self.app, "orchestrator", None)
        if orch is None:
            self._set_status(st.S("db_need_init"))
            return
        is_18v, bus, _preset, _clock = self.app._connection_settings()
        sec_count = getattr(self.app, "user_total_sectors", 0)

        def _browse_live():
            # runs inside orchestrator.run_task -> usb_operation(stop_event)
            from modes.emmc.session import EmmcSession
            from modes.emmc.data_browser.sources import SessionSource, RangeCache
            from modes.emmc.data_browser import DataBrowser
            session = EmmcSession(orch.log)
            if not session.open():
                self.app.q.put(("call", lambda: self._set_status("chip open failed")))
                return
            try:
                session.init_hw(is_18v, bus)
                if not sec_count:
                    _cid, _csd, data = session.wake_registers(bus)
                    if data and len(data) > 216:
                        sec_count = int.from_bytes(data[212:216], "little")
                if not sec_count:
                    raise RuntimeError("SEC_COUNT unknown")
                source = RangeCache(SessionSource(session, sec_count * 512,
                                                  orch.stop_event),
                                    chunk_size=16384, max_chunks=256)
                browser = DataBrowser(self._progress_source(source))
                root, diag = browser.build()
                self.app.q.put(("call", lambda: self._adopt_scan(source, browser, root)))
            finally:
                try:
                    session.close()
                except Exception:
                    pass

        orch.run_task(_browse_live)

    def _adopt_scan(self, source, browser, root):
        """GUI-thread adoption of a scan done on the worker thread."""
        self.source = source
        self.browser = browser
        self._apply_scan(root)

    def on_scan(self):
        if self.source is None:
            self._set_status(st.S("db_need_init"))
            return
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        """Build the tree on a worker thread; UI updates via the app queue.

        Dear PyGui calls must stay on the GUI thread - calling dpg from here
        corrupts the tree (observed: only the last-partition files listed).
        """
        try:
            from modes.emmc.data_browser import DataBrowser
            browser = DataBrowser(self._progress_source(self.source),
                                  partition_progress=self._partition_progress_cb)
            root, diag = browser.build()
            self._pending = (browser, root, diag)
            self.app.q.put(("call", self._adopt_pending))
        except Exception as exc:  # noqa: BLE001
            self.app.q.put(("call",
                            lambda: self._set_status(f"error: {exc}")))

    def _adopt_pending(self):
        if not getattr(self, "_pending", None):
            return
        browser, root, diag = self._pending
        self._pending = None
        self.browser = browser
        self._apply_scan(root, diag)

    def on_select(self, sender, app_data):
        # tree selection: tag payload carries the VfsNode index
        key = app_data[0] if isinstance(app_data, (list, tuple)) else None
        if key is not None and key in getattr(self, "_node_map", {}):
            self.selected = self._node_map[key]
            dpg.set_value(TAG["selected"],
                          f"{self.selected.name} ({self.selected.size} B)")

    def on_save_selected(self):
        node = self.selected
        if node is None or self.browser is None or node.is_dir:
            return

        def _worker():
            try:
                from tkinter import Tk, filedialog
                tk = Tk()
                tk.withdraw()
                dest = filedialog.asksaveasfilename(initialfile=node.name)
                tk.destroy()
                if not dest:
                    return
                n = self.browser.extract(node, dest)
                self.app.q.put(("call",
                                lambda: self._set_status(f"saved {n} bytes")))
            except Exception as exc:  # noqa: BLE001
                self.app.q.put(("call",
                                lambda: self._set_status(f"error: {exc}")))

        threading.Thread(target=_worker, daemon=True).start()

    # --- internals ---------------------------------------------------------
    def _set_status(self, text: str):
        tag = self.ids.get("status")
        try:
            if tag is not None:
                dpg.set_value(tag, text)
        except Exception:
            pass

    def _apply_scan(self, root, diag=None):
        dpg.delete_item(self.ids["tree"], children_only=True)
        self._node_map = {}
        self.selected = None
        self.root_node = root
        # debug artifact: what the scan actually saw, tree format
        try:
            out = os.path.join(os.getcwd(), "tmp", "data_browser_tree.txt")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if self.browser is not None:
                lines = self.browser.dump_tree(out)
                self._last_tree_dump = out
        except Exception as exc:  # noqa: BLE001
            self._last_tree_dump = None
            print(f"[data_browser] fallback: tree dump failed ({exc})")
        dpg.set_value(self.ids["status"],
                      f"{len(root.children)} partitions"
                      + (f", device: {diag['device_preset']}"
                         if diag and "device_preset" in diag else ""))
        self._add_nodes(root, self.ids["tree"], depth=0)

    def _add_nodes(self, node, parent, depth):
        if depth > 4:
            return
        for child in node.children:
            label = child.name + ("/" if child.is_dir else "")
            with dpg.tree_node(parent=parent, label=label, default_open=depth == 0):
                key = dpg.last_item()
                self._node_map[key] = child
                if not child.is_dir and child.size:
                    dpg.add_text(f"  {child.size} B  {child.fs_label}",
                                 color=(120, 120, 120))
                self._add_nodes(child, key, depth + 1)

    # --- construction ------------------------------------------------------
    def build(self):
        # _build_window may run twice (normal/demo rebuild). The tab has no
        # string tag (alias collisions during pre-startup builds), so guard
        # by our own runtime id: if the previous tab is still alive, skip.
        old = self.ids.get("tab")
        if old is not None and dpg.does_item_exist(old):
            return
        self.ids = {}
        with dpg.tab(label=st.S("tab_data_browser"), parent="mode_pages") as tab:
            self.ids["tab"] = tab
            with dpg.group(horizontal=True):
                dpg.add_button(label=st.S("db_browse_dump"),
                               callback=self.on_open_dump)
                dpg.add_button(label="Use chip (after Init)",
                               callback=self.on_use_chip)
                dpg.add_button(label=st.S("db_scan"), callback=self.on_scan)
                dpg.add_button(label=st.S("db_save_file"),
                               callback=self.on_save_selected)
            self.ids["status"] = dpg.add_text(st.S("db_none"),
                                              color=(150, 150, 150))
            self.ids["selected"] = dpg.add_text("", color=(200, 200, 120))
            # same symbolic bar style as Init eMMC (bar font, U+25B0/U+25B1)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=2)
                textbar = dpg.add_text("[....................]   0%",
                                       tag="db_progress_textbar",
                                       color=(120, 200, 120))
                if dpg.does_item_exist("font_bar"):
                    dpg.bind_item_font(textbar, "font_bar")
                dpg.add_spacer(width=8)
                self.ids["progress_percent"] = dpg.add_text(
                    "scan idle", color=(150, 150, 150))
            with dpg.child_window(border=True, height=-1) as tree:
                self.ids["tree"] = tree

    # --- progress ----------------------------------------------------------
    def _partition_progress_cb(self, index: int, total: int, name: str):
        """Worker thread: partition-level progress; UI via the app queue."""
        self._progress_frac = (index - 1) / max(1, total)
        self._partition_label = f"partition {index}/{total}: {name}"
        self.app.q.put(("call", self._paint_progress))

    def _paint_progress(self):
        tag = self.ids.get("progress_textbar")
        if tag is None or not dpg.does_item_exist(tag):
            return
        try:
            bar = self.app._bar(self._progress_frac, 36)
            dpg.configure_item(tag, default_value=bar)
            label = getattr(self, "_partition_label", "")
            dpg.set_value(self.ids.get("progress_percent"),
                          f"{self._progress_frac * 100:.0f}%  {label}")
        except Exception:
            pass

    def _progress_cb(self, frac: float):
        """Worker thread: buffer fraction; UI update via the app queue."""
        self._progress_frac = frac
        self.app.q.put(("call", self._paint_progress))

    def _paint_progress(self):
        tag = self.ids.get("progress_textbar")
        if tag is None or not dpg.does_item_exist(tag):
            return
        try:
            bar = self.app._bar(self._progress_frac, 36)
            dpg.configure_item(tag, default_value=bar)
            dpg.set_value(self.ids.get("progress_percent"),
                          f"{self._progress_frac * 100:.1f}%")
        except Exception:
            pass

    def _progress_source(self, cache):
        """Wrap the cache so reads drive the symbolic progress bar."""
        from modes.emmc.data_browser.sources import ProgressSource
        return ProgressSource(cache, progress=self._progress_cb)
