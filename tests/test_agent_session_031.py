"""0.3.1: proxy meta persistence + agent_preflight/finish_session."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 0.6) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_proxy_meta_survives_reopen(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _vid(v)
    root = tmp_path / "p.opm"
    ed = Editor.create(root, fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    r = ed.export_preview(height=120, fps=8)
    assert r.get("fresh") is True
    meta = Path(r["meta_path"])
    assert meta.exists()
    fp = r["fingerprint"]
    ed.save()  # fingerprint is over in-memory project; disk must match reopen

    ed2 = Editor.open(root)
    st = ed2.preview_proxy_status()
    assert st["exists"] is True
    assert st["fresh"] is True
    assert st["fingerprint"] == fp

    # edit → stale
    ed2.set_clip_meta(ed2.project.tracks[0].clips[0].id, name="x")
    st2 = ed2.preview_proxy_status()
    assert st2["fresh"] is False
    # rebuild
    r2 = ed2.ensure_preview_proxy(height=120, fps=8)
    assert r2.get("fresh") is True or r2.get("cache_hit") is False
    assert ed2.preview_proxy_status()["fresh"] is True


def test_agent_preflight_and_finish(tmp_path: Path):
    v = tmp_path / "a.mp4"
    _vid(v, "navy", 0.7)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)
    pre = ed.agent_preflight()
    assert pre["ready"] is True
    assert "proxy" in pre
    assert "next_steps" in pre
    assert isinstance(pre["next_steps"], list)

    out = tmp_path / "out.mp4"
    fin = ed.agent_finish_session(
        out,
        ensure_proxy=True,
        proxy_height=120,
        proxy_fps=8,
        run_review=False,
        normalize_preset=None,
    )
    assert fin["ok"] is True
    assert out.exists() and out.stat().st_size > 500
    assert "agent_preflight" in fin["steps"]
    assert "finish_delivery" in fin["steps"]
    assert ed.preview_proxy_status()["exists"] is True
