# -*- mode: python ; coding: utf-8 -*-

import pathlib
import sys



def resolve_project_root():
    """Return project root even when __file__ is undefined (PyInstaller bug)."""

    spec_path = globals().get("__file__")
    if spec_path:
        return pathlib.Path(spec_path).resolve().parent.parent

    # When __file__ is missing, look for the spec path in argv (pyinstaller <spec>)
    for arg in sys.argv[1:]:
        if arg.endswith(".spec"):
            return pathlib.Path(arg).resolve().parent.parent

    # Fallback to current working directory so builds still run
    return pathlib.Path.cwd()


project_root = resolve_project_root()
ui_path = project_root / "ui"

datas = []
# Bundle templates and static assets so Flask can render from the exe
def add_tree(path: pathlib.Path, prefix: str):
    """Recursively append files under *path* with target *prefix* in the bundle."""

    if not path.exists():
        return

    for file in path.rglob("*"):
        if file.is_file():
            relative = file.relative_to(path)
            datas.append((str(file), str(pathlib.Path(prefix) / relative)))


add_tree(ui_path / "templates", "ui/templates")
add_tree(ui_path / "static", "ui/static")

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
