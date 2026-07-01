"""RenderBackend: the pluggable interface between the project model and an engine.

ARCHITECTURE.md section 5.2: FFmpeg is the P0/P1 backend; an interactive backend
(libopenshot/MLT) arrives later for real-time preview. The project model must never
import a concrete backend — only this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..bundle import Bundle
from ..model import Project


class RenderBackend(ABC):
    """Compiles a Project (+ its Bundle's media files) down to an output file."""

    @abstractmethod
    def export(self, project: Project, bundle: Bundle, output_path: Path) -> Path:
        """Render the full timeline to ``output_path``. Returns the written path."""
        raise NotImplementedError
