"""export_selection_to_size + export_selection_social_pack (0.6.62)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_selection_size_and_social():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ss_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        sized = ed.export_selection_to_size(
            [c.id],
            width=120,
            height=200,
            fit="cover",
            filename="sel_size.mp4",
        )
        p = Path(sized.get("path") or "")
        assert p.is_file()
        assert int(sized.get("width") or 0) == 120
        assert int(sized.get("height") or 0) == 200

        pack = ed.export_selection_social_pack(
            [c.id],
            variants=["square"],
            name_prefix="t",
        )
        assert int(pack.get("count") or 0) >= 1
        out = Path(pack.get("out_dir") or "")
        assert out.is_dir()
        files = list(out.glob("*.mp4"))
        assert files
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_62():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_to_size" in app
    assert "/api/edit/export_selection_social_pack" in app
    assert "def export_selection_to_size" in mcp
    assert "def export_selection_social_pack" in mcp
    assert 'id="btn-size-sel"' in html
    assert 'id="btn-social-sel"' in html
    assert "exportSelectionToSizeUi" in ts
    assert "exportSelectionSocialPackUi" in ts
