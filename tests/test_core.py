"""Run with:  python -m pytest -q   (or plain:  python tests/test_core.py)"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SCENESCOUT_DATA", tempfile.mkdtemp())

from scenescout import ai, analyze_quick, script_io, sources  # noqa: E402

SRT = """1
00:00:00,000 --> 00:00:03,000
George Patton stood on the beach.

2
00:00:03,000 --> 00:00:20,000
He looked at the ships. The Army had no artillery that day. These ships were the artillery. Nobody expected that.
"""


def test_srt_rows_and_long_cue_split():
    rows = script_io.rows_from_srt(SRT)
    assert rows[0]["start"] == "00:00:00"
    assert len(rows) >= 3  # the 17-second cue is split at sentence ends
    assert all(r["loidan"] for r in rows)


def test_quick_resolves_pronoun_to_last_person():
    rows, ctx = analyze_quick.analyze(script_io.rows_from_srt(SRT))
    assert "George Patton" in rows[1]["keyword"]
    assert ctx["characters"][0] == "George Patton"


def test_query_widening():
    qs = sources.expand_queries("June Fritz Ensslin Fort Leonard Wood Missouri 1943", "Fritz Ensslin 1943")
    assert qs[0].endswith("1943") and len(qs) <= 5 and any(len(q.split()) <= 3 for q in qs)


def test_ai_fallback_chain_and_row_recovery(monkeypatch=None):
    rows = script_io.rows_from_srt(SRT)

    def fake_chat(entry, system, user, json_mode=True):
        if entry["provider"] == "groq":
            raise ai.ProviderError("HTTP 429: slow down")
        if "NARRATION" in user:
            return json.dumps({"people": [{"name": "George Patton"}]})
        import re
        stts = [int(x) for x in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
        return json.dumps({"rows": [{"stt": s, "mota": "m", "keyword": "Patton 1944", "keyword_phu": "US Army"} for s in stts[1:]]})

    ai.chat, ai.time.sleep = fake_chat, (lambda s: None)
    rows, ctx, rep = ai.analyze(rows, chain=[{"provider": "groq", "model": "x"}, {"provider": "deepseek", "model": "y"}])
    assert rep["providers"].get("deepseek")
    assert all(r["keyword"] for r in rows)  # first row always dropped by the fake -> recovered by offline mode
    assert rep["fallback_rows"] == [1]


def test_timeline_plan_has_no_drift(tmp_path=None):
    import tempfile
    from pathlib import Path
    from scenescout import timeline
    d = Path(tmp_path or tempfile.mkdtemp())
    (d / "0002_00-00-04.jpg").write_bytes(b"x")
    rows = [{"stt": i + 1, "t0": i * 4.37, "t1": i * 4.37 + 4.37, "start": "", "end": "", "flag": ""} for i in range(300)]
    plan = timeline.build_plan(rows, d, 30)
    assert plan[0]["f0"] == 0 and plan[1]["kind"] == "image" and plan[0]["kind"] == "placeholder"
    assert all(a["f1"] == b["f0"] for a, b in zip(plan, plan[1:]))      # contiguous
    assert plan[-1]["f0"] == round(299 * 4.37 * 30)                      # absolute, no accumulated rounding


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
