"""Local speech-to-text for user footage (faster-whisper).

Gives the agent *ears that hear words*, not just LUFS: word/segment
timestamps → SRT → subtitles effect / edit decisions. Optional dependency
``faster-whisper`` — install when using caption tools; the rest of Opmiere
stays ffmpeg-only.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .probe import probe, require_ffmpeg_tools

__all__ = [
    "transcribe",
    "segments_to_srt",
    "write_srt",
    "WhisperNotInstalledError",
]


class WhisperNotInstalledError(RuntimeError):
    pass


def _require_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError as e:
        raise WhisperNotInstalledError(
            "faster-whisper is not installed. Install with: "
            "pip install 'faster-whisper>=1.0'  "
            "(optional Opmiere extra for caption/transcribe tools)"
        ) from e


def _extract_audio_wav(src: Path, wav: Path) -> None:
    """Mono 16 kHz wav — Whisper's happy path; works for video or audio files."""
    require_ffmpeg_tools()
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extract failed:\n{proc.stderr}")


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    """Format [{start, end, text}, ...] as SubRip. Real formatting, not a stub."""
    def ts(seconds: float) -> str:
        if seconds < 0:
            seconds = 0.0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms >= 1000:
            ms = 0
            s += 1
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks: list[str] = []
    for i, seg in enumerate(segments, start=1):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = float(seg["start"])
        end = float(seg["end"])
        if end <= start:
            end = start + 0.01
        blocks.append(f"{i}\n{ts(start)} --> {ts(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_srt(path: Path, segments: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(segments_to_srt(segments), encoding="utf-8")
    return path


def transcribe(
    path: Path | str,
    *,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    word_timestamps: bool = True,
) -> dict[str, Any]:
    """Transcribe audio/video at ``path`` with faster-whisper.

    Returns language, duration_seconds, segments (start/end/text + optional
    words[]), and the model_size used. Does not write SRT — call write_srt.
    """
    _require_faster_whisper()
    from faster_whisper import WhisperModel

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    info = probe(path)
    if not info.has_audio:
        raise ValueError(f"{path} has no audio stream to transcribe")

    with tempfile.TemporaryDirectory(prefix="opmiere_asr_") as td:
        wav = Path(td) / "audio.wav"
        _extract_audio_wav(path, wav)
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments_iter, info_asr = model.transcribe(
            str(wav),
            language=language,
            word_timestamps=word_timestamps,
            vad_filter=True,
        )
        segments: list[dict[str, Any]] = []
        for seg in segments_iter:
            item: dict[str, Any] = {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": (seg.text or "").strip(),
            }
            if word_timestamps and getattr(seg, "words", None):
                item["words"] = [
                    {
                        "start": float(w.start),
                        "end": float(w.end),
                        "word": (w.word or "").strip(),
                    }
                    for w in seg.words
                    if w is not None
                ]
            segments.append(item)

    return {
        "path": str(path),
        "language": getattr(info_asr, "language", language),
        "duration_seconds": info.duration_seconds,
        "model_size": model_size,
        "segments": segments,
    }
