"""export_clips_pack + add_slate + close_gaps_all_tracks (0.6.3)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_slate_close_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_psc_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        # create a gap then close
        with ed._mutate():
            c2 = ed.project.add_clip(
                ed.project.track_by_id(tr.id),
                ed.project.media_by_id(c.media),
                int(c.end) + 20,
                0,
                10,
            )
            assert c2.start > c.end
        closed = ed.close_gaps_all_tracks()
        assert closed["count"] >= 1
        c2b = ed._find_clip(c2.id)
        assert c2b.start == c.end

        slate = ed.add_slate("TAKE 1", subtitle="cam A", duration_frames=15)
        assert slate["clip_id"]
        assert slate["mode"] == "prepend"
        card = ed._find_clip(slate["clip_id"])
        assert card.start == 0

        pack_dir = root / "pack"
        # only export the media clip (not title) for speed
        pack = ed.export_clips_pack([c.id], pack_dir, prefix="shot")
        assert pack["count"] >= 1
        assert pack["ok"]
        assert any(Path(x["path"]).exists() for x in pack["clips"] if x.get("ok"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_3():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/clips_pack" in app
    assert "/api/edit/slate" in app
    assert "/api/edit/close_gaps_all" in app
    assert "def export_clips_pack" in mcp
    assert "def add_slate" in mcp
    assert "def close_gaps_all_tracks" in mcp
    assert 'id="btn-clips-pack"' in html
    assert 'id="btn-slate"' in html
    assert 'id="btn-close-all"' in html
    assert "exportClipsPackUi" in ts
    assert "slateUi" in ts
    assert "closeGapsAllUi" in ts
