"""SceneScout local server (FastAPI). Binds to 127.0.0.1 only."""
import json
import os
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, ai, analyze_quick, db, exporter, jobs, script_io, sources
from .config import data_dir, resource_path

app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None)
STATIC = resource_path("scenescout/static")

DEFAULT_SETTINGS = {
    "ui_lang": "vi", "desc_lang": "Vietnamese", "analysis_default": "quick", "ai_chain": [],
    "source_keys": {"pexels": "", "pixabay": "", "unsplash": ""}, "export_root": "", "open_folder": True,
    "show_used_badge": True, "batch": 40, "row_min": 4, "row_max": 8, "wpm": 155, "show_all_projects": False,
    "rules": "", "chat_part": 50,
    "video_fps": 30, "video_res": "1920x1080", "kenburns": True, "tl_mp4": True, "tl_fcpxml": False, "tl_premiere": False,
}


def settings_for(pid):
    s = {**DEFAULT_SETTINGS, **db.get_settings(pid)}
    s["source_keys"] = {**DEFAULT_SETTINGS["source_keys"], **s.get("source_keys", {})}
    return s


# ---------------- meta ----------------
@app.get("/api/meta")
def meta():
    return {"name": APP_NAME, "version": __version__,
            "providers": {k: {kk: vv for kk, vv in v.items() if kk != "kind"} for k, v in ai.PROVIDERS.items()},
            "keyed_sources": sources.KEYED, "defaults": DEFAULT_SETTINGS}


# ---------------- profiles & settings ----------------
@app.get("/api/profiles")
def list_profiles():
    return db.profiles()


@app.post("/api/profiles")
def new_profile(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    try:
        return {"id": db.create_profile(name)}
    except Exception:
        raise HTTPException(409, "profile exists")


@app.delete("/api/profiles/{pid}")
def del_profile(pid: int):
    db.delete_profile(pid)
    return {"ok": True}


@app.get("/api/profiles/{pid}/settings")
def get_settings(pid: int):
    return settings_for(pid)


@app.put("/api/profiles/{pid}/settings")
def put_settings(pid: int, body: dict = Body(...)):
    db.save_settings(pid, {**settings_for(pid), **body})
    return settings_for(pid)


# ---------------- AI helpers ----------------
@app.post("/api/ai/models")
def ai_models(entry: dict = Body(...)):
    try:
        return {"models": ai.list_models(entry)}
    except ai.ProviderError as e:
        raise HTTPException(400, ai.humanize(e, entry.get("provider", "")))


@app.post("/api/ai/autopick")
def ai_autopick(entry: dict = Body(...)):
    try:
        models = ai.list_models(entry)
    except ai.ProviderError as e:
        raise HTTPException(400, str(e))
    model = ai.pick_default(entry.get("provider", ""), models)
    if not model:
        raise HTTPException(400, "no usable model found")
    return {"model": model, "count": len(models)}


@app.post("/api/ai/test")
def ai_test(entry: dict = Body(...)):
    try:
        out = ai.chat(entry, "Reply with JSON only.", 'Return {"ok": true}.')
        ai.parse_json(out)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, ai.humanize(e, entry.get("provider", "")))


# ---------------- projects ----------------
def _analyze_job(pid, mode, profile_id, progress=None):
    p = db.get_project(pid)
    s = settings_for(profile_id)
    rows = [{k: r[k] for k in ("stt", "start", "end", "text", "loidan")} | {"mota": "", "keyword": "", "keyword_phu": ""}
            for r in p["rows"]]
    ai_error = None
    if mode == "ai" and not any(c.get("model") for c in s["ai_chain"]):
        ai_error = "Chưa cài AI hoặc chưa chọn model. Vào Cài đặt → AI."
    elif mode == "ai":
        try:
            rows, ctx, report = ai.analyze(rows, p["title"], p["thumbnail"], s["ai_chain"], s["desc_lang"],
                                           int(s.get("batch", 40)), progress, s.get("rules", ""))
            report["mode"] = "ai"
        except ai.ProviderError as e:
            ai_error = str(e)
    if mode != "ai" or ai_error:
        rows, ctx = analyze_quick.analyze(rows, p["title"])
        report = {"mode": "quick", "calls": 0, "fallback_rows": [], "log": []}
    for r in rows:
        db.update_row(pid, r["stt"], mota=r["mota"], keyword=r["keyword"], keyword_phu=r["keyword_phu"])
    ctx["report"] = {k: report.get(k) for k in ("mode", "calls", "providers", "fallback_rows")} | {"log": report.get("log", [])[-8:]}
    db.update_project(pid, analysis=ctx.get("mode", mode), context=ctx)
    if ai_error:  # keywords from Quick mode are saved, so the project is still usable
        raise ValueError(ai_error + " Đã tạm dùng chế độ Nhanh.")
    return report


@app.get("/api/projects")
def projects(profile: int = 0, all: int = 0):
    return db.list_projects(None if all else profile)


@app.post("/api/projects")
def create_project(body: dict = Body(...)):
    profile_id = int(body["profile_id"])
    s = settings_for(profile_id)
    rows, kind = script_io.load_any(body.get("filename", "script.srt"), body.get("content", ""),
                                    body_min=float(s["row_min"]), body_max=float(s["row_max"]), wpm=int(s["wpm"]))
    if not rows:
        raise HTTPException(400, "no rows found in the file")
    name = (body.get("name") or Path(body.get("filename", "Project")).stem).strip()
    pid = db.create_project(name, profile_id, rows, body.get("title", ""), body.get("thumbnail", ""),
                            body.get("filename", ""), "csv" if kind == "csv" else "pending")
    job = None
    if kind != "csv" or not any(r.get("keyword") for r in rows):
        job = jobs.start(_analyze_job, pid, body.get("mode", s["analysis_default"]), profile_id)
    return {"id": pid, "job": job, "rows": len(rows), "kind": kind}


@app.get("/api/projects/{pid}")
def project(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404)
    return p


@app.patch("/api/projects/{pid}")
def patch_project(pid: int, body: dict = Body(...)):
    db.update_project(pid, **body)
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    db.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/duplicate")
def duplicate(pid: int, body: dict = Body(...)):
    return {"id": db.duplicate_project(pid, int(body["profile_id"]))}


@app.post("/api/projects/{pid}/reanalyze")
def reanalyze(pid: int, body: dict = Body(...)):
    return {"job": jobs.start(_analyze_job, pid, body.get("mode", "quick"), int(body["profile_id"]))}


@app.patch("/api/projects/{pid}/rows/{stt}")
def patch_row(pid: int, stt: int, body: dict = Body(...)):
    if "sel" in body and isinstance(body["sel"], dict):
        body["sel"] = json.dumps(body["sel"])
    editor = body.pop("editor", None)
    db.update_row(pid, stt, **body)
    if editor:
        db.update_project(pid, last_editor=int(editor))
    return {"ok": True}


# ---------------- chat bridge: use Claude / ChatGPT / Gemini chat without an API key ----------------
@app.post("/api/projects/{pid}/chat-prompt")
def chat_prompt(pid: int, body: dict = Body(...)):
    p = db.get_project(pid)
    s = settings_for(int(body["profile_id"]))
    stts = [int(x) for x in body.get("stts") or []] or [r["stt"] for r in p["rows"]]
    return {"prompt": ai.chat_prompt(p["rows"], stts, p["title"], p["thumbnail"], s["desc_lang"], s.get("rules", "")),
            "stts": stts}


@app.post("/api/projects/{pid}/chat-import")
def chat_import(pid: int, body: dict = Body(...)):
    p = db.get_project(pid)
    valid = {r["stt"] for r in p["rows"]}
    got = ai.extract_rows(body.get("text", ""))
    updated = []
    for stt, item in got.items():
        kw = (item.get("keyword") or "").strip()
        if stt in valid and kw:
            db.update_row(pid, stt, mota=(item.get("mota") or "").strip(), keyword=kw,
                          keyword_phu=(item.get("keyword_phu") or kw).strip())
            updated.append(stt)
    asked = [int(x) for x in body.get("stts") or []]
    missing = [x for x in asked if x not in updated]
    if updated:
        db.update_project(pid, analysis="chat")
    return {"updated": sorted(updated), "missing": missing, "found": len(got)}


@app.get("/api/rules/default")
def default_rules():
    return {"rules": ai.RULES.replace("{{", "{").replace("}}", "}")}


@app.get("/api/projects/{pid}/package")
def package(pid: int):
    p = db.get_project(pid)
    data = json.dumps({"scenescout": __version__, "project": p}, ensure_ascii=False)
    fname = exporter.safe_name(p["name"]) + ".scenescout.json"
    return Response(data, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/projects/import")
def import_package(body: dict = Body(...)):
    pkg = json.loads(body["content"])
    p = pkg["project"]
    pid = db.create_project(p["name"], int(body["profile_id"]), p["rows"], p.get("title", ""), p.get("thumbnail", ""),
                            p.get("source_file", ""), p.get("analysis", ""), p.get("context", {}))
    for r in p["rows"]:
        db.update_row(pid, r["stt"], cands=r.get("cands", {}), sel=r.get("sel", ""), flag=r.get("flag", ""))
    return {"id": pid}


# ---------------- search, uploads, library ----------------
@app.get("/api/search")
def search(tab: str, q: str = "", q2: str = "", kind: str = "image", profile: int = 0):
    s = settings_for(profile) if profile else DEFAULT_SETTINGS
    res = sources.search(tab, q, q2, kind, s["source_keys"])
    used = db.library_used_map()
    for it in res["results"]:
        it["used_in"] = used.get(it["full"], [])
    return res


@app.post("/api/upload")
def upload(body: dict = Body(...)):
    try:
        return {"url": exporter.save_upload(body["data"])}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/uploads/{name}")
def get_upload(name: str):
    p = exporter.uploads_dir() / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/library/file/{lid}")
def library_file(lid: int):
    r = db.q1("SELECT path FROM library WHERE id=?", (lid,))
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404)
    return FileResponse(r["path"])


@app.get("/api/library/stats")
def library_stats():
    r = db.q1("SELECT COUNT(*) AS n FROM library")
    return {"items": r["n"] if r else 0}


# ---------------- export & jobs ----------------
@app.post("/api/projects/{pid}/export")
def export(pid: int, body: dict = Body(...)):
    s = settings_for(int(body["profile_id"]))
    only = set(body.get("only") or []) or None
    tl = body.get("timeline") or None
    if tl:
        w, h = (s.get("video_res") or "1920x1080").split("x")
        tl = {**tl, "fps": int(s.get("video_fps", 30)), "width": int(w), "height": int(h)}
        if tl.get("audio"):
            ap = data_dir() / "audio" / Path(tl["audio"]).name
            tl["audio"] = str(ap) if ap.exists() else None
    return {"job": jobs.start(exporter.export_project, pid, s, only, body.get("defaults") or {}, tl)}


@app.post("/api/audio")
async def upload_audio(request: Request):
    """Voice-over upload (raw bytes). Returns a token used by the export and the file's duration."""
    import uuid
    import urllib.parse
    name = Path(urllib.parse.unquote(request.headers.get("x-filename", "voice.mp3"))).name
    ext = Path(name).suffix.lower() or ".mp3"
    if ext not in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
        raise HTTPException(400, "unsupported audio type")
    folder = data_dir() / "audio"
    folder.mkdir(exist_ok=True)
    token = uuid.uuid4().hex + ext
    (folder / token).write_bytes(await request.body())
    from . import timeline
    return {"token": token, "duration": timeline.media_duration(folder / token), "name": name}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    return jobs.get(jid)


@app.post("/api/open-folder")
def open_folder(body: dict = Body(...)):
    exporter.open_folder(body["path"])
    return {"ok": True}


# ---------------- static UI ----------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
