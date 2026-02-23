"""Shared policy helpers for node refinement selection and validation."""

from __future__ import annotations

import os
import re

DEFAULT_REFINE_MIN_CONTENT_CHARS = 10
MIN_REFINE_MIN_CONTENT_CHARS = 1
MAX_REFINE_MIN_CONTENT_CHARS = 500


def get_refine_min_content_chars() -> int:
    raw = os.getenv("FILESMIND_REFINE_MIN_CONTENT_CHARS")
    if raw is None:
        return DEFAULT_REFINE_MIN_CONTENT_CHARS
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_REFINE_MIN_CONTENT_CHARS
    return max(MIN_REFINE_MIN_CONTENT_CHARS, min(MAX_REFINE_MIN_CONTENT_CHARS, parsed))


def _normalized_text(content: str) -> str:
    return str(content or "").strip()


def should_refine_content(content: str) -> bool:
    text = _normalized_text(content)
    if not text:
        return False
    return len(text) >= get_refine_min_content_chars()


def should_fail_on_empty_refine_result(content: str) -> bool:
    if not should_refine_content(content):
        return False

    text = _normalized_text(content)
    meaningful = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text)
    min_meaningful = max(4, get_refine_min_content_chars() // 2)
    return len(meaningful) >= min_meaningful
