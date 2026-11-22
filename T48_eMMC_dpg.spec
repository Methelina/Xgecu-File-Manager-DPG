# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('.version.cfg', '.')]
binaries = []
hiddenimports = ['modes.emmc.autoconfig',
    'gui_data_browser',
    'modes.emmc.data_browser',
    'modes.emmc.data_browser.sources',
    'modes.emmc.data_browser.partmaps',
    'modes.emmc.data_browser.signatures',
    'modes.emmc.data_browser.profiles',
    'modes.emmc.data_browser.vfs',
    'modes.emmc.data_browser.fs_fat',
    'modes.emmc.data_browser.fs_ext',
    'modes.emmc.data_browser.fs_vdfs',
    'modes.emmc.data_browser.tools_runner',
    'py7zr',
    'lzo',
    'dissect.squashfs',
    'PySquashfsImage',
]
for _m in ('py7zr', 'dissect.squashfs', 'dissect.util', 'PySquashfsImage', 'lzo'):
    try:
        tmp_ret = collect_all(_m)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass
tmp_ret = collect_all('dearpygui')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['src/gui_dpg.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    excludes=['kivy', 'kivy_deps', 'numpy', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='T48_eMMC_dpg',
    icon='assets/xgecu_prog.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
