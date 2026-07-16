"""detach_audio_selection + match_selection_duration + selection_jl_cut (0.6.14)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_audio(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_detach_match_jl():
    root = Path(tempfile.mkdtemp(prefix="opmiere_dmj_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid_audio(a, 0.6)
        _vid_audio(b, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, int(c1.end))
        d1 = c1.timeline_duration_frames
        d2 = c2.timeline_duration_frames
        assert d1 != d2

        m = ed.match_selection_duration([c1.id, c2.id], target_clip_id=c1.id)
        assert m["count"] == 1
        assert ed._find_clip(c2.id).timeline_duration_frames == d1 or abs(
            ed._find_clip(c2.id).timeline_duration_frames - d1
        ) <= 1

        det = ed.detach_audio_selection([c1.id], audio_start_offset_frames=0)
        assert det["count"] == 1
        assert det["detached"][0]["audio_clip_id"]
        assert sum(1 for t in ed.project.tracks if t.kind == "audio") >= 1

        # fresh clip for J-cut
        c3 = ed.place_from_file(a, "video", tr.id, int(ed.duration_frames()))
        jl = ed.selection_jl_cut([c3.id], style="j", frames=10)
        assert jl["count"] == 1
        assert jl["style"] == "j"
        assert jl["detached"][0]["offset_frames"] == -10
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_14():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/detach_audio_selection" in app
    assert "/api/edit/match_selection_duration" in app
    assert "/api/edit/selection_jl_cut" in app
    assert "def detach_audio_selection" in mcp
    assert "def match_selection_duration" in mcp
    assert "def selection_jl_cut" in mcp
    assert 'id="btn-detach-sel"' in html
    assert 'id="btn-match-sel"' in html
    assert 'id="btn-jcut-sel"' in html
    assert 'id="btn-lcut-sel"' in html
    assert "detachAudioSelectionUi" in ts
    assert "matchSelectionDurationUi" in ts
    assert "selectionJlCutUi" in ts
