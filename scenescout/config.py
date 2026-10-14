"""Paths and app-wide settings. All user data lives outside the repo."""
import os
import sys
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("SCENESCOUT_DATA")
    if override:
        base = Path(override)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def library_dir() -> Path:
    p = data_dir() / "library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_export_dir() -> Path:
    p = Path.home() / "Documents" / APP_NAME / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_path(rel: str) -> Path:
    """Works both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


DB_PATH = None  # set lazily by db.connect()
USER_AGENT = f"{APP_NAME}/2.0 (+https://github.com/; desktop tool for video editors)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
