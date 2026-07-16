"""expand_selection_links + close_gaps_on_selection_tracks + freeze_selection_mids (0.6.15)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_audio(path: Path, d: float = 0.4) -> None:
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


def test_expand_gap_freeze():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lgf_"))
    try:
        v = root / "v.mp4"
        _vid_audio(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        det = ed.detach_audio(c.id, link=True)
        audio_id = det["audio_clip_id"]
        exp = ed.expand_selection_links([c.id])
        assert exp["count"] >= 2
        assert audio_id in exp["clip_ids"]
        assert exp["added_count"] >= 1

        # gap then pack selection track
        with ed._mutate():
            m = ed.project.media_by_id(c.media)
            c2 = ed.project.add_clip(
                ed.project.track_by_id(tr.id), m, int(c.end) + 20, 0, 8,
            )
        assert c2.start > c.end
        g = ed.close_gaps_on_selection_tracks([c.id, c2.id])
        assert g["count"] >= 1
        assert ed._find_clip(c2.id).start == ed._find_clip(c.id).end

        fr = ed.freeze_selection_mids([c.id], duration_frames=12)
        assert fr["count"] == 1
        assert fr["error_count"] == 0
        assert fr["freezes"][0].get("clip_id")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_15():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/expand_selection_links" in app
    assert "/api/edit/close_gaps_selection_tracks" in app
    assert "/api/edit/freeze_selection_mids" in app
    assert "def expand_selection_links" in mcp
    assert "def close_gaps_on_selection_tracks" in mcp
    assert "def freeze_selection_mids" in mcp
    assert 'id="btn-exp-link"' in html
    assert 'id="btn-gap-sel"' in html
    assert 'id="btn-frz-sel"' in html
    assert "expandSelectionLinksUi" in ts
    assert "closeGapsSelectionTracksUi" in ts
    assert "freezeSelectionMidsUi" in ts
