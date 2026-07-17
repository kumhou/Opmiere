"""set_selection_meta + clear_selection_subtitles (0.6.80)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=pink:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=510:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_meta_and_clear_subtitles():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ms_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        m = ed.set_selection_meta([c.id], name="Hero", color="#ff00aa")
        assert int(m.get("count") or 0) >= 1
        clip = ed._find_clip(c.id)
        assert clip.name == "Hero"
        assert clip.color == "#ff00aa"

        with ed._mutate():
            clip2 = ed._find_clip(c.id)
            clip2.effects = list(clip2.effects or []) + [
                {"type": "subtitles", "path": str(root / "x.srt")},
            ]
        clr = ed.clear_selection_subtitles([c.id])
        assert int(clr.get("count") or 0) >= 1
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "subtitles" not in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_80():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/set_selection_meta" in app
    assert "/api/edit/clear_selection_subtitles" in app
    assert "def set_selection_meta" in mcp
    assert "def clear_selection_subtitles" in mcp
    assert 'id="btn-meta-sel"' in html
    assert 'id="btn-sub-clr-sel"' in html
    assert "setSelectionMetaUi" in ts
    assert "clearSelectionSubtitlesUi" in ts
