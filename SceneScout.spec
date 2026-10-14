# PyInstaller build spec. Build with:  pyinstaller SceneScout.spec
# Produces dist/SceneScout.app (macOS) or dist/SceneScout/SceneScout.exe (Windows).
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

sys.path.insert(0, ".")
from scenescout import __version__  # noqa: E402

datas = [("scenescout/static", "scenescout/static"), ("scenescout/assets", "scenescout/assets")]
datas += collect_data_files("imageio_ffmpeg")          # bundled ffmpeg binary
hidden = collect_submodules("uvicorn") + ["webview"]

a = Analysis(["desktop.py"], pathex=["."], datas=datas, hiddenimports=hidden,
             excludes=["matplotlib", "numpy", "pandas", "scipy", "PyQt5", "PyQt6", "PySide2", "PySide6"])
pyz = PYZ(a.pure)
icon = "scenescout/assets/icon/icon.icns" if sys.platform == "darwin" else "scenescout/assets/icon/icon.ico"
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SceneScout", console=False, icon=icon,
          upx=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="SceneScout", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="SceneScout.app", icon=icon, bundle_identifier="io.github.scenescout",
                 info_plist={"CFBundleShortVersionString": __version__.split("-")[0], "CFBundleVersion": __version__,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"})
