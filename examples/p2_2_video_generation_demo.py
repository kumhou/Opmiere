"""P2.2 proof: local AI *video* generation through the real MCP path, end to
end - create_project -> generate(video) -> poll job_status -> place_generated
-> export. Same pattern as p2_1 (image), now with LTX-Video instead of SD1.5.

The project's fps is set to 25 to match the generated video's frame_rate -
import_media's existing fps-match check (P0) applies to generated video
clips exactly like imported footage, and would reject a mismatch rather
than silently misplacing frames.

Run:  python examples/p2_2_video_generation_demo.py
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

WORKDIR = Path(__file__).resolve().parent / "_p2_2_run"
FPS = 25


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
                {"bundle_path": str(WORKDIR / "demo.opm"), "fps": FPS, "width": 512, "height": 320},
            ))

            gen_result = await session.call_tool("generate", {
                "kind": "video",
                "prompt": "a paper boat floating down a gentle stream, sunlight sparkling on the water, "
                          "gentle camera drift, real-life footage, sharp focus",
                "params": {"width": 512, "height": 320, "num_frames": 65, "frame_rate": FPS, "seed": 2026},
            })
            print("\n--- generate ---")
            print("isError:", gen_result.isError)
            job_id = gen_result.content[0].text
            print("job_id:", job_id)

            print("\npolling job_status (video generation takes longer than image)...")
            t0 = time.time()
            while True:
                status = show("job_status", await session.call_tool("job_status", {"job_id": job_id}))
                if status["status"] in ("done", "error"):
                    break
                if time.time() - t0 > 180:
                    raise TimeoutError("generation did not finish in time")
                await asyncio.sleep(2)

            if status["status"] == "error":
                raise RuntimeError(f"generation failed: {status['error']}")

            track = show("add_track", await session.call_tool("add_track", {"kind": "video"}))
            track_id = track["id"]

            clip = show("place_generated", await session.call_tool(
                "place_generated",
                {"job_id": job_id, "track_id": track_id, "start": 0, "duration_frames": 65},
            ))

            show("export", await session.call_tool(
                "export", {"output_path": str(WORKDIR / "output.mp4")}
            ))


if __name__ == "__main__":
    asyncio.run(main())
