"""Transcript cache + keyword search for project media.

Not embedding ML — ranked substring / token hits with timestamps so agents
can answer “找到我说但是” without re-running Whisper every time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__all__ = [
    "transcript_cache_path",
    "save_transcript",
    "load_transcript",
    "search_segments",
    "search_transcript_dict",
]


def transcript_cache_path(analysis_dir: Path, media_id: str) -> Path:
    safe = re.sub(r"[^\w\-]+", "_", media_id)
    return Path(analysis_dir) / "transcripts" / f"{safe}.json"


def save_transcript(
    analysis_dir: Path,
    media_id: str,
    transcript: dict[str, Any],
) -> Path:
    path = transcript_cache_path(analysis_dir, media_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "media_id": media_id,
        **transcript,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(analysis_dir: Path, media_id: str) -> dict[str, Any] | None:
    path = transcript_cache_path(analysis_dir, media_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _tokens(q: str) -> list[str]:
    q = (q or "").strip().lower()
    if not q:
        return []
    # Keep CJK runs as tokens; split latin on non-alnum
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9']+", q)
    return [p for p in parts if p]


def search_segments(
    query: str,
    segments: list[dict[str, Any]],
    *,
    max_hits: int = 20,
) -> dict[str, Any]:
    """Rank segments (and words when present) matching ``query``."""
    tokens = _tokens(query)
    raw_q = (query or "").strip().lower()
    if not tokens and not raw_q:
        return {"query": query, "hits": [], "hit_count": 0}

    hits: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        text = str(seg.get("text") or "").strip()
        text_l = text.lower()
        score = 0.0
        matched: list[str] = []
        if raw_q and raw_q in text_l:
            score += 5.0 + min(3.0, len(raw_q) / 10.0)
            matched.append(raw_q)
        for tok in tokens:
            if tok in text_l:
                score += 2.0
                matched.append(tok)
        # word-level precision hits
        word_hits: list[dict[str, Any]] = []
        for w in seg.get("words") or []:
            ww = str(w.get("word") or "").strip()
            wl = ww.lower()
            wscore = 0.0
            if raw_q and raw_q in wl:
                wscore += 4.0
            for tok in tokens:
                if tok == wl or tok in wl:
                    wscore += 3.0
            if wscore > 0:
                word_hits.append({
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "word": ww,
                    "score": wscore,
                })
                score += wscore * 0.5
        if score > 0:
            hits.append({
                "segment_index": i,
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": text,
                "score": round(score, 3),
                "matched": sorted(set(matched)),
                "word_hits": sorted(word_hits, key=lambda x: -x["score"])[:8],
            })

    hits.sort(key=lambda h: (-h["score"], h["start"]))
    hits = hits[: max(1, int(max_hits))]
    return {
        "query": query,
        "tokens": tokens,
        "hits": hits,
        "hit_count": len(hits),
        "agent_note": (
            "Keyword/substring ranking (not embeddings). "
            "Use hit start/end seconds to seek or trim."
        ),
    }


def search_transcript_dict(
    query: str,
    transcript: dict[str, Any],
    *,
    max_hits: int = 20,
) -> dict[str, Any]:
    segs = transcript.get("segments") or []
    result = search_segments(query, segs, max_hits=max_hits)
    result["media_id"] = transcript.get("media_id")
    result["path"] = transcript.get("path")
    result["language"] = transcript.get("language")
    return result
