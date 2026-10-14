"""Small HTTP helpers shared by image sources and the exporter."""
import base64
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .config import BROWSER_UA, USER_AGENT

_unverified = ssl._create_unverified_context()


def get(url, headers=None, timeout=25, ua=USER_AGENT):
    h = {"User-Agent": ua, "Accept": "*/*", **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.URLError as e:
        # Some macOS Python installs lack root certificates.
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            with urllib.request.urlopen(req, timeout=timeout, context=_unverified) as r:
                return r.read(), r.headers.get("Content-Type", "")
        raise


def get_json(url, headers=None, timeout=25):
    data, _ = get(url, {"Accept": "application/json", **(headers or {})}, timeout)
    return json.loads(data.decode("utf-8"))


def qs(params):
    return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


def fetch_media(url):
    """Download an image/video from a URL or data: URI. Returns (bytes, ext)."""
    if url.startswith("data:"):
        _, b64 = url.split(",", 1)
        data = base64.b64decode(b64)
    else:
        m = re.search(r"[?&]imgurl=([^&]+)", url)
        if "google." in url and m:
            url = urllib.parse.unquote(m.group(1))
        host = urllib.parse.urlparse(url).netloc
        polite = any(h in host for h in ("wikimedia.org", "openverse", "loc.gov"))
        data, _ = get(url, timeout=60, ua=USER_AGENT if polite else BROWSER_UA)
    return data, detect_ext(data)


def detect_ext(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"GIF8"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"heic", b"mif1"):
            return "avif"
        return "mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    return None
