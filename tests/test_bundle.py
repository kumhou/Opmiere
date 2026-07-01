import pytest

from opmiere.bundle import Bundle
from opmiere.model import Project


def test_create_open_save_load_round_trip(tmp_path):
    root = tmp_path / "demo.opm"
    project = Project()
    project.timebase.fps = 25
    bundle = Bundle.create(root, project=project)

    assert bundle.project_path.exists()
    assert bundle.media_dir.is_dir()

    loaded = Bundle.open(root).load()
    assert loaded.id == project.id
    assert loaded.timebase.fps == 25


def test_create_fails_if_already_exists(tmp_path):
    root = tmp_path / "demo.opm"
    Bundle.create(root)
    with pytest.raises(FileExistsError):
        Bundle.create(root)


def test_open_fails_without_project_json(tmp_path):
    root = tmp_path / "not_a_bundle"
    root.mkdir()
    with pytest.raises(FileNotFoundError):
        Bundle.open(root)


def test_import_file_copies_into_media_dir(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("hello", encoding="utf-8")

    bundle = Bundle.create(tmp_path / "demo.opm")
    dest = bundle.import_file(src)

    assert dest == bundle.media_dir / "source.txt"
    assert dest.read_text(encoding="utf-8") == "hello"


def test_import_file_rejects_duplicate_name(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("hello", encoding="utf-8")

    bundle = Bundle.create(tmp_path / "demo.opm")
    bundle.import_file(src)
    with pytest.raises(FileExistsError):
        bundle.import_file(src)
