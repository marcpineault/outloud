# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller packaging/OutLoud.spec   (from the repo root; output in dist/)
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.dirname(SPECPATH)
SRC = os.path.join(ROOT, "src")

hidden = collect_submodules("outloud")
if sys.platform == "darwin":
    hidden += ["Vision", "Quartz", "Foundation", "objc"]
    icon = os.path.join(SPECPATH, "icon.icns")
elif sys.platform == "win32":
    hidden += ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes", "win32com", "winocr"]
    icon = os.path.join(SPECPATH, "icon.ico")
else:
    icon = None

a = Analysis(
    [os.path.join(SRC, "outloud", "__main__.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OutLoud",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if icon and os.path.exists(icon) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OutLoud")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OutLoud.app",
        icon=icon if os.path.exists(icon) else None,
        bundle_identifier="ca.pineault.outloud",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": "PDF", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["com.adobe.pdf"]},
                {"CFBundleTypeName": "Text", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["public.plain-text"]},
            ],
        },
    )
