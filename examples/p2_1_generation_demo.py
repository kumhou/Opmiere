"""P2.1 proof: a real MCP client drives Opmiere through local AI generation,
end to end - the same "no GUI" pathway proven in P1, now exercising the
generation loop instead of only imported footage.

create_project -> generate(image) -> poll job_status -> place_generated ->
export. Requires a running local ComfyUI server (see generation/comfyui.py)
with the SD1.5 checkpoint installed.

Run:  python examples/p2_1_generation_demo.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

WORKDIR = Path(__file__).resolve().parent / "_p2_1_run"


def show(label: str, result) -> dict | None:
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

    params = StdioServerParameters(command=sys.executable, args=["-m", "opmiere.mcp_server"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("Connected to MCP server:", init.serverInfo.name, init.serverInfo.version)

            show("create_project", await session.call_tool(
                "create_project",
                {"bundle_path": str(WORKDIR / "demo.opm"), "fps": 30, "width": 768, "height": 768},
            ))

            gen_result = await session.call_tool("generate", {
                "kind": "image",
                "prompt": "a cozy mountain cabin covered in snow at dusk, warm light in the windows",
                "params": {"width": 768, "height": 768, "seed": 777},
            })
            print("\n--- generate ---")
            print("isError:", gen_result.isError)
            job_id = gen_result.content[0].text
            print("job_id:", job_id)

            print("\npolling job_status...")
            t0 = time.time()
            while True:
                status = show("job_status", await session.call_tool("job_status", {"job_id": job_id}))
                if status["status"] in ("done", "error"):
                    break
                if time.time() - t0 > 120:
                    raise TimeoutError("generation did not finish in time")
                await asyncio.sleep(1)

            if status["status"] == "error":
                raise RuntimeError(f"generation failed: {status['error']}")

            track = show("add_track", await session.call_tool("add_track", {"kind": "video"}))
            track_id = track["id"]

            clip = show("place_generated", await session.call_tool(
                "place_generated",
                {"job_id": job_id, "track_id": track_id, "start": 0, "duration_frames": 90},
            ))

            show("export", await session.call_tool(
                "export", {"output_path": str(WORKDIR / "output.mp4")}
            ))


if __name__ == "__main__":
    asyncio.run(main())
