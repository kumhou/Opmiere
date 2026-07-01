"""P0 proof with JH's real Phu Quoc footage (not synthetic test patterns).

Uses the two clips that share a frame rate (59.94 fps, HEVC, 3840x2160):
  VID_20260621_185532_089_02_16.mp4  (13.25s)
  VID_20260621_185730_090_02_16.mp4  (16.18s)

The other two source files in test_materials/ are 29.97 fps (h264) — mixing
frame rates on one track is a documented P0 limitation (render/ffmpeg.py
validates and refuses rather than silently producing a wrong cut), so they
are not used here. See the write-up sent alongside this run for details.

Run:  python examples/p0_real_footage_demo.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opmiere import Bundle, Project  # noqa: E402
from opmiere.render import FFmpegBackend, import_media, probe  # noqa: E402

MATERIALS = Path(__file__).resolve().parent.parent / "test_materials"
WORKDIR = Path(__file__).resolve().parent / "_real_footage_run"

CLIP_A = MATERIALS / "VID_20260621_185532_089_02_16.mp4"
CLIP_B = MATERIALS / "VID_20260621_185730_090_02_16.mp4"

FPS = 60000 / 1001  # matches both source files exactly (ffprobe: 60000/1001)
SECONDS_PER_CLIP = 3


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    project = Project()
    project.timebase.fps = FPS
    project.resolution.w, project.resolution.h = 3840, 2160

    bundle = Bundle.create(WORKDIR / "phuquoc.opm", project=project)

    print(f"Importing {CLIP_A.name} and {CLIP_B.name}...")
    media_a = import_media(bundle, project, CLIP_A, kind="video")
    media_b = import_media(bundle, project, CLIP_B, kind="video")
    print(f"  {media_a.id}: {media_a.duration_frames}f "
          f"({project.timebase.frames_to_seconds(media_a.duration_frames):.2f}s)")
    print(f"  {media_b.id}: {media_b.duration_frames}f "
          f"({project.timebase.frames_to_seconds(media_b.duration_frames):.2f}s)")

    n = project.timebase.seconds_to_frames(SECONDS_PER_CLIP)
    video_track = project.add_track("video")
    clip_a = project.add_clip(video_track, media_a, start=0, src_in=0, src_out=n)
    project.add_clip(video_track, media_b, start=clip_a.end, src_in=0, src_out=n)

    bundle.save(project)
    print(f"Timeline duration: {project.duration_frames()} frames "
          f"({project.timebase.frames_to_seconds(project.duration_frames()):.2f}s)")

    output_path = WORKDIR / "output.mp4"
    print("Exporting (4K HEVC source -> h264 cut, may take a bit)...")
    FFmpegBackend().export(project, bundle, output_path)

    result = probe(output_path)
    print("\n--- ffprobe of exported file (ground truth, not claimed) ---")
    print(f"path:            {output_path}")
    print(f"duration_seconds:{result.duration_seconds:.3f}")
    print(f"fps:             {result.fps}")
    print(f"resolution:      {result.width}x{result.height}")
    print(f"has_video:       {result.has_video}")
    print(f"has_audio:       {result.has_audio}")


if __name__ == "__main__":
    main()
