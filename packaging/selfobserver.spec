# -*- mode: python ; coding: utf-8 -*-

import pathlib
from PyInstaller.building.build_main import Tree

project_root = pathlib.Path(__file__).resolve().parent.parent
ui_path = project_root / "ui"

datas = []
# Bundle templates and static assets so Flask can render from the exe
if ui_path.exists():
    datas += Tree(str(ui_path / "templates"), prefix="ui/templates").toc
    datas += Tree(str(ui_path / "static"), prefix="ui/static").toc

# Ship default config files so the bundled app has sensible defaults
for name in [
    "categories.json",
    "observer.config.json",
    "browser-extension-manifest.json",
    "service_worker.js",
]:
    path = project_root / name
    if path.exists():
        datas.append((str(path), name))

block_cipher = None

a = Analysis(
    ['packaging/launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PyWin32 helpers commonly needed on Windows builds
        'win32timezone',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SelfObserver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SelfObserver'
)
