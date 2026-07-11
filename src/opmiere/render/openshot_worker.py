"""OpenShot embed worker process (JSON-lines on stdio).

Run: ``python -m opmiere.render.openshot_worker``

Host sends one JSON object per line; worker replies with one JSON line.
Commands: ping | version | frame_media | frame_timeline | frame_project | quit
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    # Import after path fix — runtime embeds MinGW python inside this process
    from .openshot_runtime import OpenShotRuntime, default_openshot_home

    home = default_openshot_home()
    if home is None:
        print(json.dumps({"ok": False, "error": "OpenShot not installed"}), flush=True)
        return 2
    try:
        rt = OpenShotRuntime(home)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"init failed: {e}"}), flush=True)
        return 3

    # ready line
    print(json.dumps({"ok": True, "event": "ready", "home": str(home)}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"bad json: {e}"}), flush=True)
            continue
        cmd = msg.get("cmd")
        try:
            if cmd == "quit":
                print(json.dumps({"ok": True, "event": "bye"}), flush=True)
                break
            if cmd == "ping":
                print(json.dumps({"ok": True, "pong": True}), flush=True)
                continue
            if cmd == "version":
                print(json.dumps(rt.version()), flush=True)
                continue
            if cmd == "frame_media":
                r = rt.frame_from_media(
                    msg["media_path"],
                    float(msg.get("time_seconds", 0)),
                    msg["output_path"],
                    fps=msg.get("fps"),
                )
                print(json.dumps(r), flush=True)
                continue
            if cmd == "frame_timeline":
                r = rt.frame_from_timeline_clip(
                    msg["media_path"],
                    float(msg.get("time_seconds", 0)),
                    msg["output_path"],
                    width=int(msg.get("width", 640)),
                    height=int(msg.get("height", 360)),
                    fps=float(msg.get("fps", 30)),
                    clip_start=float(msg.get("clip_start", 0)),
                    clip_end=msg.get("clip_end"),
                )
                print(json.dumps(r), flush=True)
                continue
            if cmd == "frame_project":
                r = rt.frame_from_project(
                    msg["plan"],
                    float(msg.get("time_seconds", 0)),
                    msg["output_path"],
                )
                print(json.dumps(r), flush=True)
                continue
            print(json.dumps({"ok": False, "error": f"unknown cmd: {cmd}"}), flush=True)
        except Exception as e:
            print(json.dumps({"ok": False, "error": repr(e)}), flush=True)

    try:
        rt.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
