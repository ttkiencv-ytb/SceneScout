"""Read SRT / CSV / plain-text scripts and split them into image rows."""
import csv
import io
import re

TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
INTRO_SECONDS, INTRO_MIN, INTRO_MAX = 60, 3.0, 5.0
BODY_MIN, BODY_MAX = 4.0, 8.0
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]?$")


def parse_time(s):
    m = TIME_RE.search(s)
    if not m:
        raise ValueError("bad timecode: " + s)
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000.0


def fmt_tc(sec):
    s = int(sec)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def parse_srt(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                try:
                    start, end = parse_time(a), parse_time(b)
                except ValueError:
                    break
                body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(lines[i + 1:]))).strip()
                if body:
                    cues.append((start, end, body))
                break
    return sorted(cues, key=lambda c: c[0])


def split_long_cues(cues, max_len=BODY_MAX):
    """Long subtitle cues (common in TTS exports) are split at sentence ends,
    with time interpolated by word count."""
    out = []
    for start, end, text in cues:
        if end - start <= max_len:
            out.append((start, end, text))
            continue
        parts = [p for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
        if len(parts) < 2:
            out.append((start, end, text))
            continue
        total = sum(len(p.split()) for p in parts)
        t = start
        for p in parts:
            d = (end - start) * len(p.split()) / total
            out.append((t, t + d, p))
            t += d
    return out


def group_cues(cues, body_min=BODY_MIN, body_max=BODY_MAX):
    cues = split_long_cues(cues, body_max)
    groups, cur = [], []

    def close():
        if cur:
            groups.append({"start": cur[0][0], "end": cur[-1][1], "text": " ".join(c[2] for c in cur)})
            cur.clear()

    for cue in cues:
        if cur:
            g0 = cur[0][0]
            lo, hi = (INTRO_MIN, INTRO_MAX) if g0 < INTRO_SECONDS else (body_min, body_max)
            now, nxt = cur[-1][1] - g0, cue[1] - g0
            if (now >= lo and (_SENTENCE_END.search(cur[-1][2]) or nxt > hi)) or (nxt > hi + 3 and now >= 2):
                close()
        cur.append(cue)
    close()
    return groups


def lead(text, n=10):
    w = text.split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


def rows_from_srt(text, body_min=BODY_MIN, body_max=BODY_MAX):
    out = []
    for i, g in enumerate(group_cues(parse_srt(text), body_min, body_max), 1):
        out.append({"stt": i, "start": fmt_tc(g["start"]), "end": fmt_tc(g["end"]),
                    "t0": round(g["start"], 3), "t1": round(g["end"], 3),
                    "text": g["text"], "loidan": lead(g["text"])})
    return out


def rows_from_plain(text, wpm=155):
    """Plain script without timecodes: split into ~15-word chunks, estimate timecodes from reading speed."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if s.strip()]
    out, buf, t = [], [], 0.0
    for s in sentences:
        buf.append(s)
        if len(" ".join(buf).split()) >= 15:
            chunk = " ".join(buf)
            dur = len(chunk.split()) / wpm * 60
            out.append({"stt": len(out) + 1, "start": fmt_tc(t), "end": fmt_tc(t + dur), "t0": round(t, 3),
                        "t1": round(t + dur, 3), "text": chunk, "loidan": lead(chunk)})
            t += dur
            buf = []
    if buf:
        chunk = " ".join(buf)
        dur = len(chunk.split()) / wpm * 60
        out.append({"stt": len(out) + 1, "start": fmt_tc(t), "end": fmt_tc(t + dur), "text": chunk, "loidan": lead(chunk)})
    return out


_ALIASES = {"stt": "stt", "start": "start", "batdau": "start", "timecode": "start", "end": "end", "ketthuc": "end",
            "loidan": "loidan", "mota": "mota", "keyword": "keyword", "keywordphu": "keyword_phu", "text": "text"}


def _norm(h):
    h = (h or "").strip().lower()
    for a, b in (("ả", "a"), ("à", "a"), ("á", "a"), ("ạ", "a"), ("ã", "a"), ("â", "a"), ("ă", "a"), ("ầ", "a"),
                 ("đ", "d"), ("ê", "e"), ("ế", "e"), ("ô", "o"), ("ơ", "o"), ("ư", "u"), ("ụ", "u"), ("í", "i")):
        h = h.replace(a, b)
    return re.sub(r"[^a-z]", "", h)


def rows_from_csv(text):
    out = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        r = {}
        for k, v in raw.items():
            key = _ALIASES.get(_norm(k))
            if key:
                r[key] = (v or "").strip()
        if not r.get("stt"):
            continue
        r["stt"] = int(r["stt"])
        r.setdefault("start", "00:00:00")
        r["start"] = r["start"][:8]
        r["end"] = r.get("end", "")[:8]
        r.setdefault("text", r.get("loidan", ""))
        r.setdefault("loidan", lead(r["text"]))
        out.append(r)
    return out


def load_any(filename, content, **kw):
    name = filename.lower()
    if name.endswith(".csv"):
        return rows_from_csv(content), "csv"
    if name.endswith(".srt") or "-->" in content[:3000]:
        return rows_from_srt(content, kw.get("body_min", BODY_MIN), kw.get("body_max", BODY_MAX)), "srt"
    return rows_from_plain(content, kw.get("wpm", 155)), "text"
