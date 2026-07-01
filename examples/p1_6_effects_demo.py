"""P1.6 proof: gain + text (captions) actually change the rendered output.

Exports a clip with a Chinese+English caption (deliberately including a colon
and an apostrophe - the exact characters that broke naive ffmpeg drawtext
escaping during development) and an audio gain boost, then:
  1. extracts a frame so the caption can be looked at directly
  2. measures real mean volume (ffmpeg volumedetect) on the source vs the
     export to confirm the gain was actually applied, not just accepted
     without error

Run:  python examples/p1_6_effects_demo.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opmiere import Editor  # noqa: E402
from opmiere.render import probe  # noqa: E402

WORKDIR = Path(__file__).resolve().parent / "_p1_6_run"
FPS = 30
SECONDS = 2
GAIN_DB = 8.0


def make_sample(path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=480x270:rate={FPS}:duration={SECONDS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def mean_volume_db(path: Path) -> float:
    """Real measured mean volume via ffmpeg's volumedetect filter."""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", proc.stderr)
    if not match:
        raise RuntimeError(f"could not parse mean_volume from ffmpeg output:\n{proc.stderr}")
    return float(match.group(1))


def extract_frame(video_path: Path, at_seconds: float, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video_path),
           "-frames:v", "1", "-q:v", "3", str(out_path)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    src = WORKDIR / "source.mp4"
    make_sample(src)
    source_volume = mean_volume_db(src)

    editor = Editor.create(WORKDIR / "demo.opm", fps=FPS, width=480, height=270)
    media = editor.import_media(src, kind="video")
    track = editor.add_track("video")
    n = editor.project.timebase.seconds_to_frames(SECONDS)
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=n)

    editor.apply_effect(clip.id, {"type": "gain", "db": GAIN_DB})
    editor.apply_effect(clip.id, {
        "type": "text",
        "content": "你好 Opmiere: it's P1.6",
        "position": "bottom",
        "size": 32,
    })

    out = WORKDIR / "output.mp4"
    editor.export(out)

    result = probe(out)
    output_volume = mean_volume_db(out)

    print("--- ffprobe of exported file ---")
    print(f"duration_seconds: {result.duration_seconds:.3f}")
    print(f"resolution:       {result.width}x{result.height}")
    print("\n--- real measured mean volume (ffmpeg volumedetect) ---")
    print(f"source mean_volume: {source_volume:.2f} dB")
    print(f"output mean_volume: {output_volume:.2f} dB")
    print(f"delta:              {output_volume - source_volume:+.2f} dB (applied gain was {GAIN_DB:+.1f} dB)")

    extract_frame(out, SECONDS / 2, WORKDIR / "frame_caption.jpg")
    print(f"\nFrame with caption written to {WORKDIR / 'frame_caption.jpg'}")


if __name__ == "__main__":
    main()
