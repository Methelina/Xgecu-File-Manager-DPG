# Roadmap: Kivy -> DearPyGui migration

Author of the DPG port: Soror L.'.L.'.
Status as of 2026-11-19. Checked = done and verified; unchecked = todo.

## Stage 0 — runtime and groundwork

- [x] Portable uv runtime: `install_xgecu_prog.ps1` / `run_xgecu_prog.ps1`
      (+ standalone `.bat` v3.0.0), `xgecu_env` (Python 3.11), caches
      isolated in `.cache`, stale-process kill, auto-install on launch
- [x] `dearpygui==2.3` in requirements.txt (kivy kept for legacy gui.py)
- [x] OctoGirl font set vendored in `assets/fonts` (ModeSeven x2, VCR OSD
      Mono RUS, JetBrains Mono NF) + DejaVu Sans Mono for progress bars
- [x] Migration notes: docs/MIGRATION_DPG.md; roadmap: docs/roadmap.md

## Stage 1 — DPG skeleton

- [x] `src/gui_dpg.py`: setup/context, viewport "Xgecu Prog v<ver>",
      icon, `_gui_ready` guard, lazy dpg imports
- [x] CrisTical dark theme (OctoGirl palette, amber accent), semantic
      item-themes (send/reset/selection)
- [x] Font system: font_body/font_header (ModeSeven), font_chat
      (Cyrillic), font_nerd (remap), font_log (journal 11 px),
      font_bar (DejaVu); RU mode renders VCR as default font
- [x] Thread bridge: orchestrator callbacks -> queue.Queue ->
      frame callback; demo tick chain

## Stage 2 — main window

- [x] Mode tabs EMMC / NAND [SOON] / SPI [SOON]; READ/WRITE/ERASE
      sub-tabs
- [x] Toolbar: VCCQ, bus, clock, preset combos (localized values
      canonicalized before backend), Scatter -> GPT
- [x] Journal: level filter, search, per-line coloring, copy from full
      buffer, log font 11 px
- [x] Text progress bar (DejaVu, U+25B0/U+25B1) with percent + MiB/s,
      panel-width resize handler
- [x] Status lamp in title row (OctoGirl CrisTical pattern):
      ONLINE/INIT/ERROR via legacy XGecuT48.open() probe at 1 s;
      demo cycles states every 5 s
- [x] RU/EN switch (RU/EN buttons in title row, .lang.cfg persistence)

## Stage 3 — functional parity

- [x] READ: init/analyze, userdata/BOOT1/BOOT2 dumps, full read
- [x] Partition table: DPG table with header, selectable rows,
      multi-row selection, DUMP/WRITE/ERASE action row
- [x] WRITE: images folder + 4 file rows (per-row Write + status),
      WRITE CHIP flow, EXT_CSD field table (177/178/179/162/160)
- [x] ERASE: area combo, Start/End LBA, canonicalized target
- [x] EXT_CSD: file open/compare/save, per-field write, OTP modals,
      blocking plan confirm for write_all

## Stage 4 — dialogs and UX

- [x] Native tkinter file dialogs (replacing dpg.file_dialog)
- [x] Modal confirmations with Cyrillic-capable font
- [x] RU/EN screenshots in README; cross-language links

## Stage 5 — packaging and tests

- [x] `T48_eMMC_dpg.spec` + `compile_bin.ps1` -> `bin\T48_eMMC_dpg_v<ver>.exe`,
      PyInstaller auto-install, EXE smoke-checked
- [x] Root reorganized: core in `src/`, smokes in `tests/`, probes in
      `docs/research/`, logs in `logs/`, JSON in `cfg/`, fixtures in
      `assets/fixtures/`; AGENTS.md layout updated
- [x] Backend synced with upstream bepe3apng/Xgecu-File-Manager@f70aee3
      (benchmark/firmware/rpmb/service/vmx0/register_archive + session,
      registers, protocol, operations improvements)
- [x] smoke_layers / smoke_stop / smoke_verification PASS on the new
      layout; smoke_extcsd reaches the documented legacy color assert;
      smoke_autoconfig has the documented "init failed" legacy failure

## Stage 6 — remaining work

- [ ] Fix legacy smoke GUI failures (smoke_extcsd color assert,
      smoke_autoconfig init-failed) or rewrite them against gui_dpg
- [ ] Rewrite smoke suite fully against gui_dpg (headless, mocked
      orchestrator): DPG equivalents of all five smokes
- [ ] Port upstream GUI features to DPG: benchmark button + speed graph
      (native DPG plots), service panel (ui_emmc_service equivalent),
      speed_graph widget
- [ ] Localize backend-adjacent strings shown in UI where feasible
      (EXT_CSD describe() output, partition names come untranslated)
- [ ] Light/decide on: theme switcher (OctoGirl is dark-only; current
      port follows it)
- [ ] Update docs/USER_GUIDE.md with DPG screenshots and flows;
      refresh docs/BUILD.md / docs/ARCHITECTURE.md for the src/ layout
- [ ] Hardware verification (stage 6 of the plan): INIT EMMC on real
      T48, small-area read/write, STOP timings, logging per AGENTS 11
- [ ] Remove Kivy: requirements.txt, src/gui.py, src/gui.kv,
      kivy imports in ui_log/ui_theme, packaging_runtime reconsider,
      legacy T48_eMMC.spec retirement
- [ ] Final: version bump, release build, README/BUILD touch-up
