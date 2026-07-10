"""Filler-word cut suggestions from word-level transcripts.

Deterministic lexicon + timestamps — not freeform LLM guessing. Agent reviews
the plan then applies keep ranges (or dry-runs first).
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "DEFAULT_FILLER_WORDS",
    "FILLER_EN",
    "FILLER_ZH",
    "normalize_token",
    "suggest_filler_cuts_from_segments",
    "ranges_to_keep",
]

# English spoken fillers (whole tokens / short phrases matched after normalize)
FILLER_EN: frozenset[str] = frozenset({
    "um", "uh", "uhm", "erm", "er", "ah", "hmm", "mm", "mhm",
    "like", "basically", "actually", "literally", "right",
    "you know", "i mean", "kind of", "sort of", "you see",
})

# Chinese / CJK discourse fillers (substring-friendly tokens)
FILLER_ZH: frozenset[str] = frozenset({
    "那个", "就是", "然后", "嗯", "啊", "呃", "额", "这个",
    "就是说", "对吧", "怎么说", "反正", "其实", "那么",
    "嗯嗯", "啊啊", "那个什么",
})

DEFAULT_FILLER_WORDS: frozenset[str] = FILLER_EN | FILLER_ZH

_PUNCT = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)


def normalize_token(text: str) -> str:
    t = (text or "").strip().lower()
    t = _PUNCT.sub("", t)
    # collapse internal whitespace for multi-word fillers
    t = re.sub(r"\s+", " ", t)
    return t


def _is_filler(token: str, lexicon: set[str]) -> bool:
    n = normalize_token(token)
    if not n:
        return False
    if n in lexicon:
        return True
    # CJK single-token exact; also allow lexicon entry as whole token match only
    return False


def _iter_words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten segments to word dicts {start, end, word}. Fall back to whole segment."""
    words: list[dict[str, Any]] = []
    for seg in segments:
        wlist = seg.get("words")
        if wlist:
            for w in wlist:
                words.append({
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "word": str(w.get("word") or w.get("text") or ""),
                })
        else:
            text = str(seg.get("text") or "").strip()
            if text:
                words.append({
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "word": text,
                })
    words.sort(key=lambda w: w["start"])
    return words


def suggest_filler_cuts_from_segments(
    segments: list[dict[str, Any]],
    *,
    duration_seconds: float | None = None,
    extra_words: list[str] | None = None,
    pad_seconds: float = 0.02,
    min_cut_seconds: float = 0.05,
    merge_gap_seconds: float = 0.12,
) -> dict[str, Any]:
    """From ASR segments (prefer word timestamps), list filler cut ranges.

    Returns cut_ranges + keep_ranges in seconds over the media timeline.
    """
    lexicon = set(DEFAULT_FILLER_WORDS)
    if extra_words:
        lexicon |= {normalize_token(w) for w in extra_words if normalize_token(w)}

    words = _iter_words(segments)
    raw_cuts: list[dict[str, Any]] = []
    for w in words:
        if _is_filler(w["word"], lexicon):
            raw_cuts.append({
                "start": float(w["start"]),
                "end": float(w["end"]),
                "word": w["word"],
                "normalized": normalize_token(w["word"]),
            })

    # merge nearby filler islands
    cut_ranges: list[dict[str, Any]] = []
    for c in raw_cuts:
        if not cut_ranges:
            cut_ranges.append({
                "start": c["start"],
                "end": c["end"],
                "words": [c["word"]],
            })
            continue
        prev = cut_ranges[-1]
        if c["start"] - prev["end"] <= merge_gap_seconds:
            prev["end"] = max(prev["end"], c["end"])
            prev["words"].append(c["word"])
        else:
            cut_ranges.append({
                "start": c["start"],
                "end": c["end"],
                "words": [c["word"]],
            })

    # pad + filter short
    padded: list[dict[str, Any]] = []
    for c in cut_ranges:
        s = max(0.0, c["start"] - pad_seconds)
        e = c["end"] + pad_seconds
        if e - s >= min_cut_seconds:
            padded.append({
                "start": round(s, 3),
                "end": round(e, 3),
                "duration": round(e - s, 3),
                "words": c["words"],
            })

    if duration_seconds is None:
        if words:
            duration_seconds = max(w["end"] for w in words)
        elif segments:
            duration_seconds = max(float(s["end"]) for s in segments)
        else:
            duration_seconds = 0.0

    keep = ranges_to_keep(padded, float(duration_seconds))
    return {
        "duration_seconds": round(float(duration_seconds), 3),
        "filler_count": sum(len(c.get("words") or []) for c in padded),
        "cut_ranges": padded,
        "keep_ranges": keep,
        "lexicon_size": len(lexicon),
        "word_count": len(words),
        "agent_note": (
            "Review cut_ranges before apply_keep_ranges / apply_filler_cuts. "
            "Word-timestamp ASR required for precise fillers; segment-only is coarser."
        ),
    }


def ranges_to_keep(
    cut_ranges: list[dict[str, Any]],
    duration_seconds: float,
    *,
    min_keep_seconds: float = 0.05,
) -> list[dict[str, float]]:
    """Complement of cut_ranges over [0, duration]."""
    if duration_seconds <= 0:
        return []
    cuts = sorted(
        (
            (max(0.0, float(c["start"])), min(duration_seconds, float(c["end"])))
            for c in cut_ranges
        ),
        key=lambda x: x[0],
    )
    # merge overlapping cuts
    merged: list[tuple[float, float]] = []
    for s, e in cuts:
        if e <= s:
            continue
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    keep: list[dict[str, float]] = []
    t = 0.0
    for s, e in merged:
        if s - t >= min_keep_seconds:
            keep.append({
                "start": round(t, 3),
                "end": round(s, 3),
                "duration": round(s - t, 3),
            })
        t = max(t, e)
    if duration_seconds - t >= min_keep_seconds:
        keep.append({
            "start": round(t, 3),
            "end": round(duration_seconds, 3),
            "duration": round(duration_seconds - t, 3),
        })
    return keep
