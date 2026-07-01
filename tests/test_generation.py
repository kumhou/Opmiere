"""Tests for the generation wiring in Editor (ops.py).

Uses a FakeProvider rather than ComfyUIProvider: these test the Editor-level
contract (job lifecycle, place_generated's validation, origin recording),
not ComfyUI itself, so the suite stays hermetic and doesn't require a live
GPU server. See examples/p2_1_generation_demo.py for the real, GPU-backed,
end-to-end proof.
"""

import subprocess
from pathlib import Path

import pytest

from opmiere import Editor
from opmiere.generation.provider import GenerationJob, GenerationProvider, JobStatus

FPS = 30


class FakeProvider(GenerationProvider):
    name = "fake"

    def __init__(self):
        self._jobs: dict[str, GenerationJob] = {}
        self._next_id = 0

    def submit(self, kind: str, prompt: str, params: dict) -> str:
        job_id = f"job_{self._next_id}"
        self._next_id += 1
        self._jobs[job_id] = GenerationJob(id=job_id, status=JobStatus.RUNNING, kind=kind, prompt=prompt)
        return job_id

    def status(self, job_id: str) -> GenerationJob:
        return self._jobs[job_id]

    def complete(self, job_id: str, result_path: Path) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = GenerationJob(
            id=job_id, status=JobStatus.DONE, kind=job.kind, prompt=job.prompt, result_path=result_path,
        )

    def fail(self, job_id: str, error: str) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = GenerationJob(
            id=job_id, status=JobStatus.ERROR, kind=job.kind, prompt=job.prompt, error=error,
        )


@pytest.fixture(scope="module")
def sample_image(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("gen_media")
    path = d / "sample.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def editor(tmp_path, provider) -> Editor:
    return Editor.create(tmp_path / "demo.opm", fps=FPS, width=64, height=64, generation_provider=provider)


def test_generate_without_provider_raises(tmp_path):
    editor = Editor.create(tmp_path / "demo.opm", fps=FPS)  # no generation_provider
    with pytest.raises(RuntimeError):
        editor.generate("image", "a red square")


def test_generate_returns_job_id_and_status_tracks_it(editor):
    job_id = editor.generate("image", "a red square")
    job = editor.job_status(job_id)
    assert job.status == JobStatus.RUNNING
    assert job.prompt == "a red square"


def test_place_generated_rejects_unfinished_job(editor):
    job_id = editor.generate("image", "a red square")
    with pytest.raises(ValueError):
        editor.place_generated(job_id, track_id="trk_doesnotexist", start=0, duration_frames=30)


def test_place_generated_rejects_error_job(editor, provider):
    job_id = editor.generate("image", "a red square")
    provider.fail(job_id, "GPU on fire")
    with pytest.raises(ValueError):
        editor.place_generated(job_id, track_id="trk_doesnotexist", start=0, duration_frames=30)


def test_place_generated_imports_and_creates_clip(editor, provider, sample_image):
    job_id = editor.generate("image", "a red square")
    provider.complete(job_id, sample_image)
    track = editor.add_track("video")

    clip = editor.place_generated(job_id, track.id, start=0, duration_frames=45)

    assert clip.src_in == 0
    assert clip.src_out == 45
    media = editor.project.media_by_id(clip.media)
    assert media.kind == "image"
    assert media.origin == {"provider": "fake", "job": job_id, "prompt": "a red square"}
    assert editor.duration_frames() == 45


def test_place_generated_rejects_non_positive_duration(editor, provider, sample_image):
    job_id = editor.generate("image", "a red square")
    provider.complete(job_id, sample_image)
    track = editor.add_track("video")
    with pytest.raises(ValueError):
        editor.place_generated(job_id, track.id, start=0, duration_frames=0)


def test_generated_image_exports_to_real_video(editor, provider, sample_image, tmp_path):
    job_id = editor.generate("image", "a red square")
    provider.complete(job_id, sample_image)
    track = editor.add_track("video")
    editor.place_generated(job_id, track.id, start=0, duration_frames=30)

    out = tmp_path / "out.mp4"
    editor.export(out)

    from opmiere.render import probe
    result = probe(out)
    assert abs(result.duration_seconds - 1.0) < 0.05  # 30 frames @ 30fps
    assert result.has_video
