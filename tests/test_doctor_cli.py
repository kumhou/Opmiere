"""doctor + CLI — no network, optional ffmpeg (usually present in CI/dev)."""

from __future__ import annotations

import json
import subprocess
import sys

from opmiere.cli import main as cli_main
from opmiere.doctor import format_doctor_text, run_doctor


def test_run_doctor_structure():
    report = run_doctor(check_comfy=False)
    assert "ok" in report
    assert "checks" in report
    assert "version" in report
    ids = {c["id"] for c in report["checks"]}
    assert "python" in ids
    assert "opmiere" in ids
    assert "ffmpeg" in ids
    text = format_doctor_text(report)
    assert "Opmiere doctor" in text
    assert "python" in text


def test_cli_version(capsys):
    code = cli_main(["version"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out  # non-empty version


def test_cli_doctor_json(capsys):
    code = cli_main(["doctor", "--json", "--no-comfy"])
    # 0 if ffmpeg ok, 1 if not — both valid; JSON must parse
    assert code in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert "checks" in data


def test_module_entrypoint_version():
    proc = subprocess.run(
        [sys.executable, "-m", "opmiere.cli", "version"],
        capture_output=True, text=True, check=True,
    )
    assert proc.stdout.strip()
