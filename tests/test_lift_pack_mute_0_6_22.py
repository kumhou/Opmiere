"""lift_selection + pack_selection + mute_selection (0.6.22)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_lift_pack_mute():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lpm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=10)
        c3 = ed.place_from_file(v, "video", tr.id, 40, duration_frames=10)

        pk = ed.pack_selection([c1.id, c2.id, c3.id], gap_frames=0)
        assert ed._find_clip(c1.id).start == 0
        assert ed._find_clip(c2.id).start == 10
        assert ed._find_clip(c3.id).start == 20
        assert pk.get("count", 0) >= 2

        mu = ed.mute_selection([c1.id, c2.id], muted=True)
        assert mu["count"] == 2
        assert ed._find_clip(c1.id).muted is True
        ed.mute_selection([c1.id], muted=False)
        assert ed._find_clip(c1.id).muted is False

        lf = ed.lift_selection([c2.id, c3.id])
        assert lf["count"] == 2
        assert lf["ripple"] is False
        assert ed._find_clip(c1.id).start == 0
        # c2/c3 gone
        remaining = [c.id for c in ed.project.track_by_id(tr.id).clips]
        assert c2.id not in remaining
        assert c3.id not in remaining
        assert c1.id in remaining
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_22():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/lift_selection" in app
    assert "/api/edit/pack_selection" in app
    assert "/api/edit/mute_selection" in app
    assert "def lift_selection" in mcp
    assert "def pack_selection" in mcp
    assert "def mute_selection" in mcp
    assert 'id="btn-lift-sel"' in html
    assert 'id="btn-pack-sel"' in html
    assert 'id="btn-mute-sel"' in html
    assert 'id="btn-unmute-sel"' in html
    assert "liftSelectionUi" in ts
    assert "packSelectionUi" in ts
    assert "muteSelectionUi" in ts
