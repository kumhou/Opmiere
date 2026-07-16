"""apply_compression + apply_audio_eq + export_clip_audio (0.6.0)."""

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


def test_compression_eq_clip_audio():
    root = Path(tempfile.mkdtemp(prefix="opmiere_afx_"))
    try:
        v = root / "v.mp4"
        _vid_audio(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        cp = ed.apply_compression(c.id, ratio=3.0, threshold_db=-20)
        assert cp["clip_id"] == c.id
        assert any(
            e.get("type") == "compression" and float(e.get("ratio", 0)) == 3.0
            for e in (ed._find_clip(c.id).effects or [])
        )
        eq = ed.apply_audio_eq(c.id, frequency_hz=800, gain_db=2.0, q=1.2)
        assert eq["clip_id"] == c.id
        assert any(
            e.get("type") == "audio_eq" and float(e.get("frequency_hz", 0)) == 800
            for e in (ed._find_clip(c.id).effects or [])
        )
        with ed._mutate():
            ed._find_clip(c.id).effects = []
        out = ed.export_clip_audio(c.id, root / "a.wav")
        assert Path(out["path"]).exists()
        assert out["clip_id"] == c.id
        assert Path(out["path"]).stat().st_size > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_0():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/compression" in app
    assert "/api/clip/audio_eq" in app
    assert "/api/export/clip_audio" in app
    assert "def apply_compression" in mcp
    assert "def apply_audio_eq" in mcp
    assert "def export_clip_audio" in mcp
    assert 'id="btn-comp"' in html
    assert 'id="btn-eq"' in html
    assert 'id="btn-clip-aud"' in html
    assert "compressionUi" in ts
    assert "audioEqUi" in ts
    assert "exportClipAudioUi" in ts
