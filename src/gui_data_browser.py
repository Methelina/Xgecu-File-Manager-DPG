"""
Data Browser GUI tab for the DPG frontend (Explorer-style file view).

Self-contained module: builds a 'Data Browser' tab into the mode_pages tab
bar, owns its state (source, VfsNode tree), and talks to data_browser core.
Two input modes: a dump file (always available, read-only) or the live chip
SessionSource after Init eMMC. The dump is never written to.

src/gui_data_browser.py
Version:     0.4.5
Author:      Soror L.'.L.'
Updated:     2026-11-27

Patch Notes v0.4.5 (Soror L.'.L.'.):
  [*] The progress bar no longer keeps the last listing step (94.1%)
      after everything succeeded: successful mount paints it done at
      100% with the mounted letter; Unmount All resets it to 0%.

Patch Notes v0.4.4 (Soror L.'.L.'.):
  [*] Final simplification per user decision: no DPG file tree, no
      FIND, no BROWSE pane - open dump lists the model in the
      background (bar + log), then auto-mounts the drive; the file
      level lives in Windows Explorer. Tab layout: source buttons,
      status, MOUNT block, progress bar, LOG.

Patch Notes v0.4.3 (Soror L.'.L.'.):
  [+] In-GUI LOG box (200 lines, timestamped) mirroring the console
      [data_browser] lines, next to the phase status bars.
  [*] Search index includes zero-byte files too (the selftest caught
      205 missing files - the index filtered size > 0).

Patch Notes v0.4.2 (Soror L.'.L.'.):
  [*] Open dump now goes straight to the drive: fast open -> background
      listing (bar shows per-partition progress) -> automatic read-only
      mount of the fully listed model. The DPG tree stage is no longer
      on the critical path (it stays as a first-level preview); full
      depth is browsed in Explorer via the drive, in the BROWSE pane
      and in FIND.
  [+] BROWSE pane: Explorer-style navigation of any folder (listbox +
      Open/Up/Save buttons - button callbacks work, item handlers do
      not), backed by the fully listed model.

Patch Notes v0.4.1 (Soror L.'.L.'.):
  [*] Depth cap reverted (user decision: the tree is the user's view of
      the firmware - no content limiting). Full-depth build stays, now
      with adaptive chunk pacing (150 -> 20 nodes when a chunk costs
      > 16 ms, growing back below 6 ms) inside the 8 ms frame budget.
      The FIND FILE block stays as a complement.

Patch Notes v0.4.0 (Soror L.'.L.'.):
  [*] THE render budget is now architectural: the tree renders only the
      top two levels; the full-depth walk feeds a filename search index
      instead of DPG widgets. Measured again and again: DPG freezes for
      seconds per frame past ~40k flat nodes and crashes at 165k - no
      watchdog can fix that, it is render work, not a hang.
  [+] FIND FILE block (input + Find + results list + Save selected,
      button-driven only): substring search over every listed file of
      the dump, extract to tmp/extract/. Whole-dump browsing stays on
      the mounted drive (Explorer handles millions of files).

Patch Notes v0.3.9 (Soror L.'.L.'.):
  [*] Mount got its own framed block in the tab: MOUNT header, the
      Mount/Unmount buttons, the drive lamp with the mounted letter and
      the dedicated mount report line - instead of buttons scattered
      across the shared toolbar row.

Patch Notes v0.3.8 (Soror L.'.L.'.):
  [+] Dedicated mount report line under the buttons: stages, the final
      "Mounted P: (read-only)" and errors go there - the scan
      auto-listing owned the shared status and buried every mount
      report (user-visible: clicking Mount "did nothing").
  [*] The lamp shows the mounted letter ("● P:") and turns green on
      success; Unmount All resets it.
  [*] Auto-listing stopped overwriting the general status per
      partition (its progress lives in the bar label now).

Patch Notes v0.3.7 (Soror L.'.L.'.):
  [*] Deterministic tree build: a failing node is skipped and named in
      the console ("fallback: node 'x' skipped") but the batch chain
      always continues - the bar now finishes every partition's plan
      at 100% instead of stopping at a random percent per run.

Patch Notes v0.3.6 (Soror L.'.L.'.):
  [+] Disambiguated the two phases: console now logs "tree built
      (N nodes, Xs)" when the DPG build of a partition finishes, and
      the GUI bar label says "building tree ..." - the console percent
      is the listing phase, the GUI percent is the node build, they
      legitimately differ while a big partition (smarttv: 160k nodes)
      is still being rendered in chunks.

Patch Notes v0.3.5 (Soror L.'.L.'.):
  [*] Auto-continue on stalls: a failing build chunk logs a fallback
      line, releases the partition slot and drops the rest of that
      partition's plan instead of wedging _tree_busy forever; the
      auto-listing watchdog force-continues after 120 s without
      movement. Random-percent "freezes" were one exception inside a
      queued callback killing the whole drain loop (gui_dpg side
      guards every event now).

Patch Notes v0.3.4 (Soror L.'.L.'.):
  [+] Console "listed" lines carry the live scan state: overall percent,
      wall-clock time and the partition counter, plus listing duration
      - "[data_browser] smarttv: listed (76344 files, fat32, 92.2%,
      22:31:11 16/17, 2.4s)".

Patch Notes v0.3.3 (Soror L.'.L.'.):
  [*] Tree build chunks 600 -> 150 nodes: with the frame budget the
      combined per-frame work must stay ~10 ms or the window still
      stalls (observed live at the 76k-file smarttv partition).
  [*] Progress text is ASCII-separated and "left" is localized - the
      middot separators rendered as "?" on the EN locale and the
      hardcoded Russian rendered as "????????" (Latin-only font).

Patch Notes v0.3.2 (Soror L.'.L.'.):
  [*] DPG item-click/toggle handlers never fired in the live window, so
      the lazy expand-on-click design was dead: "..." placeholders
      stayed forever. Removed every click dependency - after the fast
      open, partitions list themselves sequentially in the background
      (worker walk + chunked build, generation-guarded), "..." is
      replaced by real content without any user input, and empty
      partitions show "(empty)".

Patch Notes v0.3.1 (Soror L.'.L.'.):
  [*] DocMobi-style fast open: scans are shallow (partition map +
      signatures, ~1 s for a 15.5 GiB dump); a partition's filesystem
      lists on first expand - worker-thread walk, then chunked DPG
      build (600/batch) with the bar showing nodes added vs total.
      The old full-walk-then-render pipeline froze the GUI on huge
      ext4 partitions no matter how the render was chunked.

Patch Notes v0.3.0 (Soror L.'.L.'.):
  [*] Progress label rebuilt after the DocMobi reference layout: the
      partition counter leads ("partition 17/17: smarttv"), followed by
      the creeping percent, bytes read and "remaining" bytes - during a
      long FS walk the bar creeps (log curve, never stalls, never
      finishes early) and the counters stay visible.

Patch Notes v0.2.9 (Soror L.'.L.'.):

Patch Notes v0.2.9 (Soror L.'.L.'.):
  [*] Scan progress is monotonic: the bar fills by partition; byte
      events only tick the "N read" label (the byte fraction used to
      yank the bar back to ~0% mid-scan, looking like a hang).

Patch Notes v0.2.8 (Soror L.'.L.'.):
  [*] First tree level is real content: partitions render with their
      actual children (dirs/files), no "..." filler at the top. The
      placeholder only marks deeper unexpanded dirs and is replaced in
      the same frame as the toggle.
  [*] Handlers pass user_data=key explicitly; the callback reads
      user_data, not the dispatch payload shape.

Patch Notes v0.2.7 (Soror L.'.L.'.):
  [*] Worker error lambdas capture msg=exc: a queued lambda evaluated
      after the except block lost the exc binding (NameError traceback
      on every mount failure).
  [+] Mount status bar: per-stage progress from mount_auto (letter pick,
      indexing, host start, READY wait) plus a drive lamp: gray idle,
      green mounted, red failed.
  [+] dump-chain unwrap test coverage surfaced a GUI-only bug: the
      ProgressSource wrapper hid the dump path from mount_tree.
  [*] Full-depth tree, no depth cap: directories carry a placeholder
      arrow and populate on first toggle-open. Worst measured fanout on
      the MTK dump is 421 direct children, so one expand stays in the
      single-frame budget; the full 165k-node tree is reachable without
      ever laying it out flat (which crashes DPG).
  [+] Node click selection wired (on_select existed but was bound to
      nothing - Save Selected could never fire).

Patch Notes v0.2.5 (Soror L.'.L.'.):
  [*] Tree depth cap raised 4 -> 7 (4330 -> ~17k nodes on the MTK dump;
    build stays ~0.5 s chunked). Full 165k-node render is unsafe in DPG;
    whole-dump browsing stays on the read-only drive mount.

Patch Notes v0.2.4 (Soror L.'.L.'.):
  [*] Tree builds in chunks of 600 nodes through the frame queue; the
      symbolic bar shows nodes added vs total (no lazy placeholders).
  [*] progressbar fixed: ids["progress_textbar"] was never stored and
      _paint_progress was defined twice (second silently shadowed the
      first), so the bar never painted at all.
  [-] removed the v0.2.3 lazy toggle-open mechanism.

Patch Notes v0.2.3 (Soror L.'.L.'.):
  [*] Lazy tree: directories render a placeholder arrow and populate
      children on first toggle-open. A full MTK dump lists 80k+ files;
      building every DPG node in one pass froze the GUI for minutes on
      the scan that itself takes ~3 s.

Patch Notes v0.2.2 (Soror L.'.L.'.):
  [*] Mount worker uses self.browser (the worker closure referenced an
      undefined `browser` - every mount click died with NameError).

Patch Notes v0.2.1 (Soror L.'.L.'.):
  [*] Mount mounts the whole scanned dump (all partitions as folders of
      one drive) as soon as a dump/chip is scanned - no selection needed;
      an explicit folder selection still narrows the mount to that node.

Patch Notes v0.2.0 (Soror L.'.L.'):
  [+] Mount/unmount buttons: selected partition (or folder with a tree)
      mounts read-only as a drive letter via data_browser.mount
      (WinFsp, user-mode); unmount-all and status line updates; refused
      gracefully when WinFsp is absent or the selection has no tree.

Patch Notes v0.1.0 (Soror L.'.L.'):
  [+] Tab builder: source buttons (open dump / use live chip), scan button,
      tree view (partitions -> folders/files), save-selected, status line.
  [+] Tree population from VfsNode.walk() with depth cap; lazy: FS listing
      runs in build() (worker thread planned in GUI-phase 2).
  [+] Extraction: backend read_node + save dialog via existing pattern.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

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
                msg = f"error: {exc}"
                self.app.q.put(("call",
                                lambda msg=msg: self._set_status(msg)))

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
                root, diag = browser.build(list_fs=False)
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
            # shallow: partition map + signatures only (DocMobi-style fast
            # open); each partition lists its FS on first expand
            root, diag = browser.build(list_fs=False)
            self._pending = (browser, root, diag)
            self.app.q.put(("call", self._adopt_pending))
        except Exception as exc:  # noqa: BLE001
            msg = f"error: {exc}"
            self.app.q.put(("call",
                            lambda msg=msg: self._set_status(msg)))

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
                msg = f"error: {exc}"
                self.app.q.put(("call",
                                lambda msg=msg: self._set_status(msg)))

        threading.Thread(target=_worker, daemon=True).start()

    # NOTE: no in-GUI file search / browse pane - after the automatic
    # drive mount the file level lives in Windows Explorer, which handles
    # any depth and file count natively (user decision, 2026-11-26).

    def on_mount_selected(self):
        # Whole dump by default: every scanned partition becomes a folder
        # of one read-only drive; an explicit folder selection narrows it.
        node = self.selected
        if node is None or self.browser is None or not node.is_dir:
            node = self.root_node
        if node is None or self.browser is None or not node.is_dir:
            self._set_status(st.S("db_mount_need_scan"))
            return

        def _worker():
            try:
                from modes.emmc.data_browser.mount import MountManager, is_available
                manager = getattr(self.app, "mount_manager", None)
                if manager is None:
                    manager = MountManager()
                    self.app.mount_manager = manager
                if not is_available():
                    self.app.q.put(("call", self._mount_lamp_red))
                    self.app.q.put(("call",
                                    lambda: self._set_mount_status(
                                        st.S("db_mount_no_winfsp"))))
                    return
                self.app.q.put(("call", self._mount_lamp_busy))

                def _stage(text):
                    self.app.q.put(("call",
                                    lambda s=text: self._set_mount_status(
                                        st.S("db_mount_stage").format(s=s))))

                letter = manager.mount_auto(self.browser, node, node.name,
                                            progress=_stage)
                self.app.q.put(("call",
                                lambda d=letter: self._set_mount_status(
                                    st.S("db_mount_ok").format(d=d))))
                # the listing bar used to freeze at its last step (94.1%)
                # after everything succeeded - finish it at 100% here
                self.app.q.put(("call",
                                lambda d=letter: self._paint_progress(
                                    st.S("db_mount_ok").format(d=d))))
                self.app.q.put(("call",
                                lambda d=letter: self._mount_lamp_ok(d)))
            except Exception as exc:
                msg = st.S("db_mount_failed").format(e=exc)
                self.app.q.put(("call", self._mount_lamp_red))
                self.app.q.put(("call",
                                lambda msg=msg: self._set_mount_status(msg)))

        threading.Thread(target=_worker, daemon=True).start()

    def on_unmount_all(self):
        def _worker():
            try:
                from modes.emmc.data_browser.mount import MountManager
                manager = getattr(self.app, "mount_manager", None)
                if manager is None:
                    manager = MountManager()
                    self.app.mount_manager = manager
                n = manager.unmount_all()
                self.app.q.put(("call",
                                lambda: self._set_mount_status(
                                    st.S("db_unmount_ok").format(n=n))))
                self.app.q.put(("call", self._mount_lamp_idle))
                self.app.q.put(("call",
                                lambda: self._paint_progress_frac(0.0, "")))
            except Exception as exc:  # noqa: BLE001
                msg = f"error: {exc}"
                self.app.q.put(("call",
                                lambda msg=msg: self._set_mount_status(msg)))

        threading.Thread(target=_worker, daemon=True).start()

    # --- internals ---------------------------------------------------------
    _LAMP_COLORS = {
        "idle": (120, 120, 120),   # no drive mounted
        "busy": (230, 180, 60),    # mount in progress
        "ok": (95, 252, 65),       # drive mounted (theme green family)
        "fail": (255, 80, 80),     # last mount attempt failed
    }

    def _set_lamp(self, state: str, letter: str = ""):
        tag = self.ids.get("lamp")
        if tag is None or not dpg.does_item_exist(tag):
            return
        try:
            dpg.configure_item(tag, color=self._LAMP_COLORS.get(state) or
                               self._LAMP_COLORS["idle"])
            dpg.configure_item(tag, default_value=f"● {letter}".rstrip())
            tag_status = self.ids.get("mount_status")
            if state == "ok" and tag_status is not None \
                    and dpg.does_item_exist(tag_status):
                dpg.configure_item(tag_status, color=self._LAMP_COLORS["ok"])
        except Exception:
            pass

    def _set_mount_status(self, text: str):
        """Mount report line - separate from the scan/auto-list status."""
        tag = self.ids.get("mount_status")
        try:
            if tag is not None and dpg.does_item_exist(tag):
                dpg.set_value(tag, text)
        except Exception:
            pass

    def _mount_lamp_idle(self):
        self._set_lamp("idle")

    def _mount_lamp_busy(self):
        self._set_lamp("busy")

    def _mount_lamp_ok(self, letter: str = ""):
        self._set_lamp("ok", letter)

    def _mount_lamp_red(self):
        self._set_lamp("fail")

    def _db_log(self, msg: str):
        """Console print AND the in-GUI log box (bounded to 200 lines)."""
        print(f"[data_browser] {msg}" if not msg.startswith("[data_browser]")
              else msg, flush=True)
        self.app.q.put(("call", lambda m=msg: self._log_append(m)))

    def _log_append(self, msg: str):
        box = self.ids.get("log_box")
        if box is None or not dpg.does_item_exist(box):
            return
        self._log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        self._log_lines = self._log_lines[-200:]
        for kid in dpg.get_item_children(box, 1):
            dpg.delete_item(kid)
        for line in self._log_lines:
            dpg.add_text(line, parent=box, color=(140, 190, 140))

    def _set_status(self, text: str):
        tag = self.ids.get("status")
        try:
            if tag is not None:
                dpg.set_value(tag, text)
        except Exception:
            pass

    def _apply_scan(self, root, diag=None):
        self._node_map = {}
        self._tree_busy = False
        self._tree_gen = getattr(self, "_tree_gen", 0) + 1
        self._auto_list_done = False
        self.selected = None
        self.root_node = root
        # full-tree text dump (debug artifact) - tmp/data_browser_tree.txt
        self._db_log(f"fast open: {len(root.children)} partitions; "
                     f"listing + auto-mount follow")
        try:
            out = os.path.join(os.getcwd(), "tmp", "data_browser_tree.txt")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if self.browser is not None:
                lines = self.browser.dump_tree(out)
                self._last_tree_dump = out
        except Exception as exc:  # noqa: BLE001
            self._last_tree_dump = None
            self._db_log(f"fallback: tree dump failed ({exc})")
        size = self._fmt_bytes(self.source.size())
        dpg.set_value(self.ids["status"],
                      f"{len(root.children)} partitions, {size} dump"
                      + (f", device: {diag['device_preset']}"
                         if diag and "device_preset" in diag else ""))
        self._paint_progress_frac(0.0, "listing partitions...")
        parts = list(root.children)
        if parts:
            threading.Thread(target=self._auto_list_worker,
                             args=(parts, self._tree_gen),
                             daemon=True).start()

    def _auto_list_worker(self, parts, gen):
        """Background: list partitions sequentially, one walk at a time.

        A partition slot stuck longer than 120 s is force-released and
        the listing moves on (auto-continue; the watchdog prints a
        tagged fallback line so the stall is visible in the log).
        """
        total = len(parts)
        for idx, node in enumerate(parts, 1):
            waited = 0.0
            while self._tree_busy:
                if gen != self._tree_gen:
                    return
                time.sleep(0.05)
                waited += 0.05
                if waited >= 120.0:
                    self._db_log(f"fallback: partition slot stuck "
                                 f">120 s - force-continue with {node.name}")
                    self._tree_busy = False
                    break
            if gen != self._tree_gen:
                return
            self._start_partition_listing(node, idx, total, gen)
        # all partitions listed: the model is complete - auto-mount the
        # dump as a read-only drive (skips the GUI-render stage entirely;
        # Explorer shows the full depth without DPG limits)
        self._auto_list_done = True
        self.app.q.put(("call",
                        lambda: self._set_status(st.S("db_automount"))))
        self.app.q.put(("call", self.on_mount_selected))

    def _start_partition_listing(self, node, idx, total, gen):
        """Walk one partition's FS in this worker (model + index only)."""
        self._tree_busy = True
        name = node.name
        # progress-bar label only: the general status line stays free for
        # real messages (a mount report must not be buried by listing spam)
        self._paint_progress_frac((idx - 1) / max(1, total),
                                  f"listing partition {idx}/{total}: {name}")

        def _work():
            t_list = time.perf_counter()
            try:
                info = self.browser.list_partition(node)
                pct = idx / max(1, total) * 100.0
                now = time.strftime("%H:%M:%S")
                self._db_log(f"{name}: listed "
                             f"({info['files']} files, {info['label']}, "
                             f"{pct:.1f}%, {now} {idx}/{total}, "
                             f"{time.perf_counter() - t_list:.1f}s)")
            except Exception as exc:  # noqa: BLE001
                msg = f"{name}: listing failed: {exc}"
                self._db_log(f"fallback: {msg}")
                self.app.q.put(("call",
                                lambda msg=msg: self._set_status(msg)))
            # release the slot so the next partition goes
            self._tree_busy = False

        threading.Thread(target=_work, daemon=True).start()

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
            # --- source row: dump / chip / rescan -----------------------
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
            # --- LOG: mirrors console [data_browser] lines --------------
            dpg.add_separator()
            dpg.add_text(st.S("db_log_block"), color=(120, 200, 120))
            with dpg.child_window(border=True, height=140,
                                  no_scrollbar=False) as logw:
                self.ids["log_box"] = logw
            self._log_lines = []
            # --- mount block: buttons + lamp + its own report line -----
            # plain group, no child_window: autosize child windows inside
            # a tab proved layout-hostile (they swallowed the source row)
            dpg.add_separator()
            dpg.add_text(st.S("db_mount_block"), color=(120, 200, 120))
            with dpg.group(horizontal=True):
                dpg.add_button(label=st.S("db_mount"),
                                callback=self.on_mount_selected)
                dpg.add_button(label=st.S("db_unmount_all"),
                                callback=self.on_unmount_all)
                # drive lamp: gray idle, yellow mounting, green mounted
                # ("● N"), red failed
                dpg.add_spacer(width=6)
                lamp = dpg.add_text("●", color=self._LAMP_COLORS["idle"])
                with dpg.tooltip(lamp):
                    dpg.add_text(st.S("db_lamp_hint"))
                self.ids["lamp"] = lamp
            # dedicated mount report line: the scan auto-listing owns the
            # general status and must never bury a mount result
            self.ids["mount_status"] = dpg.add_text("",
                                                    color=(150, 150, 150))
            # same symbolic bar style as Init eMMC (bar font, U+25B0/U+25B1)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=2)
                textbar = dpg.add_text("[....................]   0%",
                                       tag="db_progress_textbar",
                                       color=(120, 200, 120))
                if dpg.does_item_exist("font_bar"):
                    dpg.bind_item_font(textbar, "font_bar")
                self.ids["progress_textbar"] = textbar
                dpg.add_spacer(width=8)
                percent = dpg.add_text("scan idle", color=(150, 150, 150))
                # the progress text carries Cyrillic ("осталось", RU scan
                # labels); the default ModeSeven body font is Latin-only
                if st.get_lang() == "ru" and dpg.does_item_exist("font_chat"):
                    dpg.bind_item_font(percent, "font_chat")
                self.ids["progress_percent"] = percent

    # --- progress ----------------------------------------------------------
    @staticmethod
    def _fmt_bytes(n: float) -> str:
        for unit, div in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
            if n >= div:
                return f"{n / div:.1f} {unit}"
        return f"{n:.0f} B"

    def _partition_progress_cb(self, index: int, total: int, name: str):
        """Worker thread: partition-level progress; UI via the app queue.

        Bar = monotonic steps by partition; the in-partition walk adds a
        time-based creep (DocMobi-style continuous fill): it approaches
        the next step but never reaches it, so the bar never looks stuck.
        """
        import time as _t
        self._part_idx = index
        self._part_total = total
        self._part_started = _t.monotonic()
        self._progress_frac = (index - 1) / max(1, total)
        self._partition_label = f"partition {index}/{total}: {name}"
        self._bytes_label = ""
        self.app.q.put(("call", self._paint_progress))

    def _paint_progress_frac(self, frac: float, label: str = ""):
        """Worker thread: arbitrary fraction with a label; UI via queue."""
        self._progress_frac = frac
        self._progress_label = label
        self.app.q.put(("call", self._paint_progress))

    def _paint_progress(self, done_label: str | None = None):
        tag = self.ids.get("progress_textbar")
        if tag is None or not dpg.does_item_exist(tag):
            return
        try:
            frac = 1.0 if done_label else getattr(self, "_progress_frac", 0.0)
            if done_label:
                text = done_label
            else:
                # ASCII-only separators and a localized "left" word: the
                # bar/status fonts must never meet raw non-ASCII layout
                # glyphs (middot rendered as "?" on the EN locale)
                size = getattr(self.source, "size", lambda: 0)()
                parts = [getattr(self, "_progress_label", ""),
                         f"{frac * 100:.1f}%",
                         getattr(self, "_bytes_label", ""),
                         (f"{st.S('db_left')} "
                          f"{self._fmt_bytes((1 - frac) * size)}"
                          if size and frac < 1.0 else "")]
                text = "  |  ".join(p for p in parts if p)
            dpg.configure_item(tag, default_value=self.app._bar(frac, 36))
            dpg.set_value(self.ids.get("progress_percent"), text)
        except Exception:
            pass

    def _progress_cb(self, frac: float):
        """Worker thread: byte-read ticker during a partition walk.

        The bar creeps toward the next partition step with a log curve
        (never stalls, never completes early); the label keeps the
        partition counter prominent and ticks the bytes read.
        """
        import time as _t
        try:
            total_size = self.source.size()
            self._bytes_label = f"{self._fmt_bytes(frac * total_size)} read"
        except Exception:
            self._bytes_label = ""
        idx = getattr(self, "_part_idx", 0)
        total = getattr(self, "_part_total", 0)
        started = getattr(self, "_part_started", None)
        if idx and total and started is not None:
            weight = 1.0 / max(1, total)
            base = (idx - 1) * weight
            creep = (1.0 - 1.0 / (1.0 + (_t.monotonic() - started) / 8.0))
            self._progress_frac = base + weight * creep
        self.app.q.put(("call", self._paint_progress))

    def _progress_source(self, cache):
        """Wrap the cache so reads drive the symbolic progress bar."""
        from modes.emmc.data_browser.sources import ProgressSource
        return ProgressSource(cache, progress=self._progress_cb)
