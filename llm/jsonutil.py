"""Tolerant JSON extraction (V13 M6 judge-robustness ladder, moved from engine/director.py)."""
from __future__ import annotations

import json
import re


def extract_json(text: str):
    """Fenced, prose-wrapped, trailing-comma JSON -> parsed object, else None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        for cand in (m.group(), re.sub(r",\s*([}\]])", r"\1", m.group())):
            try:
                return json.loads(cand)
            except Exception:
                pass
    m2 = re.search(r"\{[^{}]*\}", text, re.S)
    if m2:
        try:
            return json.loads(m2.group())
        except Exception:
            pass
    return None
