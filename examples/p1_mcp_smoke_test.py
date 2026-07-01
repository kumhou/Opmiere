"""P1 proof: a real MCP client drives the Opmiere MCP server end-to-end.

This is the actual "no GUI" pathway: launches mcp_server.py as a subprocess over
stdio (exactly how Claude Desktop/Cursor/Claude Code would), and calls tools in
sequence to build a timeline and export a real file - printing every raw
CallToolResult so success is read back, never assumed.

Run:  python examples/p1_mcp_smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

WORKDIR = Path(__file__).resolve().parent / "_p1_mcp_run"
FPS = 30


def make_sample(path: Path, pattern: str, freq: int, seconds: float) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"{pattern}=size=320x180:rate={FPS}:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)


def show(label: str, result) -> dict | None:
    """Print the raw tool result and return the parsed JSON payload, if any.

    Observed live: FastMCP leaves structuredContent=None for plain-dict-returning
    tools here; the real payload is JSON text in content[0]. Parse that instead
    of assuming structuredContent is populated.
    """
    print(f"\n--- {label} ---")
    print("isError:", result.isError)
    parsed = None
    for block in result.content:
        text = getattr(block, "text", None)
        print("content:", text if text is not None else block)
        if text is not None and parsed is None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
    return parsed


async def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    src_a = WORKDIR / "a.mp4"
    make_sample(src_a, "testsrc2", 440, 2)

    params = StdioServerParameters(command=sys.executable, args=["-m", "opmiere.mcp_server"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("Connected to MCP server:", init.serverInfo.name, init.serverInfo.version)

            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools])

            show("create_project", await session.call_tool(
                "create_project",
                {"bundle_path": str(WORKDIR / "demo.opm"), "fps": FPS, "width": 320, "height": 180},
            ))

            media = show("import_media", await session.call_tool(
                "import_media", {"src_path": str(src_a), "kind": "video"}
            ))
            media_id = media["id"]

            track = show("add_track", await session.call_tool("add_track", {"kind": "video"}))
            track_id = track["id"]

            show("add_clip", await session.call_tool(
                "add_clip",
                {"track_id": track_id, "media_id": media_id, "start": 0, "src_in": 0, "src_out": 40},
            ))

            show("get_project_state", await session.call_tool("get_project_state", {}))

            show("export", await session.call_tool(
                "export", {"output_path": str(WORKDIR / "output.mp4")}
            ))


if __name__ == "__main__":
    asyncio.run(main())
