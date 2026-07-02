"""Pure structural tests for ComfyUIProvider's workflow builders — no network,
no live ComfyUI server. These catch accidental graph corruption (a dangling
link, a renamed input) on edit; they do not substitute for the real,
GPU-verified runs in examples/p2_1_generation_demo.py and
examples/p2_2_video_generation_demo.py.
"""

from pathlib import Path

import pytest

from opmiere.generation.comfyui import (
    CHECKPOINT_LICENSES,
    DEFAULT_FLUX_DEV_CHECKPOINT,
    DEFAULT_FLUX_SCHNELL_CHECKPOINT,
    DEFAULT_IMAGE_CHECKPOINT,
    DEFAULT_SPEECH_CLONE_MODEL,
    DEFAULT_SPEECH_CUSTOM_VOICE_MODEL,
    DEFAULT_VIDEO_CHECKPOINT,
    DEFAULT_WAN21_T2V_CHECKPOINT,
    DEFAULT_WAN22_HIGHNOISE_CHECKPOINT,
    DEFAULT_WAN22_LOWNOISE_CHECKPOINT,
    WAN22_MOE_LICENSE_KEY,
    ComfyUIProvider,
)
from opmiere.generation.provider import JobStatus


@pytest.fixture
def provider(tmp_path) -> ComfyUIProvider:
    return ComfyUIProvider(output_dir=tmp_path)


def test_txt2img_workflow_has_expected_nodes_and_wiring(provider):
    wf, checkpoint = provider._build_txt2img_workflow("a red bicycle", {})

    assert wf["4"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["6"]["inputs"]["text"] == "a red bicycle"
    assert wf["3"]["inputs"]["model"] == ["4", 0]
    assert wf["3"]["inputs"]["positive"] == ["6", 0]
    assert wf["9"]["class_type"] == "SaveImage"
    assert wf["9"]["inputs"]["images"] == ["8", 0]
    assert checkpoint == wf["4"]["inputs"]["ckpt_name"]


def test_txt2img_workflow_respects_params(provider):
    wf, _ = provider._build_txt2img_workflow("x", {"width": 768, "height": 640, "seed": 42, "steps": 4})

    assert wf["5"]["inputs"]["width"] == 768
    assert wf["5"]["inputs"]["height"] == 640
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["3"]["inputs"]["steps"] == 4


def test_ltxv_workflow_has_expected_nodes_and_wiring(provider):
    wf, checkpoint = provider._build_ltxv_workflow("a paper boat", {})

    assert wf["44"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["44"]["inputs"]["ckpt_name"] == provider.video_checkpoint
    assert wf["38"]["inputs"]["clip_name"] == provider.video_text_encoder
    assert wf["6"]["inputs"]["text"] == "a paper boat"
    assert wf["72"]["inputs"]["model"] == ["44", 0]
    assert wf["79"]["class_type"] == "SaveVideo"
    assert wf["78"]["class_type"] == "CreateVideo"
    assert checkpoint == provider.video_checkpoint


def test_ltxv_workflow_frame_rate_flows_to_conditioning_and_output(provider):
    wf, _ = provider._build_ltxv_workflow("x", {"frame_rate": 24, "num_frames": 49})

    assert wf["69"]["inputs"]["frame_rate"] == 24
    assert wf["78"]["inputs"]["fps"] == 24
    assert wf["70"]["inputs"]["length"] == 49


def test_submit_rejects_unsupported_kind(provider):
    with pytest.raises(NotImplementedError):
        provider.submit("sfx", "x", {})


def test_speech_preset_voice_workflow_has_expected_nodes_and_wiring(provider):
    wf, checkpoint = provider._build_speech_workflow("hello world", {})

    assert wf["1"]["inputs"]["repo_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert wf["2"]["class_type"] == "Qwen3CustomVoice"
    assert wf["2"]["inputs"]["text"] == "hello world"
    assert wf["2"]["inputs"]["speaker"] == "Vivian"
    assert wf["4"]["class_type"] == "SaveAudio"
    assert wf["4"]["inputs"]["audio"] == ["2", 0]
    assert checkpoint == wf["1"]["inputs"]["repo_id"]


def test_speech_preset_voice_respects_speaker_param(provider):
    wf, _ = provider._build_speech_workflow("x", {"speaker": "Dylan", "language": "Chinese"})

    assert wf["2"]["inputs"]["speaker"] == "Dylan"
    assert wf["2"]["inputs"]["language"] == "Chinese"


def test_speech_clone_workflow_uploads_reference_and_wires_clone_node(provider, tmp_path):
    provider.comfyui_input_dir = tmp_path / "comfy_input"
    provider.comfyui_input_dir.mkdir()
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"not real audio, just testing the copy")

    wf, checkpoint = provider._build_speech_workflow(
        "cloned speech", {"reference_audio": str(ref), "reference_text": "the reference said this"}
    )

    assert wf["1"]["inputs"]["repo_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert wf["3"]["class_type"] == "Qwen3VoiceClone"
    assert wf["3"]["inputs"]["text"] == "cloned speech"
    assert wf["3"]["inputs"]["ref_text"] == "the reference said this"
    assert wf["3"]["inputs"]["ref_audio"] == ["2", 0]
    assert checkpoint == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    uploaded_name = wf["2"]["inputs"]["audio"]
    assert (provider.comfyui_input_dir / uploaded_name).exists()


def test_speech_clone_requires_reference_text(provider, tmp_path):
    provider.comfyui_input_dir = tmp_path
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    with pytest.raises(ValueError, match="reference_text"):
        provider._build_speech_workflow("x", {"reference_audio": str(ref)})


def test_speech_clone_requires_comfyui_input_dir_configured(provider, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    assert provider.comfyui_input_dir is None
    with pytest.raises(ValueError, match="comfyui_input_dir"):
        provider._build_speech_workflow("x", {"reference_audio": str(ref), "reference_text": "hi"})


def test_speech_clone_rejects_missing_reference_file(provider, tmp_path):
    provider.comfyui_input_dir = tmp_path
    with pytest.raises(FileNotFoundError):
        provider._build_speech_workflow(
            "x", {"reference_audio": str(tmp_path / "nope.wav"), "reference_text": "hi"}
        )


def test_flux_schnell_workflow_has_expected_nodes_and_wiring(provider):
    wf, checkpoint = provider._build_flux_workflow("a red bicycle", {}, "flux-schnell")

    assert checkpoint == DEFAULT_FLUX_SCHNELL_CHECKPOINT
    assert wf["30"]["class_type"] == "UnetLoaderGGUF"
    assert wf["30"]["inputs"]["unet_name"] == DEFAULT_FLUX_SCHNELL_CHECKPOINT
    assert wf["31"]["class_type"] == "DualCLIPLoader"
    assert wf["31"]["inputs"]["type"] == "flux"
    assert wf["6"]["inputs"]["text"] == "a red bicycle"
    assert wf["3"]["inputs"]["steps"] == 4
    assert wf["3"]["inputs"]["cfg"] == 1.0
    assert wf["3"]["inputs"]["model"] == ["30", 0]
    assert wf["9"]["class_type"] == "SaveImage"


def test_flux_dev_workflow_uses_more_steps_and_dev_checkpoint(provider):
    wf, checkpoint = provider._build_flux_workflow("a red bicycle", {}, "flux-dev")

    assert checkpoint == DEFAULT_FLUX_DEV_CHECKPOINT
    assert wf["30"]["inputs"]["unet_name"] == DEFAULT_FLUX_DEV_CHECKPOINT
    assert wf["3"]["inputs"]["steps"] == 20


def test_flux_workflow_respects_params(provider):
    wf, checkpoint = provider._build_flux_workflow(
        "x", {"width": 768, "height": 768, "steps": 8, "seed": 7}, "flux-schnell"
    )

    assert wf["27"]["inputs"]["width"] == 768
    assert wf["27"]["inputs"]["height"] == 768
    assert wf["3"]["inputs"]["steps"] == 8
    assert wf["3"]["inputs"]["seed"] == 7
    assert checkpoint == DEFAULT_FLUX_SCHNELL_CHECKPOINT


def test_flux_workflow_rejects_unknown_model(provider):
    with pytest.raises(ValueError, match="flux-schnell, flux-dev"):
        provider._build_flux_workflow("x", {}, "flux-turbo")


def test_checkpoint_licenses_cover_every_default_checkpoint():
    for checkpoint in (
        DEFAULT_IMAGE_CHECKPOINT, DEFAULT_VIDEO_CHECKPOINT, DEFAULT_FLUX_SCHNELL_CHECKPOINT,
        DEFAULT_FLUX_DEV_CHECKPOINT, DEFAULT_SPEECH_CUSTOM_VOICE_MODEL, DEFAULT_SPEECH_CLONE_MODEL,
        DEFAULT_WAN21_T2V_CHECKPOINT, WAN22_MOE_LICENSE_KEY,
    ):
        assert checkpoint in CHECKPOINT_LICENSES, f"{checkpoint} generates real output with no tracked license"
        assert CHECKPOINT_LICENSES[checkpoint].commercial_use in ("yes", "no", "conditional")


def test_submit_dispatches_image_model_param_to_flux_and_records_checkpoint(provider, monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["prompt"] = payload["prompt"]
        return {"prompt_id": "job-1"}

    monkeypatch.setattr(provider, "_post", fake_post)

    job_id = provider.submit("image", "a red bicycle", {"model": "flux-dev"})

    assert job_id == "job-1"
    assert captured["prompt"]["30"]["inputs"]["unet_name"] == DEFAULT_FLUX_DEV_CHECKPOINT
    assert provider._jobs["job-1"]["checkpoint"] == DEFAULT_FLUX_DEV_CHECKPOINT


def test_submit_defaults_image_model_to_sd15(provider, monkeypatch):
    monkeypatch.setattr(provider, "_post", lambda path, payload: {"prompt_id": "job-2"})

    provider.submit("image", "x", {})

    assert provider._jobs["job-2"]["checkpoint"] == DEFAULT_IMAGE_CHECKPOINT


def test_submit_rejects_unknown_image_model(provider):
    with pytest.raises(ValueError, match="sd1.5, flux-schnell, flux-dev"):
        provider.submit("image", "x", {"model": "midjourney"})


def test_status_done_attaches_license_for_known_checkpoint(provider, monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "_post", lambda path, payload: {"prompt_id": "job-3"})
    job_id = provider.submit("image", "x", {"model": "flux-dev"})

    history = {
        job_id: {
            "status": {"status_str": "success"},
            "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
        }
    }
    monkeypatch.setattr(provider, "_get", lambda path: history)
    monkeypatch.setattr(
        "opmiere.generation.comfyui.urllib.request.urlretrieve",
        lambda url, dest: Path(dest).write_bytes(b"fake png bytes"),
    )

    job = provider.status(job_id)

    assert job.status == JobStatus.DONE
    assert job.license is not None
    assert job.license.name == "FLUX.1-dev Non-Commercial License"
    assert job.license.commercial_use == "no"


def test_wan_workflow_has_expected_nodes_and_wiring(provider):
    wf, checkpoint = provider._build_wan_workflow("a paper boat", {})

    assert checkpoint == DEFAULT_WAN21_T2V_CHECKPOINT
    assert wf["37"]["class_type"] == "UNETLoader"
    assert wf["37"]["inputs"]["unet_name"] == DEFAULT_WAN21_T2V_CHECKPOINT
    assert wf["38"]["class_type"] == "CLIPLoader"
    assert wf["38"]["inputs"]["type"] == "wan"
    assert wf["6"]["inputs"]["text"] == "a paper boat"
    assert wf["48"]["class_type"] == "ModelSamplingSD3"
    assert wf["48"]["inputs"]["model"] == ["37", 0]
    assert wf["3"]["inputs"]["model"] == ["48", 0]
    assert wf["79"]["class_type"] == "SaveVideo"
    assert wf["78"]["class_type"] == "CreateVideo"


def test_wan_workflow_respects_params(provider):
    wf, _ = provider._build_wan_workflow("x", {"width": 480, "height": 480, "num_frames": 17, "shift": 5.0})

    assert wf["40"]["inputs"]["width"] == 480
    assert wf["40"]["inputs"]["height"] == 480
    assert wf["40"]["inputs"]["length"] == 17
    assert wf["48"]["inputs"]["shift"] == 5.0


def test_submit_dispatches_video_model_param_to_wan_and_records_checkpoint(provider, monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["prompt"] = payload["prompt"]
        return {"prompt_id": "job-4"}

    monkeypatch.setattr(provider, "_post", fake_post)

    job_id = provider.submit("video", "a paper boat", {"model": "wan2.1"})

    assert job_id == "job-4"
    assert captured["prompt"]["37"]["inputs"]["unet_name"] == DEFAULT_WAN21_T2V_CHECKPOINT
    assert provider._jobs["job-4"]["checkpoint"] == DEFAULT_WAN21_T2V_CHECKPOINT


def test_submit_defaults_video_model_to_ltx(provider, monkeypatch):
    monkeypatch.setattr(provider, "_post", lambda path, payload: {"prompt_id": "job-5"})

    provider.submit("video", "x", {})

    assert provider._jobs["job-5"]["checkpoint"] == provider.video_checkpoint


def test_submit_rejects_unknown_video_model(provider):
    with pytest.raises(ValueError, match="ltx-video, wan2.1, wan2.2-moe"):
        provider.submit("video", "x", {"model": "veo"})


def test_wan22_moe_workflow_has_expected_nodes_and_wiring(provider):
    wf, license_key = provider._build_wan22_moe_workflow("a paper boat", {})

    assert license_key == WAN22_MOE_LICENSE_KEY
    assert wf["75"]["class_type"] == "UnetLoaderGGUF"
    assert wf["75"]["inputs"]["unet_name"] == DEFAULT_WAN22_HIGHNOISE_CHECKPOINT
    assert wf["76"]["class_type"] == "UnetLoaderGGUF"
    assert wf["76"]["inputs"]["unet_name"] == DEFAULT_WAN22_LOWNOISE_CHECKPOINT
    assert wf["6"]["inputs"]["text"] == "a paper boat"
    # Two-stage hand-off: stage 1 (high-noise) ends where stage 2 (low-noise)
    # picks up, sharing the same latent chain.
    assert wf["20"]["inputs"]["model"] == ["82", 0]
    assert wf["20"]["inputs"]["add_noise"] == "enable"
    assert wf["20"]["inputs"]["return_with_leftover_noise"] == "enable"
    assert wf["21"]["inputs"]["model"] == ["86", 0]
    assert wf["21"]["inputs"]["latent_image"] == ["20", 0]
    assert wf["21"]["inputs"]["add_noise"] == "disable"
    assert wf["20"]["inputs"]["end_at_step"] == wf["21"]["inputs"]["start_at_step"]
    assert wf["79"]["class_type"] == "SaveVideo"
    assert wf["78"]["class_type"] == "CreateVideo"


def test_wan22_moe_workflow_respects_params(provider):
    wf, _ = provider._build_wan22_moe_workflow("x", {"width": 640, "height": 640, "steps": 10, "split_step": 4})

    assert wf["40"]["inputs"]["width"] == 640
    assert wf["40"]["inputs"]["height"] == 640
    assert wf["20"]["inputs"]["steps"] == 10
    assert wf["20"]["inputs"]["end_at_step"] == 4
    assert wf["21"]["inputs"]["start_at_step"] == 4


def test_submit_dispatches_video_model_param_to_wan22_moe(provider, monkeypatch):
    captured = {}

    def fake_post(path, payload):
        captured["prompt"] = payload["prompt"]
        return {"prompt_id": "job-6"}

    monkeypatch.setattr(provider, "_post", fake_post)

    job_id = provider.submit("video", "a paper boat", {"model": "wan2.2-moe"})

    assert job_id == "job-6"
    assert captured["prompt"]["75"]["inputs"]["unet_name"] == DEFAULT_WAN22_HIGHNOISE_CHECKPOINT
    assert provider._jobs["job-6"]["checkpoint"] == WAN22_MOE_LICENSE_KEY
