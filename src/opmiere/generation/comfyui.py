"""ComfyUIProvider — the local GPU generation backend (ARCHITECTURE.md 5.3/5.7).

Talks to a running ComfyUI server (default http://127.0.0.1:8188) over its
plain HTTP API: POST a node-graph workflow to /prompt, poll /history/{id},
fetch the result bytes via /view. This is exactly the workflow verified by
hand against this machine's RTX 3070 before any of this file was written
(SD1.5, 512x512, 20 steps, ~7s) — the txt2img graph below is that same graph,
parameterized.

Scope note: image (SD1.5 checkpoint) only for now. Video/audio generation and
the VRAM-adaptive quantization profiles from section 5.7 (GGUF, block-swap,
etc.) are follow-up work once this basic wiring is proven end to end.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .provider import GenerationJob, GenerationProvider, JobStatus

DEFAULT_CHECKPOINT = "v1-5-pruned-emaonly-fp16.safetensors"


class ComfyUIProvider(GenerationProvider):
    name = "comfyui"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        output_dir: Path | None = None,
        checkpoint: str = DEFAULT_CHECKPOINT,
    ):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / ".opmiere_generated"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint = checkpoint
        self.client_id = str(uuid.uuid4())
        # ComfyUI's /history doesn't echo back a plain-text "kind"/"prompt" in
        # an easily queryable form, so we remember our own request alongside
        # its job id rather than re-parsing the submitted graph back out.
        self._jobs: dict[str, dict[str, str]] = {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ComfyUI POST {path} failed: {e.code} {e.read().decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"could not reach ComfyUI at {self.base_url} — is the server running?"
            ) from e

    def _get(self, path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}") as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"could not reach ComfyUI at {self.base_url} — is the server running?"
            ) from e

    def _build_txt2img_workflow(self, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        width = params.get("width", 512)
        height = params.get("height", 512)
        steps = params.get("steps", 20)
        cfg = params.get("cfg", 7.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get("negative_prompt", "blurry, low quality, watermark, text")
        checkpoint = params.get("checkpoint", self.checkpoint)
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                    "scheduler": "normal", "denoise": 1.0,
                    "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "opmiere_gen", "images": ["8", 0]}},
        }

    def submit(self, kind: str, prompt: str, params: dict[str, Any]) -> str:
        if kind != "image":
            raise NotImplementedError(
                f"ComfyUIProvider only supports kind='image' so far, got {kind!r} "
                "(video/audio generation are follow-up work)"
            )
        workflow = self._build_txt2img_workflow(prompt, params)
        resp = self._post("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if resp.get("node_errors"):
            raise ValueError(f"ComfyUI rejected the workflow: {resp['node_errors']}")
        job_id = resp["prompt_id"]
        self._jobs[job_id] = {"kind": kind, "prompt": prompt}
        return job_id

    def status(self, job_id: str) -> GenerationJob:
        if job_id not in self._jobs:
            raise KeyError(f"unknown job id {job_id!r} (not submitted through this provider instance)")
        meta = self._jobs[job_id]
        history = self._get(f"/history/{job_id}")

        if job_id not in history:
            # Not in history yet: ComfyUI doesn't distinguish "still queued"
            # from "actively running" through this simple endpoint, so both
            # report as RUNNING here - the caller's action (keep polling) is
            # the same either way. See provider.py's JobStatus for the
            # documented vocabulary.
            return GenerationJob(id=job_id, status=JobStatus.RUNNING, kind=meta["kind"], prompt=meta["prompt"])

        entry = history[job_id]
        status_str = entry.get("status", {}).get("status_str")
        if status_str != "success":
            messages = entry.get("status", {}).get("messages", [])
            return GenerationJob(
                id=job_id, status=JobStatus.ERROR, kind=meta["kind"], prompt=meta["prompt"],
                error=f"ComfyUI job did not succeed (status_str={status_str!r}): {messages}",
            )

        images = entry.get("outputs", {}).get("9", {}).get("images", [])
        if not images:
            return GenerationJob(
                id=job_id, status=JobStatus.ERROR, kind=meta["kind"], prompt=meta["prompt"],
                error="ComfyUI reported success but produced no images in the expected output node",
            )
        img = images[0]
        url = (
            f"{self.base_url}/view?filename={img['filename']}"
            f"&subfolder={img.get('subfolder', '')}&type={img['type']}"
        )
        dest = self.output_dir / f"{job_id}_{img['filename']}"
        try:
            urllib.request.urlretrieve(url, dest)
        except urllib.error.URLError as e:
            raise ConnectionError(f"could not fetch generated image from ComfyUI: {e}") from e

        return GenerationJob(
            id=job_id, status=JobStatus.DONE, kind=meta["kind"], prompt=meta["prompt"], result_path=dest,
        )

    def wait(self, job_id: str, timeout_seconds: float = 180.0, poll_interval: float = 1.0) -> GenerationJob:
        """Convenience for scripts/tests: block until DONE or ERROR. The
        async job model (submit + poll status) remains the real API surface
        an agent uses via MCP; this just saves callers from writing their
        own poll loop when synchronous waiting is genuinely what they want.
        """
        deadline = time.time() + timeout_seconds
        while True:
            job = self.status(job_id)
            if job.status in (JobStatus.DONE, JobStatus.ERROR):
                return job
            if time.time() > deadline:
                raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds}s")
            time.sleep(poll_interval)
