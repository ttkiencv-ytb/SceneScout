# Changelog

## 3.0.0-beta.1 — desktop app
- SceneScout runs as a real app with its own window and icon on macOS and Windows. No Python, no Terminal.
- Google, Envato and AI chat links open in the normal browser; an "Open in browser" button is available inside the app.
- Profile choice and settings are remembered between launches; downloads (project files) work from the app window.
- GitHub Actions builds `SceneScout-mac-apple-silicon.dmg` and `SceneScout-windows.zip` on demand or on every release.
- If the native window cannot start (for example WebView2 missing on an old Windows), SceneScout falls back to the browser with a small window to quit.

## 2.1.0-alpha.1 — timeline export
- **Video MP4 with every shot already in place**: drop one file on the timeline of CapCut or any editor at 0:00 and all shots line up with the voice-over. Frame boundaries come from absolute SRT times, so there is no drift on long videos.
- **FCPXML** for DaVinci Resolve / Final Cut and **XML** for Premiere Pro, with each shot as its own clip.
- Optional **voice-over** (MP3, WAV, M4A…): included in the MP4 and the XML timelines; a warning appears if its length does not match the SRT.
- Shots without media (AI / Envato / missing) become labelled placeholder cards (shot number, times, description, narration, keyword).
- Portrait and square images are placed on a blurred copy of themselves to fill 16:9. Optional gentle zoom (Ken Burns), alternating in and out.
- Stock videos are trimmed (or looped) to the shot length.
- Settings: frame rate (24/25/30/60) and resolution (1080p/4K). Row times are now stored to the millisecond.
- Launchers install new dependencies automatically on start (Pillow, ffmpeg via imageio-ffmpeg).

## 2.0.0-alpha.4
- **Chat AI mode (no API key)**: SceneScout splits the script, builds a ready-to-paste prompt (full narration as context + the rows to write + your keyword rules), and you paste it into Claude, ChatGPT or Gemini chat. Paste the reply back; SceneScout reads JSON, JSONL or CSV, even when the JSON is cut off, and re-asks only the rows that are missing. Available when creating a project, from the Quick-mode banner, and in "Analyze again".
- AI over API is much more tolerant of small/free models: broken or truncated JSON is salvaged row by row, failed rows are retried in smaller batches (3 rounds), the same provider gets a second try before falling back, batches shrink to 20 rows for lite/free models, free tiers are paced (one call every few seconds) and `Retry-After` is respected.
- Keyword rules are editable in Settings (advanced) and are shared by API and chat modes. "On-screen text" notes are written in the description language.

## 2.0.0-alpha.3
- "No credit / quota used up" errors (OpenAI insufficient_quota, HTTP 402) now skip that provider immediately and move to the next one, instead of waiting and retrying.
- API errors are explained in plain Vietnamese with what to do next (no credit, wrong key, model not found, rate limit, no connection). The OpenAI message notes that ChatGPT subscriptions do not include API usage.
- The "Quick mode" banner no longer appears on projects imported from a CSV that already has descriptions and keywords.
- Error dialogs have a button that opens AI settings directly.

## 2.0.0-alpha.2
- Quick mode finds the visible subject: "Patton's tanks were burning gasoline" now searches "Patton tanks gasoline France 1944" instead of just the name. Name phrases no longer run across sentence boundaries.
- AI prompt: start from the visible subject of each sentence; fix names misspelled by subtitles ("Patten" -> Patton) when context makes it clear.
- A key saved without a model gets a model picked automatically (OpenAI, Claude, Gemini, DeepSeek, Groq, OpenRouter).
- After AI analysis a report shows how many calls were made, which provider answered, and which rows fell back to Quick mode. If AI fails completely you now see why, and the project keeps Quick-mode keywords.
- Projects analyzed in Quick mode show a banner with a one-click "Analyze again with AI".

## 2.0.0-alpha.1
- New app: SceneScout (rewrite of the v1 image finder).
- Profiles for several people on one computer; per-profile settings and API keys.
- Projects saved automatically: list, reopen, rename, duplicate, delete, export/import as a file.
- Script analysis built in: Quick (offline) or AI with OpenAI, Claude, Gemini, DeepSeek, Groq, OpenRouter, Ollama or any OpenAI-compatible API, with automatic fallback between providers.
- Image sources: Wikimedia Commons, Library of Congress, Openverse (no key); Pexels, Pixabay, Unsplash (free keys, photos and videos); "Used" tab searching your own library; Google and Envato by drag-and-drop or paste.
- Shared library of everything you have exported, reusable across videos, with optional "used in" badges.
- Export: files named STT_hh-mm-ss, list of AI/Envato/missing rows, credits.csv, manifest.

## 1.x
- Single-file local tool (tim-anh-tool).
