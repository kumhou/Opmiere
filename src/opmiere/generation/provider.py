"""GenerationProvider: the pluggable interface for generative AI backends.

ARCHITECTURE.md section 4 (design principle 3) and section 5.3/5.7: local
(ComfyUI) and cloud (Replicate/fal/Runway/...) providers all implement this
one interface, so the Editor and MCP layer never know or care which is
actually generating a given asset.

Section 8's async job model: submit() returns a job id immediately; status()
is polled (cheap, non-blocking) until it reports DONE or ERROR. Providers own
translating their own native state into this shared vocabulary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class GenerationJob:
    id: str
    status: JobStatus
    kind: str  # "image" today; "video"/"speech"/"sfx"/"music" in later phases
    prompt: str
    # Set once status == DONE: where the provider left the result file.
    result_path: Path | None = None
    # Set if status == ERROR: what went wrong, for the agent to see verbatim.
    error: str | None = None


class GenerationProvider(ABC):
    """One generation backend. See ComfyUIProvider for the local implementation."""

    name: str

    @abstractmethod
    def submit(self, kind: str, prompt: str, params: dict[str, Any]) -> str:
        """Start a generation job. Returns a job id immediately (non-blocking)."""
        raise NotImplementedError

    @abstractmethod
    def status(self, job_id: str) -> GenerationJob:
        """Poll a job's current state. Cheap; safe to call repeatedly."""
        raise NotImplementedError
