"""compression_selection + noise_reduction_selection + audio_eq_selection (0.6.37)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _wav(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def _has(clip, etype: str) -> bool:
    return any(
        isinstance(e, dict) and e.get("type") == etype
        for e in (clip.effects or [])
    )


def test_comp_nr_eq():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cne_"))
    try:
        a = root / "a.wav"
        _wav(a, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("audio")
        med = ed.import_media(a, "audio")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 15)
        c2 = ed.add_clip(tr.id, med.id, 15, 0, 15)

        cp = ed.compression_selection([c1.id], ratio=3.0, threshold_db=-20.0)
        assert cp["count"] == 1
        assert _has(ed._find_clip(c1.id), "compression")

        nr = ed.noise_reduction_selection([c1.id, c2.id], amount=10.0)
        assert nr["count"] == 2
        assert _has(ed._find_clip(c2.id), "noise_reduction")

        eq = ed.audio_eq_selection(
            [c2.id], frequency_hz=1000.0, gain_db=3.0, q=1.0,
        )
        assert eq["count"] == 1
        assert _has(ed._find_clip(c2.id), "audio_eq")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_37():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/compression_selection" in app
    assert "/api/edit/noise_reduction_selection" in app
    assert "/api/edit/audio_eq_selection" in app
    assert "def compression_selection" in mcp
    assert "def noise_reduction_selection" in mcp
    assert "def audio_eq_selection" in mcp
    assert 'id="btn-comp-sel"' in html
    assert 'id="btn-nr-sel"' in html
    assert 'id="btn-eq-sel"' in html
    assert "compressionSelectionUi" in ts
    assert "noiseReductionSelectionUi" in ts
    assert "audioEqSelectionUi" in ts
