"""genie_box.py - "Ask about these facilities" powered by a Genie space.

Genie is text-to-SQL over the curated Unity Catalog tables - which is what it is
actually good at (analytical questions like counts / which-has-the-most), unlike
per-card narration. Returns the answer text, or None if Genie couldn't answer
(the caller then shows a gentle hint). Caches by (context, question) so Streamlit
re-runs don't re-ask.

Config: GENIE_SPACE_ID (the same space already set in app.yaml).
"""

from __future__ import annotations

import os
from datetime import timedelta

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID")
GENIE_TIMEOUT = timedelta(seconds=int(os.environ.get("GENIE_TIMEOUT_S", "40")))

_cache: dict[tuple, str | None] = {}
_w = None


def _client():
    global _w
    if _w is None:
        from databricks.sdk import WorkspaceClient
        _w = WorkspaceClient()
    return _w


def ask(question: str, context: str = "") -> str | None:
    """Send a natural-language data question to Genie; return its answer text."""
    if not GENIE_SPACE_ID:
        print("[genie_box] GENIE_SPACE_ID not set")
        return None

    key = (context, question)
    if key in _cache:
        return _cache[key]

    content = f"{context}\n\n{question}".strip() if context else question
    try:
        resp = _client().genie.start_conversation_and_wait(
            space_id=GENIE_SPACE_ID,
            content=content,
            timeout=GENIE_TIMEOUT,
        )
        parts = []
        for a in (getattr(resp, "attachments", None) or []):
            text_att = getattr(a, "text", None)
            if text_att and getattr(text_att, "content", None):
                parts.append(text_att.content.strip())
        answer = " ".join(p for p in parts if p) or None
    except Exception as e:
        print(f"[genie_box] failed: {type(e).__name__}: {e}")
        answer = None

    _cache[key] = answer
    return answer
