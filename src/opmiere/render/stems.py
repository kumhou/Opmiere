"""Vocal/instrument stem separation via Demucs (optional dependency).

Gives the agent a way to duck original dialogue vs keep music bed, or mute
vocals under a new VO — without re-generating the whole track.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = ["separate_stems", "DemucsNotInstalledError"]


class DemucsNotInstalledError(RuntimeError):
    pass


def _require_demucs() -> None:
    try:
        import demucs  # noqa: F401
    except ImportError as e:
        raise DemucsNotInstalledError(
            "demucs is not installed. pip install demucs  "
            "(optional Opmiere extra for stem separation; pulls PyTorch)"
        ) from e


def separate_stems(
    path: Path | str,
    output_dir: Path | str,
    *,
    model: str = "htdemucs",
    two_stems: str | None = "vocals",
    device: str = "cpu",
) -> dict[str, Any]:
    """Separate ``path`` into stems under ``output_dir``.

    When ``two_stems`` is ``\"vocals\"`` (default), Demucs writes
    ``vocals.wav`` + ``no_vocals.wav`` (accompaniment). Set ``two_stems=None``
    for full 4-stem (drums/bass/other/vocals) if the model supports it.

    Uses the ``demucs`` CLI so we do not re-implement their API surface.
    """
    path = Path(path)
    output_dir = Path(output_dir)
    if not path.exists():
        raise FileNotFoundError(path)
    _require_demucs()
    require_ffmpeg_tools()
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio stream")

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="opmiere_demucs_") as td:
        td_path = Path(td)
        # Demucs prefers wav/flac input
        wav_in = td_path / "input.wav"
        ext = path.suffix.lower()
        if ext in {".wav", ".flac"}:
            shutil.copy2(path, wav_in)
        else:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "2", str(wav_in)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg extract for demucs failed:\n{proc.stderr}")

        cmd = [
            "python", "-m", "demucs",
            "-n", model,
            "-d", device,
            "-o", str(td_path / "out"),
        ]
        if two_stems:
            cmd += ["--two-stems", two_stems]
        cmd.append(str(wav_in))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"demucs failed (exit {proc.returncode}):\n{proc.stderr[-2000:]}"
            )

        # demucs layout: out/<model>/<track_name>/*.wav
        stem_root = td_path / "out" / model
        candidates = list(stem_root.rglob("*.wav"))
        if not candidates:
            raise RuntimeError(f"demucs produced no wav stems under {stem_root}")

        # Parent folder of stem files
        stem_dir = candidates[0].parent
        stems: dict[str, str] = {}
        for w in stem_dir.glob("*.wav"):
            dest = output_dir / w.name
            shutil.copy2(w, dest)
            stems[w.stem] = str(dest)

    return {
        "path": str(path),
        "model": model,
        "two_stems": two_stems,
        "device": device,
        "output_dir": str(output_dir),
        "stems": stems,
    }
