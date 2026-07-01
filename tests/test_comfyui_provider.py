"""Pure structural tests for ComfyUIProvider's workflow builders — no network,
no live ComfyUI server. These catch accidental graph corruption (a dangling
link, a renamed input) on edit; they do not substitute for the real,
GPU-verified runs in examples/p2_1_generation_demo.py and
examples/p2_2_video_generation_demo.py.
"""

import pytest

from opmiere.generation.comfyui import ComfyUIProvider


@pytest.fixture
def provider(tmp_path) -> ComfyUIProvider:
    return ComfyUIProvider(output_dir=tmp_path)


def test_txt2img_workflow_has_expected_nodes_and_wiring(provider):
    wf = provider._build_txt2img_workflow("a red bicycle", {})

    assert wf["4"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["6"]["inputs"]["text"] == "a red bicycle"
    assert wf["3"]["inputs"]["model"] == ["4", 0]
    assert wf["3"]["inputs"]["positive"] == ["6", 0]
    assert wf["9"]["class_type"] == "SaveImage"
    assert wf["9"]["inputs"]["images"] == ["8", 0]


def test_txt2img_workflow_respects_params(provider):
    wf = provider._build_txt2img_workflow("x", {"width": 768, "height": 640, "seed": 42, "steps": 4})

    assert wf["5"]["inputs"]["width"] == 768
    assert wf["5"]["inputs"]["height"] == 640
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["3"]["inputs"]["steps"] == 4


def test_ltxv_workflow_has_expected_nodes_and_wiring(provider):
    wf = provider._build_ltxv_workflow("a paper boat", {})

    assert wf["44"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["44"]["inputs"]["ckpt_name"] == provider.video_checkpoint
    assert wf["38"]["inputs"]["clip_name"] == provider.video_text_encoder
    assert wf["6"]["inputs"]["text"] == "a paper boat"
    assert wf["72"]["inputs"]["model"] == ["44", 0]
    assert wf["79"]["class_type"] == "SaveVideo"
    assert wf["78"]["class_type"] == "CreateVideo"


def test_ltxv_workflow_frame_rate_flows_to_conditioning_and_output(provider):
    wf = provider._build_ltxv_workflow("x", {"frame_rate": 24, "num_frames": 49})

    assert wf["69"]["inputs"]["frame_rate"] == 24
    assert wf["78"]["inputs"]["fps"] == 24
    assert wf["70"]["inputs"]["length"] == 49


def test_submit_rejects_unsupported_kind(provider):
    with pytest.raises(NotImplementedError):
        provider.submit("sfx", "x", {})


def test_speech_preset_voice_workflow_has_expected_nodes_and_wiring(provider):
    wf = provider._build_speech_workflow("hello world", {})

    assert wf["1"]["inputs"]["repo_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert wf["2"]["class_type"] == "Qwen3CustomVoice"
    assert wf["2"]["inputs"]["text"] == "hello world"
    assert wf["2"]["inputs"]["speaker"] == "Vivian"
    assert wf["4"]["class_type"] == "SaveAudio"
    assert wf["4"]["inputs"]["audio"] == ["2", 0]


def test_speech_preset_voice_respects_speaker_param(provider):
    wf = provider._build_speech_workflow("x", {"speaker": "Dylan", "language": "Chinese"})

    assert wf["2"]["inputs"]["speaker"] == "Dylan"
    assert wf["2"]["inputs"]["language"] == "Chinese"


def test_speech_clone_workflow_uploads_reference_and_wires_clone_node(provider, tmp_path):
    provider.comfyui_input_dir = tmp_path / "comfy_input"
    provider.comfyui_input_dir.mkdir()
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"not real audio, just testing the copy")

    wf = provider._build_speech_workflow(
        "cloned speech", {"reference_audio": str(ref), "reference_text": "the reference said this"}
    )

    assert wf["1"]["inputs"]["repo_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert wf["3"]["class_type"] == "Qwen3VoiceClone"
    assert wf["3"]["inputs"]["text"] == "cloned speech"
    assert wf["3"]["inputs"]["ref_text"] == "the reference said this"
    assert wf["3"]["inputs"]["ref_audio"] == ["2", 0]
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
