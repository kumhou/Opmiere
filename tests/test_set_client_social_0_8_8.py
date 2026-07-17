"""export_selection_set_client_pack + social_pack (0.8.8)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=steelblue:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=160:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_client_and_social_packs():
    root = Path(tempfile.mkdtemp(prefix="opmiere_scs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        client = ed.export_selection_set_client_pack(
            "hero",
            include_card=True,
            include_stills=True,
            include_export=False,
            include_review_export=False,
            stills_width=160,
        )
        assert client.get("ok") is True
        assert client.get("selection_set") == "hero"
        assert Path(client["out_dir"]).is_dir()

        social = ed.export_selection_set_social_pack(
            "hero",
            variants=["square"],
            normalize_preset=None,
        )
        assert social.get("selection_set") == "hero"
        assert Path(social["out_dir"]).is_dir()
        assert social.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_8():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_client_pack" in app
    assert "/api/edit/export_selection_set_social_pack" in app
    assert "def export_selection_set_client_pack" in mcp
    assert "def export_selection_set_social_pack" in mcp
    assert 'id="btn-set-client"' in html
    assert 'id="btn-set-social"' in html
    assert "exportSelectionSetClientPackUi" in ts
    assert "exportSelectionSetSocialPackUi" in ts
