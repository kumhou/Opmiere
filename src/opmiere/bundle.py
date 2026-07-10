"""The .opm bundle: a project folder containing project.json + a media/ subfolder.

ARCHITECTURE.md section 3.2 treats the render engine as pluggable and the project
model as the source of truth; this module is the thin persistence layer around that
model — it never touches ffmpeg or any renderer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .model import Project

PROJECT_FILENAME = "project.json"
MEDIA_DIRNAME = "media"
PROXIES_DIRNAME = "proxies"
ANALYSIS_DIRNAME = "analysis"


class Bundle:
    """A .opm project bundle on disk.

    Layout::

        my_film.opm/
            project.json
            media/
                clip1.mp4
                gen_sunrise.png
            proxies/          # optional per-asset scrub proxies
            analysis/         # transcripts, asset cards, …
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def project_path(self) -> Path:
        return self.root / PROJECT_FILENAME

    @property
    def media_dir(self) -> Path:
        return self.root / MEDIA_DIRNAME

    @property
    def proxies_dir(self) -> Path:
        return self.root / PROXIES_DIRNAME

    @property
    def analysis_dir(self) -> Path:
        return self.root / ANALYSIS_DIRNAME

    def resolve_bundle_path(self, relative: str) -> Path:
        """Resolve a path stored relative to the bundle root."""
        return (self.root / relative).resolve()

    # --- lifecycle ----------------------------------------------------
    @classmethod
    def create(cls, root: Path, project: Project | None = None) -> "Bundle":
        """Create a new bundle on disk. Fails if ``root`` already exists."""
        root = Path(root)
        if root.exists():
            raise FileExistsError(f"bundle already exists: {root}")
        root.mkdir(parents=True)
        (root / MEDIA_DIRNAME).mkdir()
        bundle = cls(root)
        bundle.save(project if project is not None else Project())
        return bundle

    @classmethod
    def open(cls, root: Path) -> "Bundle":
        root = Path(root)
        bundle = cls(root)
        if not bundle.project_path.exists():
            raise FileNotFoundError(f"not an opmiere bundle (no project.json): {root}")
        return bundle

    # --- project.json ---------------------------------------------------
    def load(self) -> Project:
        data = json.loads(self.project_path.read_text(encoding="utf-8"))
        return Project.from_dict(data)

    def save(self, project: Project) -> None:
        self.media_dir.mkdir(exist_ok=True)
        self.project_path.write_text(
            json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- media files ------------------------------------------------------
    def import_file(self, src_path: Path, dest_name: str | None = None) -> Path:
        """Copy an external file into media/ and return its path inside the bundle."""
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        self.media_dir.mkdir(exist_ok=True)
        dest = self.media_dir / (dest_name or src_path.name)
        if dest.exists():
            raise FileExistsError(f"media file already exists in bundle: {dest}")
        shutil.copy2(src_path, dest)
        return dest

    def media_path(self, relative_path: str) -> Path:
        """Resolve a Media.path (relative to media/) to an absolute filesystem path."""
        return self.media_dir / relative_path
