"""opmiere CLI — doctor, version, thin wrappers for mcp/web."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opmiere",
        description="Opmiere — open agent-native video editor (native CLI)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="Check ffmpeg, Python, extras, ComfyUI")
    p_doc.add_argument("--json", action="store_true", help="Machine-readable report")
    p_doc.add_argument("--no-comfy", action="store_true", help="Skip ComfyUI port check")
    p_doc.add_argument("--comfy-host", default="127.0.0.1")
    p_doc.add_argument("--comfy-port", type=int, default=8188)

    sub.add_parser("version", help="Print package version")

    p_web = sub.add_parser("web", help="Start minimal web GUI (opmiere-web)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8787)

    sub.add_parser("mcp", help="Start MCP server (stdio)")

    args = parser.parse_args(argv)

    if args.cmd == "version":
        from . import __version__
        print(__version__)
        return 0

    if args.cmd == "doctor":
        from .doctor import format_doctor_text, run_doctor
        report = run_doctor(
            comfy_host=args.comfy_host,
            comfy_port=args.comfy_port,
            check_comfy=not args.no_comfy,
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            sys.stdout.write(format_doctor_text(report))
        return 0 if report.get("ok") else 1

    if args.cmd == "web":
        try:
            import uvicorn
        except ImportError:
            print(
                "web extras missing — pip install -e \".[web]\"",
                file=sys.stderr,
            )
            return 2
        from .web.app import app
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
