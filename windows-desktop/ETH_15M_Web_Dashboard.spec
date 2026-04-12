# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()
app_path = project_root / "windows-desktop" / "eth_web_dashboard_launcher.py"
presets_dir = project_root / "presets"
tradingview_dir = project_root / "tradingview"
web_dashboard_dir = project_root / "web-dashboard"

block_cipher = None

a = Analysis(
    [str(app_path)],
    pathex=[str(project_root), str(project_root / "src")],
    binaries=[],
    datas=[
        (str(presets_dir), "presets"),
        (str(tradingview_dir), "tradingview"),
        (str(web_dashboard_dir), "web-dashboard"),
        (str(project_root / "README.md"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ETH_15M_Web_Dashboard",
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
