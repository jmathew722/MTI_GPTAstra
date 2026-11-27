"""TEST SCAFFOLDING ONLY: a deterministic stand-in for the model client, used by unit tests and by dry runs that debug the native pipeline without spending
API budget. It is never used for acceptance evidence: every acceptance run that claims a real extraction goes through the configured OpenAI client.

``MockClient(layout)`` answers ``messages.create(...)`` with a tool_use block carrying ``layout`` (a dict valid for ``reverse.refextract.MLayout``) and records
the calls it received, so tests can assert "zero model calls" on a cache hit.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace


class _Messages:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.calls.append(kw)
        layout = self.outer.layout(kw) if callable(self.outer.layout) else self.outer.layout
        blk = SimpleNamespace(type="tool_use", id="toolu_mock", name="report_reference_layout", input=layout)
        usage = SimpleNamespace(input_tokens=self.outer.input_tokens, output_tokens=self.outer.output_tokens, input_tokens_details=SimpleNamespace(cached_tokens=0))
        return SimpleNamespace(content=[blk], stop_reason="tool_use", usage=usage, stop_details=None)


class MockClient:
    def __init__(self, layout, input_tokens: int = 1000, output_tokens: int = 500):
        self.layout = layout
        self.calls: list = []
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.messages = _Messages(self)


def text_items_from_call(kw: dict) -> list[dict]:
    """The T### items the extractor put into the prompt."""
    for m in kw.get("messages", []):
        for b in m.get("content", []):
            if isinstance(b, dict) and b.get("type") == "text" and "TEXT ITEMS:" in b["text"]:
                raw = b["text"].split("TEXT ITEMS:", 1)[1].split("\n", 1)[0]
                return json.loads(raw)
    return []


def scan_layout_for(views: list[dict], material: str = "", notes=None):
    """A layout function: numeric OCR items become linear annotations with the OCR string (deterministic, obviously a mock); the given views are used as is."""
    def build(kw):
        items = text_items_from_call(kw)
        anns = []
        for it in items:
            t = it["text"].strip()
            if re.fullmatch(r"\d*\.\d+|\d+\.\d*", t):
                anns.append({"id": f"A{len(anns) + 1:03d}", "kind": "linear", "text": t, "view_id": "", "ocr_ids": [it["id"]], "required": True})
        return {"sheet": {"projection": "third angle", "units": "inch", "scale_text": "1:2"}, "views": views, "annotations": anns, "notes": notes or [],
                "title_block": {}, "material_text": material}
    return build
