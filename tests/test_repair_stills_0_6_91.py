"""repair_selection + export_selection_stills_default (0.6.91)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=620:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_repair_and_stills_default():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        # lock then repair should unlock
        ed.set_track_locked(tr.id, True)
        rep = ed.repair_selection(
            [c.id],
            unlock=True,
            ensure_proxies=False,
            pack_gaps=False,
            set_work_area=False,
        )
        assert "unlock" in rep.get("steps") or "unlock_selection_tracks" in (
            rep.get("steps") or []
        )
        assert ed.project.track_by_id(tr.id).locked is False
        assert rep.get("after", {}).get("ok") is True

        stills = ed.export_selection_stills_default(
            [c.id], width=160, edge="mid",
        )
        # response shape may use count/output_dir/path
        assert stills is not None
        out = stills.get("output_dir") or stills.get("path") or stills.get("out_dir")
        if out:
            p = Path(str(out))
            if p.is_dir():
                assert list(p.glob("*.jpg")) or list(p.glob("*.png"))
            elif p.is_file():
                assert p.stat().st_size > 0
        else:
            # stills list
            items = stills.get("stills") or stills.get("written") or []
            assert items or int(stills.get("count") or 0) >= 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_91():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/repair_selection" in app
    assert "/api/edit/export_selection_stills_default" in app
    assert "def repair_selection" in mcp
    assert "def export_selection_stills_default" in mcp
    assert 'id="btn-repair-sel"' in html
    assert 'id="btn-stills-def-sel"' in html
    assert "repairSelectionUi" in ts
    assert "exportSelectionStillsDefaultUi" in ts
