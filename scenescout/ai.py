"""AI script analysis with any major provider, plus automatic fallback.

Two adapters cover almost everything:
  * "openai" — the OpenAI-compatible chat API, used by OpenAI, Gemini, DeepSeek,
    Groq, OpenRouter, Mistral, Ollama, LM Studio and most others.
  * "anthropic" — Claude's Messages API.

The pipeline is built to fit free tiers: one context call, then rows in batches
(~40 per call), so a 30-minute script needs roughly 8–10 calls in total.
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import analyze_quick

PROVIDERS = {
    "openai":     {"label": "OpenAI (ChatGPT)", "kind": "openai", "base": "https://api.openai.com/v1",
                   "key_url": "https://platform.openai.com/api-keys", "tier": "paid"},
    "anthropic":  {"label": "Claude (Anthropic)", "kind": "anthropic", "base": "https://api.anthropic.com/v1",
                   "key_url": "https://console.anthropic.com/settings/keys", "tier": "paid",
                   "suggest": ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"]},
    "gemini":     {"label": "Gemini (Google)", "kind": "openai",
                   "base": "https://generativelanguage.googleapis.com/v1beta/openai",
                   "key_url": "https://aistudio.google.com/apikey", "tier": "free-tier"},
    "deepseek":   {"label": "DeepSeek", "kind": "openai", "base": "https://api.deepseek.com",
                   "key_url": "https://platform.deepseek.com/api_keys", "tier": "low-cost",
                   "suggest": ["deepseek-chat"]},
    "groq":       {"label": "Groq (free tier, very fast)", "kind": "openai", "base": "https://api.groq.com/openai/v1",
                   "key_url": "https://console.groq.com/keys", "tier": "free-tier"},
    "openrouter": {"label": "OpenRouter (free models)", "kind": "openai", "base": "https://openrouter.ai/api/v1",
                   "key_url": "https://openrouter.ai/keys", "tier": "free-tier"},
    "ollama":     {"label": "Ollama (on this computer, free)", "kind": "openai", "base": "http://localhost:11434/v1",
                   "key_url": "https://ollama.com/download", "tier": "local", "nokey": True},
    "custom":     {"label": "Custom (OpenAI-compatible)", "kind": "openai", "base": "", "tier": "custom"},
}

RULES = """You prepare image-search keywords for a documentary video editor.
For each row of narration, return:
- "mota": what the picture on screen should show, max 15 words, written in {lang}. No invented details.
- "keyword": 2–6 English words for an image archive search (Wikimedia, Library of Congress, stock sites).
- "keyword_phu": a broader English fallback keyword (drop the narrowest detail, keep side/year/type).
Rules:
0. Start from the VISIBLE SUBJECT of the sentence: what a camera would show. "Patton's tanks were burning gasoline"
   -> "Third Army Sherman tanks France 1944", not just the general's name. Abstract sentences use rule 3.
1. Concrete and visible: person names, units, equipment, places, years. e.g. "George Patton 1945 portrait".
1b. Subtitles may misspell names (e.g. "Patten" for Patton). If CONTEXT makes the intended well-known name clear,
   use the correct spelling in "keyword" and "keyword_phu"; never invent a name the narration does not support.
2. Replace pronouns with the real person/thing using the CONTEXT ("he refused" -> that person).
3. Abstract/emotional lines -> a concrete image: portrait of the person being discussed, the place, a document, a map.
4. Correct side, year and theater. Never mix them.
5. Archive style: proper nouns + year; add "photograph", "portrait", "map" or "document" when useful. No mood words.
6. Do not repeat the exact same keyword more than 2 rows in a row; vary the angle (portrait, place, equipment, map).
7. Rows inside the first 15 seconds must target the title / thumbnail subject.
8. Numbers or lists -> mota starts with "{onscreen}" and keyword finds a related background image.
9. Graphic violence or camps -> keyword aims at a less graphic image (gate, survivors, liberators).
Return ONLY JSON: {{"rows": [{{"stt": 1, "mota": "...", "keyword": "...", "keyword_phu": "..."}}]}}"""

CONTEXT_PROMPT = """Read this documentary narration and return ONLY JSON with:
{"summary": "...", "people": [{"name": "correct spelling", "spelled_in_script": "...", "role": "...", "side": "...", "aliases": ["he", "the general"]}],
 "places": ["..."], "years": ["..."], "equipment": ["..."], "title_subject": "..."}
TITLE: %s
THUMBNAIL: %s
NARRATION:
%s"""


class ProviderError(Exception):
    def __init__(self, msg, fatal=False, retry_after=None):
        super().__init__(msg)
        self.fatal = fatal  # bad key / bad model / no credit: skip this provider for the rest of the job
        self.retry_after = retry_after


_last_call = {}
MIN_GAP = {"free-tier": 4.0, "local": 0.0}  # seconds between calls, keeps free tiers under per-minute limits


def _pace(provider):
    tier = PROVIDERS.get(provider, {}).get("tier", "")
    gap = MIN_GAP.get(tier, 0.5)
    wait = _last_call.get(provider, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[provider] = time.time()


def _post(url, payload, headers, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        # No credit / quota used up is permanent for this job: skip the provider immediately
        no_money = e.code == 402 or any(x in body.lower() for x in ("insufficient_quota", "credit", "balance", "billing"))
        try:
            ra = float(e.headers.get("Retry-After") or 0) or None
        except (TypeError, ValueError):
            ra = None
        raise ProviderError(f"HTTP {e.code}: {body}", fatal=e.code in (401, 403, 404) or no_money, retry_after=ra) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ProviderError(f"network: {e}") from None


def humanize(err, provider=""):
    """Turn raw API errors into a short Vietnamese explanation with what to do next."""
    t = str(err).lower()
    name = PROVIDERS.get(provider, {}).get("label", provider) if provider else "Nhà cung cấp AI"
    if "insufficient_quota" in t or "credit" in t or "balance" in t or "billing" in t or "http 402" in t:
        extra = (" Lưu ý: gói ChatGPT Plus/Pro không bao gồm tiền dùng API; API tính tiền riêng tại "
                 "platform.openai.com → Billing.") if provider == "openai" else ""
        return f"{name}: tài khoản API đã hết tiền (credit).{extra} Nạp thêm, hoặc thêm một nhà cung cấp miễn phí (Gemini, Groq) làm dự phòng."
    if "http 401" in t or "invalid api key" in t or "incorrect api key" in t:
        return f"{name}: khóa API không đúng hoặc đã bị thu hồi. Dán lại khóa."
    if "http 403" in t:
        return f"{name}: khóa không có quyền dùng model này, hoặc tài khoản chưa được kích hoạt."
    if "http 404" in t or "model_not_found" in t or "does not exist" in t:
        return f"{name}: không tìm thấy model. Bấm ⟳ để chọn lại model."
    if "http 429" in t:
        return f"{name}: đang bị giới hạn số lượt (rate limit). Đợi vài phút hoặc thêm nhà cung cấp dự phòng."
    if "network" in t:
        return f"{name}: không kết nối được. Kiểm tra mạng (với Ollama: ứng dụng Ollama phải đang mở)."
    if "no model" in t:
        return f"{name}: chưa chọn model."
    return f"{name}: {str(err)[:200]}"


def _get(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}", fatal=True) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ProviderError(f"network: {e}") from None


def _cfg(entry):
    p = PROVIDERS.get(entry.get("provider"), PROVIDERS["custom"])
    base = (entry.get("base") or p["base"]).rstrip("/")
    return p, base


def chat(entry, system, user, json_mode=True):
    """One chat call. Returns the model's text."""
    p, base = _cfg(entry)
    key, model = entry.get("key", ""), entry.get("model", "")
    if not model:
        raise ProviderError("no model selected", fatal=True)
    _pace(entry.get("provider", ""))
    if p["kind"] == "anthropic":
        data = _post(f"{base}/messages",
                     {"model": model, "max_tokens": 8000, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                     {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    headers = {"Authorization": f"Bearer {key or 'none'}"}
    if entry.get("provider") == "openrouter":
        headers.update({"HTTP-Referer": "https://github.com/scenescout", "X-Title": "SceneScout"})
    payload = {"model": model, "temperature": 0.2,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        data = _post(f"{base}/chat/completions", payload, headers)
    except ProviderError as e:
        if json_mode and "HTTP 400" in str(e):  # some models reject response_format
            payload.pop("response_format")
            data = _post(f"{base}/chat/completions", payload, headers)
        else:
            raise
    return data["choices"][0]["message"]["content"] or ""


def list_models(entry):
    p, base = _cfg(entry)
    if p["kind"] == "anthropic":
        data = _get(f"{base}/models?limit=100", {"x-api-key": entry.get("key", ""), "anthropic-version": "2023-06-01"})
    else:
        data = _get(f"{base}/models", {"Authorization": f"Bearer {entry.get('key') or 'none'}"})
    ids = sorted({m.get("id", "") for m in data.get("data", data.get("models", [])) if m.get("id")})
    if entry.get("provider") == "openrouter" and entry.get("free_only"):
        ids = [i for i in ids if i.endswith(":free")]
    return ids


_SKIP = ("embed", "tts", "whisper", "image", "audio", "moderation", "guard", "realtime", "transcribe", "vision",
         "search", "dall", "sora", "veo", "imagen", "rerank", "ocr")
_PREFS = {
    "openai": ["mini"],
    "anthropic": ["haiku", "sonnet"],
    "gemini": ["flash"],
    "deepseek": ["deepseek-chat"],
    "groq": ["gpt-oss-120b", "70b", "llama", "qwen"],
    "openrouter": ["deepseek", "llama-3.3", "qwen", "gemma", "mistral"],
}


def pick_default(provider, models):
    """Choose a sensible model when the user pasted a key but left Model empty.
    Newer versions sort last alphabetically, so search from the end."""
    ok = [m for m in models if not any(x in m.lower() for x in _SKIP)]
    if provider == "openrouter":
        ok = [m for m in ok if m.endswith(":free")] or ok
    ok = sorted(ok, reverse=True)
    for pref in _PREFS.get(provider, []):
        for m in ok:
            if pref in m.lower() and "lite" not in m.lower() and "nano" not in m.lower():
                return m
    return ok[0] if ok else ""


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in reply")
    return json.loads(text[i:j + 1])


def extract_rows(text):
    """Pull {stt, mota, keyword, keyword_phu} items out of a reply even when the JSON is
    broken or cut off (common with small/free models). Also accepts JSONL and CSV pastes."""
    import csv
    import io
    out = {}

    def take(item):
        try:
            stt = int(str(item.get("stt", item.get("STT", ""))).strip())
        except (TypeError, ValueError):
            return
        kw = item.get("keyword") or item.get("Keyword") or ""
        out[stt] = {"stt": stt, "mota": item.get("mota") or item.get("MoTa") or "",
                    "keyword": kw, "keyword_phu": item.get("keyword_phu") or item.get("KeywordPhu") or ""}

    clean = re.sub(r"```(?:json|csv)?", "", text or "").strip()
    try:
        data = parse_json(clean)
        for item in (data.get("rows") if isinstance(data, dict) else data) or []:
            if isinstance(item, dict):
                take(item)
        if out:
            return out
    except Exception:
        pass
    for m in re.finditer(r"\{[^{}]*?[\"']stt[\"']\s*:\s*\d+[^{}]*?\}", clean):
        frag = re.sub(r",\s*}", "}", m.group(0))
        try:
            take(json.loads(frag))
        except Exception:
            continue
    if out:
        return out
    if "," in clean and re.search(r"(?im)^\s*\"?stt\"?\s*,", clean):
        for row in csv.DictReader(io.StringIO(clean[re.search(r"(?im)^\s*\"?stt\"?\s*,", clean).start():])):
            take({k.strip(): (v or "").strip() for k, v in row.items() if k})
    return out


def call_chain(chain, system, user, log, dead, parse=None):
    """Try each provider in order. Rate limits and network errors fall through to the next one."""
    last = None
    for idx, entry in enumerate(chain):
        if idx in dead:
            continue
        for attempt in range(2):
            try:
                out = chat(entry, system, user)
                parsed = (parse or parse_json)(out)
                if not parsed:
                    raise ValueError("reply had no usable rows")
                return parsed, entry
            except ProviderError as e:
                last = ProviderError(humanize(e, entry.get("provider", "")), e.fatal)
                log(f"{entry.get('provider')}/{entry.get('model')}: {e}")
                if e.fatal:
                    dead.add(idx)
                    break
                if "HTTP 429" in str(e):
                    if attempt == 0:
                        time.sleep(min(e.retry_after or 15, 60))
                        continue
                    dead.add(idx)  # still rate-limited: stop using it for this job
                break
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                last = e
                log(f"{entry.get('provider')}: unreadable reply ({e})")
                if attempt == 0:
                    continue  # one more try on the same provider before moving on
                break
    raise ProviderError(str(last) if last else "Không nhà cung cấp AI nào trả lời.")


def _valid(item):
    kw = (item.get("keyword") or "").strip()
    return bool(kw) and kw.isascii()


def rules_text(lang="Vietnamese", custom=""):
    base = custom.strip() if custom and custom.strip() else RULES
    onscreen = "Chữ trên màn hình:" if lang.lower().startswith("viet") else "On-screen text:"
    return base.replace("{lang}", lang).replace("{onscreen}", onscreen).replace("{{", "{").replace("}}", "}")


def auto_batch(chain, batch):
    e = chain[0] if chain else {}
    small = any(x in (e.get("model") or "").lower() for x in ("lite", "mini", "nano", "small", ":free", "gemma", "8b", "7b"))
    free = PROVIDERS.get(e.get("provider"), {}).get("tier") in ("free-tier", "local")
    return min(batch, 20) if (small or free) else batch


def analyze(rows, title="", thumbnail="", chain=None, lang="Vietnamese", batch=40, progress=None, rules=""):
    """Returns (rows, context, report). Never raises for row-level failures:
    rows the AI could not handle fall back to the offline analyzer."""
    progress = progress or (lambda *a: None)
    report = {"calls": 0, "providers": {}, "fallback_rows": [], "log": []}
    log = report["log"].append
    dead = set()
    chain = [c for c in (chain or []) if c.get("model")]
    if not chain:
        rows, ctx = analyze_quick.analyze(rows, title)
        report["fallback_rows"] = [r["stt"] for r in rows]
        return rows, ctx, report

    narration = "\n".join(f"[{r['stt']}] {r['text']}" for r in rows)
    words = narration.split()
    if len(words) > 14000:
        narration = " ".join(words[:14000])
    progress("context", 0, 1)
    try:
        context, used = call_chain(chain, "You are a careful research assistant. Output JSON only.",
                                   CONTEXT_PROMPT % (title, thumbnail, narration), log, dead)
        report["calls"] += 1
        report["providers"][used["provider"]] = report["providers"].get(used["provider"], 0) + 1
    except ProviderError as e:
        log(f"context failed: {e}")
        context = {}

    system = rules_text(lang, rules)
    batch = auto_batch(chain, batch)
    ctx_text = json.dumps(context, ensure_ascii=False)
    by_stt = {r["stt"]: r for r in rows}
    pending = [r["stt"] for r in rows]
    batches = [pending[i:i + batch] for i in range(0, len(pending), batch)]
    done = 0
    for round_no in range(3):  # later rounds retry missing rows in smaller batches
        missing = []
        for b in batches:
            payload = (f"TITLE: {title}\nTHUMBNAIL: {thumbnail}\nCONTEXT: {ctx_text}\nROWS:\n" +
                       "\n".join(f"[{s}] ({by_stt[s]['start']}) {by_stt[s]['text']}" for s in b))
            try:
                got, used = call_chain(chain, system, payload, log, dead, parse=extract_rows)
                report["calls"] += 1
                report["providers"][used["provider"]] = report["providers"].get(used["provider"], 0) + 1
                for s in b:
                    item = got.get(s)
                    if item and _valid(item):
                        by_stt[s].update(mota=(item.get("mota") or by_stt[s]["loidan"]).strip(),
                                         keyword=item["keyword"].strip(),
                                         keyword_phu=(item.get("keyword_phu") or item["keyword"]).strip())
                        done += 1
                    else:
                        missing.append(s)
            except ProviderError as e:
                log(f"batch {b[0]}-{b[-1]} failed: {e}")
                missing.extend(b)
            progress("rows", done, len(rows))
        if not missing:
            break
        size = 10 if round_no == 0 else 4
        batches = [missing[i:i + size] for i in range(0, len(missing), size)]
        if round_no == 2 or len(dead) == len(chain):
            break
    leftovers = [by_stt[s] for s in pending if not by_stt[s].get("keyword")]
    if len(leftovers) == len(rows):
        # Nothing worked: tell the user why instead of silently switching to Quick mode
        msgs = []
        for idx, entry in enumerate(chain):
            hits = [l for l in report["log"] if l.startswith(f"{entry.get('provider')}/")]
            if hits:
                msgs.append(humanize(hits[-1], entry.get("provider", "")))
        raise ProviderError(" ".join(dict.fromkeys(msgs)) or "Không nhà cung cấp AI nào trả lời.")
    if leftovers:
        analyze_quick.analyze(leftovers, title)
        report["fallback_rows"] = [r["stt"] for r in leftovers]
    context["mode"] = "ai"
    return rows, context, report


CHAT_HEADER = """You will write image-search data for part of a documentary narration.
Read the FULL NARRATION first for context (people, sides, places, years, what "he" or "the column" refers to).
Then write one item for EACH row listed under ROWS TO WRITE, and nothing else.

"""


def chat_prompt(all_rows, part_stts, title="", thumbnail="", lang="Vietnamese", rules=""):
    """A self-contained prompt to paste into Claude / ChatGPT / Gemini chat (no API needed)."""
    by = {r["stt"]: r for r in all_rows}
    narration = "\n".join(f"[{r['stt']}] {r['text']}" for r in all_rows)
    rows_txt = "\n".join(f"[{s}] ({by[s]['start']}) {by[s]['text']}" for s in part_stts)
    return (CHAT_HEADER + rules_text(lang, rules) +
            f"\n\nAnswer with ONE JSON code block only, containing exactly {len(part_stts)} items "
            f"(stt {part_stts[0]} to {part_stts[-1]}). No explanation before or after.\n\n"
            f"TITLE: {title}\nTHUMBNAIL: {thumbnail}\n\nFULL NARRATION:\n{narration}\n\nROWS TO WRITE:\n{rows_txt}\n")
