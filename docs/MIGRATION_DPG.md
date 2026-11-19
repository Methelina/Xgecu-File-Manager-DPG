# Kivy -> DearPyGui migration notes

Scope: GUI layer only (gui.py / gui.kv -> gui_dpg.py).
orchestrator.py, modes/, t48_usb.py are untouched; AppOrchestrator callbacks
(log, table, task, progress, phase) keep their signatures.

## Runtime

- Portable uv (uv.exe in the project root), caches isolated in .cache.
- venv xgecu_env (Python 3.11), deps from requirements.txt via uv pip.
- install_xgecu_prog.ps1 (install / run / reinstall menu),
  run_xgecu_prog.ps1 (launcher with stale-process kill, auto-installs).

## Frontend decisions

- OctoGirl-style DearPyGui paradigm: tagged widgets + get/set_value +
  configure_item; one global CrisTical dark theme + semantic item themes
  (button_theme_send / button_theme_reset / ext_field_*).
- Fonts from assets/fonts: font_header (ModeSeven 22), font_body
  (ModeSeven 16, default, Latin), font_chat (VCR OSD Mono RUS 16,
  Cyrillic), font_nerd (JetBrains Mono NF 15, Cyrillic via char remap
  0x0410..0x044F -> 0x00C0..0x00FF). UI strings Latin-only; Cyrillic
  appears in the log, which binds font_nerd on the container.
- Thread model: orchestrator callbacks run in the worker thread and only
  enqueue into queue.Queue; a frame callback drains the queue and issues
  all dpg calls. _gui_ready gates dpg calls until the first frame.
- Preset display names (standard / THGA / Auto) map to the Cyrillic
  protocol keys at import time (_PRESET_DISPLAY_TO_KEY); combo_clock is
  disabled while Auto.
- File dialogs and OTP confirmations (EXT_CSD 162/178) are native
  dpg.file_dialog / modal windows, replacing tkinter. The EXT_CSD write
  plan uses a blocking confirm over the render loop to keep the legacy
  one-shot run_write_all contract.
- Partition table: dpg.table with selectable rows; a single action row
  (DUMP / WRITE / ERASE) works on the selected row (per-row buttons are
  expensive in DPG tables).

## Stages

1. [done] Runtime (uv), fonts, theme, gui_dpg.py skeleton, smoke render.
2. EXT_CSD write/read flows against mocks (smoke_extcsd equivalent).
3. Partition dump/write/erase flows against mocks (smoke_verification).
4. STOP and session lifecycle (smoke_stop); autoconfig GUI parity
   (smoke_autoconfig, fix known legacy failures separately).
5. PyInstaller spec update (dearpygui + fonts), EXE check from dist.
6. [done] Remove Kivy (requirements, gui.kv, legacy gui.py), docs refresh.
