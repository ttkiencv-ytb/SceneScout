"""Image / video sources. Each source returns a list of candidate dicts:
{id, source, kind, thumb, full, page, title, credit, license, download_ping}
Sources needing a key are skipped silently when the key is missing.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import db
from .net import get_json, qs

CACHE_SECONDS = 24 * 3600  # Pixabay requires 24h caching; applied to all sources
_cooldown = {}
_lock = threading.Lock()


def _cool(name, seconds):
    with _lock:
        _cooldown[name] = time.time() + seconds


def _is_cool(name):
    return time.time() < _cooldown.get(name, 0)


# ---------------- history / archives (no key) ----------------
def wikimedia(q, kind="image", keys=None, n=10):
    if kind != "image":
        return []
    data = get_json("https://commons.wikimedia.org/w/api.php?" + qs({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": q + " filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "330"}))
    out = []
    for p in sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]
        thumb, orig, w, mime = ii.get("thumburl"), ii.get("url"), ii.get("width") or 0, ii.get("mime", "")
        if not thumb or not orig:
            continue
        if mime in ("image/jpeg", "image/png") and w <= 1920:
            full = orig
        else:
            tw = next((x for x in (1920, 1280, 960) if w >= x), 0)
            full = re.sub(r"/((?:lossy-)?page1-)?\d+px-", lambda m: "/" + (m.group(1) or "") + f"{tw}px-", thumb, count=1) if tw else thumb
        meta = ii.get("extmetadata", {})
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:120]
        out.append({"id": f"wm:{p.get('pageid')}", "source": "Wikimedia", "kind": "image", "thumb": thumb, "full": full,
                    "page": ii.get("descriptionurl", ""), "title": p.get("title", "").replace("File:", ""),
                    "credit": artist, "license": lic})
    return out


def loc(q, kind="image", keys=None, n=10):
    """Library of Congress Prints & Photographs (public JSON API, no key)."""
    if kind != "image" or _is_cool("loc"):
        return []
    try:
        data = get_json("https://www.loc.gov/pictures/search/?" + qs({"q": q, "fo": "json", "c": n}))
    except Exception as e:
        _cool("loc", 300)
        raise
    out = []
    for r in data.get("results", []):
        img = r.get("image") or {}
        thumb = img.get("thumb") or img.get("full")
        if not thumb or "notdigitized" in thumb:
            continue
        thumb = thumb if thumb.startswith("http") else "https:" + thumb
        # 150px thumbnails have a larger "r.jpg" variant (~640px) on the same path
        full = re.sub(r"_150px\.jpg$", "r.jpg", thumb)
        out.append({"id": f"loc:{r.get('pk', '')}", "source": "Library of Congress", "kind": "image",
                    "thumb": thumb, "full": full, "page": (r.get("links") or {}).get("item", ""),
                    "title": (r.get("title") or "")[:160], "credit": r.get("creator") or "Library of Congress",
                    "license": "Check rights on item page", "fallback": thumb})
    return out


def openverse(q, kind="image", keys=None, n=10):
    if kind != "image" or _is_cool("openverse"):
        return []
    try:
        data = get_json("https://api.openverse.org/v1/images/?" + qs({
            "q": q, "page_size": n, "license_type": "commercial", "mature": "false"}))
    except Exception as e:
        if "429" in str(e) or "401" in str(e):
            _cool("openverse", 600)
        return []
    return [{"id": f"ov:{r.get('id')}", "source": "Openverse", "kind": "image", "thumb": r.get("thumbnail") or r["url"],
             "full": r["url"], "page": r.get("foreign_landing_url", ""), "title": r.get("title") or "",
             "credit": r.get("creator") or "", "license": f"{r.get('license', '')} {r.get('license_version', '')}".strip()}
            for r in data.get("results", []) if r.get("url")]


# ---------------- stock (free API keys) ----------------
def pexels(q, kind="image", keys=None, n=10):
    key = (keys or {}).get("pexels")
    if not key or _is_cool("pexels"):
        return []
    h = {"Authorization": key}
    try:
        if kind == "video":
            data = get_json("https://api.pexels.com/videos/search?" + qs({"query": q, "per_page": n}), h)
            out = []
            for v in data.get("videos", []):
                files = sorted([f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and (f.get("width") or 0) <= 1920],
                               key=lambda f: f.get("width") or 0)
                if files:
                    out.append({"id": f"px:v{v['id']}", "source": "Pexels", "kind": "video", "thumb": v.get("image", ""),
                                "full": files[-1]["link"], "page": v.get("url", ""), "title": "",
                                "credit": (v.get("user") or {}).get("name", ""), "license": "Pexels License",
                                "duration": v.get("duration")})
            return out
        data = get_json("https://api.pexels.com/v1/search?" + qs({"query": q, "per_page": n}), h)
        return [{"id": f"px:{p['id']}", "source": "Pexels", "kind": "image", "thumb": p["src"]["medium"],
                 "full": p["src"].get("large2x") or p["src"]["original"], "page": p.get("url", ""),
                 "title": p.get("alt", ""), "credit": p.get("photographer", ""), "license": "Pexels License"}
                for p in data.get("photos", [])]
    except Exception as e:
        if "429" in str(e):
            _cool("pexels", 900)
        raise


def pixabay(q, kind="image", keys=None, n=10):
    key = (keys or {}).get("pixabay")
    if not key or _is_cool("pixabay"):
        return []
    try:
        if kind == "video":
            data = get_json("https://pixabay.com/api/videos/?" + qs({"key": key, "q": q[:100], "per_page": max(n, 3), "safesearch": "true"}))
            out = []
            for h in data.get("hits", []):
                v = h.get("videos", {})
                best = v.get("large") if (v.get("large") or {}).get("url") else v.get("medium") or {}
                thumb = (v.get("medium") or {}).get("thumbnail") or (v.get("tiny") or {}).get("thumbnail") or ""
                if best.get("url"):
                    out.append({"id": f"pb:v{h['id']}", "source": "Pixabay", "kind": "video", "thumb": thumb,
                                "full": best["url"], "page": h.get("pageURL", ""), "title": h.get("tags", ""),
                                "credit": h.get("user", ""), "license": "Pixabay Content License",
                                "duration": h.get("duration")})
            return out
        data = get_json("https://pixabay.com/api/?" + qs({"key": key, "q": q[:100], "image_type": "photo",
                                                         "per_page": max(n, 3), "safesearch": "true"}))
        return [{"id": f"pb:{h['id']}", "source": "Pixabay", "kind": "image", "thumb": h.get("webformatURL", ""),
                 "full": h.get("largeImageURL") or h.get("webformatURL", ""), "page": h.get("pageURL", ""),
                 "title": h.get("tags", ""), "credit": h.get("user", ""), "license": "Pixabay Content License"}
                for h in data.get("hits", [])]
    except Exception as e:
        if "429" in str(e):
            _cool("pixabay", 120)
        raise


def unsplash(q, kind="image", keys=None, n=10):
    key = (keys or {}).get("unsplash")
    if kind != "image" or not key or _is_cool("unsplash"):
        return []
    try:
        data = get_json("https://api.unsplash.com/search/photos?" + qs({"query": q, "per_page": n}),
                        {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"})
    except Exception as e:
        if "403" in str(e) or "429" in str(e):
            _cool("unsplash", 1800)
        raise
    return [{"id": f"us:{r['id']}", "source": "Unsplash", "kind": "image", "thumb": r["urls"]["small"],
             "full": r["urls"]["regular"], "page": r["links"]["html"], "title": r.get("alt_description") or "",
             "credit": f"Photo by {r['user']['name']} on Unsplash", "license": "Unsplash License",
             "download_ping": r["links"].get("download_location", "")} for r in data.get("results", [])]


# ---------------- registry ----------------
TABS = {
    "history": [("Wikimedia", wikimedia), ("Library of Congress", loc), ("Openverse", openverse)],
    "stock": [("Pexels", pexels), ("Pixabay", pixabay), ("Unsplash", unsplash)],
}
KEYED = {"pexels": "https://www.pexels.com/api/", "pixabay": "https://pixabay.com/api/docs/",
         "unsplash": "https://unsplash.com/developers"}


def expand_queries(q, q2=""):
    """Archive search engines AND every word, so long keywords often return nothing.
    Try the keyword, the fallback, then progressively shorter versions."""
    out = []

    def add(x):
        x = " ".join(x.split())
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    add(q)
    add(q2)
    no_year = re.sub(r"\b(1[89]\d\d|20\d\d)\b", "", q)
    add(no_year)
    words = no_year.split()
    if len(words) > 3:
        add(" ".join(words[:3]))
        add(" ".join(words[-3:]))
    return out[:5]


def _run_source(name, fn, qq, kind, keys):
    ck = f"{fn.__name__}|{kind}|{qq.lower()}"
    items = db.cache_get(ck, CACHE_SECONDS)
    if items is not None:
        return items, None
    try:
        items = fn(qq, kind, keys)
        db.cache_put(ck, items)
        return items, None
    except Exception as e:
        return [], f"{name}: {str(e)[:120]}"


def search(tab, q, q2="", kind="image", keys=None, want=15, enough=8):
    """Search every source in a tab (in parallel), widening the query until results are sufficient."""
    if tab == "library":
        return {"results": [_lib_item(r) for r in db.library_search(f"{q} {q2}", want)], "errors": []}
    sources = TABS.get(tab, [])
    results, seen, errors = [], set(), []
    with ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        for qq in expand_queries(q, q2):
            futures = [pool.submit(_run_source, name, fn, qq, kind, keys) for name, fn in sources]
            for f in futures:
                items, err = f.result()
                if err and err not in errors:
                    errors.append(err)
                for it in items:
                    if it["full"] not in seen:
                        seen.add(it["full"])
                        results.append(it)
            if len(results) >= enough:
                break
    return {"results": results[:want], "errors": errors if not results else []}


def _lib_item(r):
    return {"id": f"lib:{r['id']}", "source": "Đã dùng", "kind": r.get("kind", "image"),
            "thumb": f"/api/library/file/{r['id']}", "full": f"/api/library/file/{r['id']}",
            "page": r.get("source_url", ""), "title": r.get("title") or r.get("keyword", ""),
            "credit": r.get("credit", ""), "license": r.get("license", ""), "orig_source": r.get("source", ""),
            "lib_id": r["id"]}
