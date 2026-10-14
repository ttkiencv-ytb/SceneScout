"""SQLite storage: profiles, projects, rows, the shared image library, and a search cache."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import data_dir

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, settings TEXT DEFAULT '{}',
  created REAL);
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_id INTEGER, last_editor INTEGER,
  title TEXT DEFAULT '', thumbnail TEXT DEFAULT '', source_file TEXT DEFAULT '',
  analysis TEXT DEFAULT '', context TEXT DEFAULT '{}',
  export_dir TEXT DEFAULT '', created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS rows(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, stt INTEGER NOT NULL,
  start TEXT, end TEXT, text TEXT, loidan TEXT, mota TEXT, keyword TEXT, keyword_phu TEXT,
  cands TEXT DEFAULT '{}', sel TEXT DEFAULT '', flag TEXT DEFAULT '', note TEXT DEFAULT '',
  UNIQUE(project_id, stt));
CREATE TABLE IF NOT EXISTS library(
  id INTEGER PRIMARY KEY, sha1 TEXT UNIQUE, path TEXT, orig_url TEXT, source TEXT,
  source_url TEXT, title TEXT, credit TEXT, license TEXT, kind TEXT DEFAULT 'image',
  keyword TEXT, mota TEXT, used_in TEXT DEFAULT '[]', added REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(keyword, mota, title, content='library', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS lib_ai AFTER INSERT ON library BEGIN
  INSERT INTO library_fts(rowid, keyword, mota, title) VALUES (new.id, new.keyword, new.mota, new.title); END;
CREATE TRIGGER IF NOT EXISTS lib_au AFTER UPDATE ON library BEGIN
  INSERT INTO library_fts(library_fts, rowid, keyword, mota, title) VALUES('delete', old.id, old.keyword, old.mota, old.title);
  INSERT INTO library_fts(rowid, keyword, mota, title) VALUES (new.id, new.keyword, new.mota, new.title); END;
CREATE TABLE IF NOT EXISTS search_cache(
  key TEXT PRIMARY KEY, payload TEXT, created REAL);
"""


def conn():
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(data_dir() / "scenescout.db", check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            cols = {r[1] for r in _conn.execute("PRAGMA table_info(rows)")}
            for col in ("t0", "t1"):  # precise seconds (v2.1); older projects fall back to the HH:MM:SS text
                if col not in cols:
                    _conn.execute(f"ALTER TABLE rows ADD COLUMN {col} REAL")
            _conn.commit()
        return _conn


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


# ---------- profiles ----------
def profiles():
    return q("SELECT id, name, created FROM profiles ORDER BY name")


def create_profile(name):
    with tx() as c:
        cur = c.execute("INSERT INTO profiles(name, settings, created) VALUES (?,?,?)", (name.strip(), "{}", time.time()))
        return cur.lastrowid


def get_settings(pid):
    r = q1("SELECT settings FROM profiles WHERE id=?", (pid,))
    return json.loads(r["settings"]) if r else {}


def save_settings(pid, settings):
    with tx() as c:
        c.execute("UPDATE profiles SET settings=? WHERE id=?", (json.dumps(settings), pid))


def delete_profile(pid):
    with tx() as c:
        c.execute("DELETE FROM profiles WHERE id=?", (pid,))


# ---------- projects ----------
def list_projects(profile_id=None):
    sql = """SELECT p.*, pr.name AS owner,
               (SELECT COUNT(*) FROM rows r WHERE r.project_id=p.id) AS n_rows,
               (SELECT COUNT(*) FROM rows r WHERE r.project_id=p.id AND (r.sel!='' OR r.flag!='')) AS n_done
             FROM projects p LEFT JOIN profiles pr ON pr.id=p.profile_id"""
    if profile_id:
        return q(sql + " WHERE p.profile_id=? ORDER BY p.updated DESC", (profile_id,))
    return q(sql + " ORDER BY p.updated DESC")


def create_project(name, profile_id, rows, title="", thumbnail="", source_file="", analysis="quick", context=None):
    now = time.time()
    with tx() as c:
        cur = c.execute(
            "INSERT INTO projects(name, profile_id, last_editor, title, thumbnail, source_file, analysis, context, created, updated)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, profile_id, profile_id, title, thumbnail, source_file, analysis, json.dumps(context or {}), now, now))
        pid = cur.lastrowid
        c.executemany(
            "INSERT INTO rows(project_id, stt, start, end, text, loidan, mota, keyword, keyword_phu, t0, t1)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(pid, r["stt"], r["start"], r["end"], r.get("text", ""), r.get("loidan", ""), r.get("mota", ""),
              r.get("keyword", ""), r.get("keyword_phu", ""), r.get("t0"), r.get("t1")) for r in rows])
        return pid


def get_project(pid):
    p = q1("SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        return None
    p["context"] = json.loads(p.get("context") or "{}")
    rows = q("SELECT * FROM rows WHERE project_id=? ORDER BY stt", (pid,))
    for r in rows:
        r["cands"] = json.loads(r["cands"] or "{}")
    p["rows"] = rows
    return p


def update_project(pid, **fields):
    allowed = {"name", "title", "thumbnail", "analysis", "export_dir", "last_editor", "context"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(json.dumps(v) if k == "context" else v)
    sets.append("updated=?")
    vals.append(time.time())
    with tx() as c:
        c.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", (*vals, pid))


def update_row(pid, stt, **fields):
    allowed = {"mota", "keyword", "keyword_phu", "cands", "sel", "flag", "note"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(json.dumps(v) if k == "cands" else v)
    if not sets:
        return
    with tx() as c:
        c.execute(f"UPDATE rows SET {', '.join(sets)} WHERE project_id=? AND stt=?", (*vals, pid, stt))
        c.execute("UPDATE projects SET updated=? WHERE id=?", (time.time(), pid))


def duplicate_project(pid, profile_id):
    p = get_project(pid)
    rows = [{k: r.get(k) for k in ("stt", "start", "end", "text", "loidan", "mota", "keyword", "keyword_phu", "t0", "t1")} for r in p["rows"]]
    return create_project(p["name"] + " (bản sao)", profile_id, rows, p["title"], p["thumbnail"], p["source_file"], p["analysis"], p["context"])


def delete_project(pid):
    with tx() as c:
        c.execute("DELETE FROM rows WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))


# ---------- library ----------
def library_add(sha1, path, meta, project_name):
    existing = q1("SELECT id, used_in FROM library WHERE sha1=?", (sha1,))
    if existing:
        used = json.loads(existing["used_in"] or "[]")
        if project_name not in used:
            used.append(project_name)
        with tx() as c:
            c.execute("UPDATE library SET used_in=?, keyword=?, mota=? WHERE id=?",
                      (json.dumps(used), meta.get("keyword", ""), meta.get("mota", ""), existing["id"]))
        return existing["id"]
    with tx() as c:
        cur = c.execute(
            "INSERT INTO library(sha1, path, orig_url, source, source_url, title, credit, license, kind, keyword, mota, used_in, added)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sha1, str(path), meta.get("full", ""), meta.get("source", ""), meta.get("page", ""), meta.get("title", ""),
             meta.get("credit", ""), meta.get("license", ""), meta.get("kind", "image"), meta.get("keyword", ""),
             meta.get("mota", ""), json.dumps([project_name]), time.time()))
        return cur.lastrowid


def library_search(text, limit=15):
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in text).split() if len(w) > 1]
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in words[:12])
    return q("""SELECT l.* FROM library_fts f JOIN library l ON l.id=f.rowid
                WHERE library_fts MATCH ? ORDER BY bm25(library_fts) LIMIT ?""", (match, limit))


def library_used_map():
    """sha1/url -> list of project names, for 'used in' badges."""
    m = {}
    for r in q("SELECT id, orig_url, used_in FROM library"):
        used = json.loads(r["used_in"] or "[]")
        for key in (r["orig_url"], f"/api/library/file/{r['id']}"):
            if key:
                m[key] = used
    return m


# ---------- cache ----------
def cache_get(key, max_age):
    r = q1("SELECT payload, created FROM search_cache WHERE key=?", (key,))
    if r and time.time() - r["created"] < max_age:
        return json.loads(r["payload"])
    return None


def cache_put(key, payload):
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO search_cache(key, payload, created) VALUES (?,?,?)",
                  (key, json.dumps(payload), time.time()))
