"""Timeline export.

Turns an exported project folder into:
  * scenescout-timeline.mp4  — every shot placed at its SRT time (drop on any editor at 0:00, including CapCut)
  * scenescout-timeline.fcpxml — DaVinci Resolve / Final Cut Pro
  * scenescout-timeline-premiere.xml — Premiere Pro (FCP7 XML)
Shots without media (AI / Envato / missing) become labelled placeholder cards so gaps are visible.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import resource_path

IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
VIDEO_EXT = {"mp4", "webm", "mov"}
_NOWIN = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}  # no console flashes on Windows


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found. Reinstall SceneScout (pip install -r requirements.txt).")
        return exe


def run(args):
    p = subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *args], capture_output=True, text=True, **_NOWIN)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "ffmpeg failed")[-500:])


def media_duration(path):
    p = subprocess.run([ffmpeg(), "-i", str(path)], capture_output=True, text=True, **_NOWIN)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def _font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (resource_path(f"scenescout/assets/fonts/{name}"),):
        if Path(p).exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _secs(row):
    if row.get("t0") is not None:
        return float(row["t0"])
    h, m, s = (row.get("start") or "00:00:00")[:8].split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _secs_end(row):
    if row.get("t1") is not None:
        return float(row["t1"])
    if row.get("end"):
        h, m, s = row["end"][:8].split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    return _secs(row) + 4


# ---------------- frames ----------------
def frame_16x9(src, W, H):
    """Fit any image into W×H; empty space is filled with a blurred, darkened copy of itself."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    bg = ImageOps.fit(im, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(max(W, H) // 40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    fg = ImageOps.contain(im, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def placeholder(row, W, H):
    flag = row.get("flag") or ""
    label = {"AI": "CẦN ẢNH AI", "ENVATO": "DÙNG ENVATO"}.get(flag, "CHƯA CÓ ẢNH")
    color = {"AI": (164, 151, 255), "ENVATO": (82, 183, 168)}.get(flag, (227, 168, 59))
    im = Image.new("RGB", (W, H), (32, 35, 39))
    d = ImageDraw.Draw(im)
    s = W / 1920
    d.rectangle([int(60 * s), int(60 * s), W - int(60 * s), H - int(60 * s)], outline=color, width=max(2, int(6 * s)))
    d.text((int(120 * s), int(130 * s)), f"#{row['stt']}  ·  {label}", font=_font(int(84 * s), True), fill=color)
    d.text((int(120 * s), int(250 * s)), f"{(row.get('start') or '')[:8]}  →  {(row.get('end') or '')[:8]}",
           font=_font(int(44 * s)), fill=(163, 157, 146))
    y = int(360 * s)
    for label_txt, txt, size in (("Mô tả cảnh", row.get("mota") or "", 52), ("Lời dẫn", row.get("text") or row.get("loidan") or "", 40),
                                 ("Từ khóa", row.get("keyword") or "", 40)):
        if not txt:
            continue
        d.text((int(120 * s), y), label_txt.upper(), font=_font(int(28 * s), True), fill=(120, 116, 108))
        y += int(44 * s)
        for line in textwrap.wrap(txt, width=int(62 * 52 / size))[:3]:
            d.text((int(120 * s), y), line, font=_font(int(size * s)), fill=(236, 230, 218))
            y += int(size * 1.35 * s)
        y += int(24 * s)
    return im


# ---------------- plan ----------------
def build_plan(rows, outdir, fps, audio_dur=None):
    """One segment per row; frame boundaries come from absolute times so there is no drift."""
    outdir = Path(outdir)
    files = {}
    for f in outdir.iterdir():
        m = re.match(r"^(\d{4})_", f.name)
        if m and f.suffix.lower().lstrip(".") in IMAGE_EXT | VIDEO_EXT:
            files[int(m.group(1))] = f
    rows = sorted(rows, key=_secs)
    starts = [0.0] + [_secs(r) for r in rows[1:]]
    end = max(_secs_end(rows[-1]), audio_dur or 0) if rows else (audio_dur or 0)
    bounds = [round(t * fps) for t in starts] + [round(end * fps)]
    plan = []
    for i, r in enumerate(rows):
        f0, f1 = bounds[i], max(bounds[i + 1], bounds[i] + 1)
        path = files.get(r["stt"])
        kind = "placeholder" if (r.get("flag") or not path) else ("video" if path.suffix.lower().lstrip(".") in VIDEO_EXT else "image")
        plan.append({"row": r, "stt": r["stt"], "kind": kind, "path": path, "f0": f0, "f1": f1})
    return plan


# ---------------- MP4 ----------------
def _encode_args(fps, preset):
    return ["-c:v", "libx264", "-preset", preset, "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-an", "-threads", "2"]


def _render_segment(seg, i, tmp, W, H, fps, kenburns, preset):
    n = seg["f1"] - seg["f0"]
    out = Path(tmp) / f"seg_{i:05d}.mp4"
    if seg["kind"] == "video":
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,eq=brightness=-0.12[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps},setsar=1")
        try:
            run(["-stream_loop", "-1", "-i", str(seg["path"]), "-filter_complex", vf, "-frames:v", str(n),
                 *_encode_args(fps, preset), str(out)])
            return out
        except RuntimeError:
            seg["kind"] = "placeholder"  # unreadable video: show the card instead of failing the export
    zoom = kenburns and seg["kind"] == "image" and n > fps
    scale = 1.12 if zoom else 1.0
    if seg["kind"] == "image":
        try:
            frame = frame_16x9(seg["path"], int(W * scale), int(H * scale))
        except Exception:
            frame = placeholder(seg["row"], int(W * scale), int(H * scale))
            zoom = False
    else:
        frame = placeholder(seg["row"], W, H)
    still = Path(tmp) / f"seg_{i:05d}.png"
    frame.save(still)
    if zoom:
        # alternate zoom in / zoom out so consecutive shots do not feel identical
        z = f"1+0.08*on/{n}" if i % 2 == 0 else f"1.08-0.08*on/{n}"
        vf = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={fps},setsar=1")
        run(["-i", str(still), "-vf", vf, "-frames:v", str(n), *_encode_args(fps, preset), str(out)])
    else:
        run(["-loop", "1", "-framerate", str(fps), "-i", str(still), "-vf", f"scale={W}:{H},setsar=1",
             "-frames:v", str(n), "-tune", "stillimage", *_encode_args(fps, preset), str(out)])
    still.unlink(missing_ok=True)
    return out


def render_mp4(plan, out_path, W=1920, H=1080, fps=30, kenburns=True, audio=None, preset="veryfast", progress=None):
    progress = progress or (lambda *a, **k: None)
    tmp = tempfile.mkdtemp(prefix="scenescout-")
    try:
        workers = max(1, (os.cpu_count() or 2) // 2)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_render_segment, seg, i, tmp, W, H, fps, kenburns, preset) for i, seg in enumerate(plan)]
            parts = []
            for f in futures:
                parts.append(f.result())
                done += 1
                progress("render", done, len(plan))
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        progress("finish", 0, 1)
        silent = Path(tmp) / "timeline.mp4"
        run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])
        if audio:
            run(["-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                 "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path)])
        else:
            run(["-i", str(silent), "-c", "copy", "-movflags", "+faststart", str(out_path)])
        progress("finish", 1, 1)
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_placeholders(plan, outdir, W, H):
    """XML timelines need real files for gaps too."""
    pdir = Path(outdir) / "placeholders"
    for seg in plan:
        if seg["kind"] == "placeholder":
            pdir.mkdir(exist_ok=True)
            p = pdir / f"{seg['stt']:04d}_placeholder.png"
            placeholder(seg["row"], W, H).save(p)
            seg["path"] = p
            seg["kind"] = "image"


# ---------------- XML timelines ----------------
def _url(p):
    p = Path(p).resolve().as_posix()
    if not p.startswith("/"):
        p = "/" + p  # Windows drive letter
    return "file://" + urllib.parse.quote(p)


def write_fcpxml(plan, out_path, name, W, H, fps, audio=None, audio_dur=None):
    total = plan[-1]["f1"] if plan else 0
    t = lambda frames: f"{frames}/{fps}s"  # noqa: E731
    res = [f'<format id="r0" name="FFVideoFormat{H}p{fps}" frameDuration="1/{fps}s" width="{W}" height="{H}"/>']
    spine = []
    for i, seg in enumerate(plan):
        aid, n = f"a{i + 1}", seg["f1"] - seg["f0"]
        nm = escape(Path(seg["path"]).name)
        if seg["kind"] == "video":
            res.append(f'<asset id="{aid}" name="{nm}" start="0s" duration="{t(n)}" hasVideo="1" format="r0">'
                       f'<media-rep kind="original-media" src="{escape(_url(seg["path"]))}"/></asset>')
            el = f'<asset-clip ref="{aid}" offset="{t(seg["f0"])}" name="{nm}" start="0s" duration="{t(n)}" tcFormat="NDF"'
        else:
            res.append(f'<asset id="{aid}" name="{nm}" start="0s" duration="0s" hasVideo="1" format="r0">'
                       f'<media-rep kind="original-media" src="{escape(_url(seg["path"]))}"/></asset>')
            el = f'<video ref="{aid}" offset="{t(seg["f0"])}" name="{nm}" start="0s" duration="{t(n)}"'
        close = "</asset-clip>" if seg["kind"] == "video" else "</video>"
        inner = ""
        if i == 0 and audio:
            ad = round((audio_dur or total / fps) * fps)
            res.append(f'<asset id="aud" name="{escape(Path(audio).name)}" start="0s" duration="{t(ad)}" hasAudio="1" '
                       f'audioSources="1" audioChannels="2" audioRate="48000"><media-rep kind="original-media" src="{escape(_url(audio))}"/></asset>')
            inner = f'<asset-clip ref="aud" lane="-1" offset="0s" name="voice-over" start="0s" duration="{t(ad)}" audioRole="dialogue"/>'
        spine.append(el + ">" + inner + close)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n<resources>\n' +
           "\n".join(res) + f'\n</resources>\n<library><event name="SceneScout"><project name="{escape(name)}">'
           f'<sequence format="r0" duration="{t(total)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k"><spine>\n' +
           "\n".join(spine) + "\n</spine></sequence></project></event></library>\n</fcpxml>\n")
    Path(out_path).write_text(xml, encoding="utf-8")
    return out_path


def write_premiere_xml(plan, out_path, name, W, H, fps, audio=None, audio_dur=None):
    total = plan[-1]["f1"] if plan else 0
    rate = f"<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>"
    clips = []
    for i, seg in enumerate(plan):
        n = seg["f1"] - seg["f0"]
        nm = escape(Path(seg["path"]).name)
        clips.append(
            f'<clipitem id="clip-{i + 1}"><name>{nm}</name><enabled>TRUE</enabled><duration>{n}</duration>{rate}'
            f'<start>{seg["f0"]}</start><end>{seg["f1"]}</end><in>0</in><out>{n}</out>'
            f'<file id="file-{i + 1}"><name>{nm}</name><pathurl>{escape(_url(seg["path"]).replace("file://", "file://localhost", 1))}</pathurl>'
            f'{rate}<duration>{n}</duration><media><video><samplecharacteristics><width>{W}</width><height>{H}</height>'
            f'</samplecharacteristics></video></media></file></clipitem>')
    audio_xml = ""
    if audio:
        ad = round((audio_dur or total / fps) * fps)
        an = escape(Path(audio).name)
        audio_xml = (f'<audio><track><clipitem id="clip-audio"><name>{an}</name><enabled>TRUE</enabled><duration>{ad}</duration>{rate}'
                     f'<start>0</start><end>{ad}</end><in>0</in><out>{ad}</out><file id="file-audio"><name>{an}</name>'
                     f'<pathurl>{escape(_url(audio).replace("file://", "file://localhost", 1))}</pathurl>{rate}<duration>{ad}</duration>'
                     f'<media><audio><channelcount>2</channelcount></audio></media></file></clipitem></track></audio>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="scenescout">'
           f'<name>{escape(name)}</name><duration>{total}</duration>{rate}<media><video><format><samplecharacteristics>'
           f'{rate}<width>{W}</width><height>{H}</height><pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>'
           '<track>' + "".join(clips) + '</track></video>' + audio_xml + '</media></sequence></xmeml>\n')
    Path(out_path).write_text(xml, encoding="utf-8")
    return out_path


def export_timeline(rows, outdir, name, opts, progress=None):
    """opts: mp4, fcpxml, premiere (bool), fps, width, height, kenburns, audio (path or None)"""
    fps, W, H = int(opts.get("fps", 30)), int(opts.get("width", 1920)), int(opts.get("height", 1080))
    audio = opts.get("audio")
    audio_dur = media_duration(audio) if audio else None
    outdir = Path(outdir)
    if audio:  # keep the voice-over next to the timelines so XML links stay valid
        target = outdir / ("voice-over" + Path(audio).suffix.lower())
        shutil.copyfile(audio, target)
        audio = target
    plan = build_plan(rows, outdir, fps, audio_dur)
    made = {}
    if opts.get("mp4"):
        made["mp4"] = str(render_mp4(plan, outdir / "scenescout-timeline.mp4", W, H, fps, opts.get("kenburns", True),
                                     audio, opts.get("preset", "veryfast"), progress))
    if opts.get("fcpxml") or opts.get("premiere"):
        write_placeholders(plan, outdir, W, H)
        if opts.get("fcpxml"):
            made["fcpxml"] = str(write_fcpxml(plan, outdir / "scenescout-timeline.fcpxml", name, W, H, fps, audio, audio_dur))
        if opts.get("premiere"):
            made["premiere"] = str(write_premiere_xml(plan, outdir / "scenescout-timeline-premiere.xml", name, W, H, fps, audio, audio_dur))
    srt_end = plan[-1]["f1"] / fps if plan else 0
    made["placeholders"] = sum(1 for s in plan if "placeholder" in str(s["path"]) or s["kind"] == "placeholder")
    made["audio_dur"] = audio_dur
    made["script_dur"] = srt_end
    return made
