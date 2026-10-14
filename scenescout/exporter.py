"""Export: download chosen media with timecode names, write lists and credits,
and register everything in the shared library for reuse in later videos."""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db
from .config import data_dir, default_export_dir, library_dir
from .net import fetch_media, get


def safe_name(s):
    return (re.sub(r"[^\w\-]+", "-", s, flags=re.UNICODE).strip("-") or "project")[:60]


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def uploads_dir():
    p = data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_upload(data_url):
    """Manual drops/pastes arrive as data: URLs. Store them once, return a local URL."""
    data, ext = fetch_media(data_url)
    if not ext:
        raise ValueError("not an image or video")
    sha = hashlib.sha1(data).hexdigest()
    name = f"{sha}.{ext}"
    (uploads_dir() / name).write_bytes(data)
    return f"/api/uploads/{name}"


def _read_local(url):
    m = re.match(r"^/api/(uploads|library/file)/(.+)$", url)
    if not m:
        return None
    if m.group(1) == "uploads":
        p = uploads_dir() / Path(m.group(2)).name
    else:
        row = db.q1("SELECT path FROM library WHERE id=?", (int(m.group(2)),))
        p = Path(row["path"]) if row else None
    return p.read_bytes() if p and p.exists() else None


def _fetch(cand):
    url = cand["full"]
    local = _read_local(url)
    if local is not None:
        from .net import detect_ext
        return local, detect_ext(local)
    try:
        return fetch_media(url)
    except Exception:
        if cand.get("fallback"):
            return fetch_media(cand["fallback"])
        raise


def export_project(pid, profile_settings, only=None, defaults=None, timeline_opts=None, progress=None):
    progress = progress or (lambda *a, **k: None)
    p = db.get_project(pid)
    outdir = Path(p["export_dir"]) if (only and p.get("export_dir")) else \
        Path(profile_settings.get("export_root") or default_export_dir()) / f"{safe_name(p['name'])}_{time.strftime('%Y%m%d-%H%M')}"
    outdir.mkdir(parents=True, exist_ok=True)
    keys = profile_settings.get("source_keys", {})
    rows = [r for r in p["rows"] if not only or r["stt"] in only]
    defaults = {int(k): v for k, v in (defaults or {}).items()}
    for r in rows:
        if not r["sel"] and r["stt"] in defaults:
            r["sel"] = json.dumps(defaults[r["stt"]])
    todo = [r for r in rows if not r["flag"] and r["sel"]]
    results, credits = [], []

    def work(r):
        cand = json.loads(r["sel"])
        name = f"{r['stt']:04d}_{(r['start'] or '00:00:00').replace(':', '-')}"
        try:
            data, ext = _fetch(cand)
            if not ext or len(data) < 800:
                raise ValueError("the source did not return an image or video file")
            for old in outdir.glob(name + ".*"):
                old.unlink()
            target = outdir / f"{name}.{ext}"
            target.write_bytes(data)
            if cand.get("download_ping") and keys.get("unsplash"):  # Unsplash API guideline
                try:
                    get(cand["download_ping"], {"Authorization": f"Client-ID {keys['unsplash']}"})
                except Exception:
                    pass
            sha = hashlib.sha1(data).hexdigest()
            lib_path = library_dir() / f"{sha}.{ext}"
            if not lib_path.exists():
                shutil.copyfile(target, lib_path)
            meta = {**cand, "keyword": r["keyword"], "mota": r["mota"], "kind": cand.get("kind", "image"),
                    "source": cand.get("orig_source") or cand.get("source", "")}
            db.library_add(sha, lib_path, meta, p["name"])
            return {"stt": r["stt"], "ok": True, "file": target.name, "cand": cand}
        except Exception as e:
            return {"stt": r["stt"], "ok": False, "reason": str(e)[:200]}

    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(work, todo):
            results.append(res)
            done += 1
            progress("download", done, len(todo))
    ok = [x for x in results if x["ok"]]
    failed = [x for x in results if not x["ok"]]

    if not only:
        flagged = [r for r in rows if r["flag"] or not r["sel"]]
        with open(outdir / "rows-AI-Envato-missing.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["STT", "Timecode", "Type", "Narration", "Shot description", "Keyword"])
            for r in flagged:
                kind = {"AI": "AI IMAGE", "ENVATO": "ENVATO"}.get(r["flag"], "NO IMAGE")
                w.writerow([r["stt"], r["start"], kind, r["loidan"], r["mota"], r["keyword"]])
    with open(outdir / "credits.csv", "a" if only else "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not only:
            w.writerow(["File", "Source", "Title", "Credit", "License", "Page"])
        for x in ok:
            c = x["cand"]
            w.writerow([x["file"], c.get("orig_source") or c.get("source", ""), c.get("title", ""),
                        c.get("credit", ""), c.get("license", ""), c.get("page", "")])
    manifest = {"project": p["name"], "exported": time.strftime("%Y-%m-%d %H:%M"),
                "rows": [{"stt": r["stt"], "start": r["start"], "end": r["end"], "flag": r["flag"],
                          "file": next((x["file"] for x in ok if x["stt"] == r["stt"]), None)} for r in p["rows"]]}
    (outdir / "scenescout-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    db.update_project(pid, export_dir=str(outdir))
    if failed:
        with open(outdir / "download-errors.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["STT", "Reason"])
            for x in failed:
                w.writerow([x["stt"], x["reason"]])
    made = {}
    if timeline_opts and any(timeline_opts.get(k) for k in ("mp4", "fcpxml", "premiere")):
        from . import timeline
        fresh = db.get_project(pid)
        made = timeline.export_timeline(fresh["rows"], outdir, p["name"], timeline_opts, progress)
    if profile_settings.get("open_folder", True):
        open_folder(outdir)
    return {"outdir": str(outdir), "ok": len(ok), "failed": failed, "timeline": made,
            "flagged": sum(1 for r in rows if r["flag"]), "missing": sum(1 for r in rows if not r["flag"] and not r["sel"])}
