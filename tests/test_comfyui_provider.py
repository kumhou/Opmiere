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
        provider.submit("audio", "x", {})
