"""OpenAI backend for the extractor, behind the Anthropic-shaped ``messages.create``.

The extractor builds Anthropic-style requests (system blocks, image/text/
tool_result content, a forced tool call) and reads Anthropic-style responses
(``content`` blocks of type ``tool_use``, ``stop_reason``, ``usage``). This
adapter translates both ways so the extractor's repair retry, low-confidence
re-query, caching and token ledger run unchanged on OpenAI.

Uses the **Responses API**: ``gpt-6-astra`` rejects function tools combined with
reasoning on Chat Completions ("use /v1/responses or set reasoning_effort to
'none'"), and reasoning is what we want for reading drawings. The tool is NON-strict:
strict mode rejects ``DrawingData``'s schema (CLAUDE.md rule 10). If a forced
``tool_choice`` is rejected, the call is retried once with ``auto`` plus an explicit
instruction to call the tool.

Reasoning effort: ``OPENAI_REASONING_EFFORT`` (none|minimal|low|medium|high|xhigh);
unset = the model's default.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

from utils.logger import get_logger

log = get_logger()

_NUDGE = "Respond ONLY by calling the {name} tool."


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "name": t["name"], "description": t.get("description", ""),
         "parameters": t["input_schema"], "strict": False}
        for t in tools
    ]


def _convert_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic-style messages -> Responses ``input`` items."""
    items: list[dict[str, Any]] = []
    pending: list[str] = []  # function call ids awaiting an output item

    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            kind = "output_text" if m["role"] == "assistant" else "input_text"
            items.append({"role": m["role"], "content": [{"type": kind, "text": content}]})
            continue

        if m["role"] == "assistant":
            pending = []
            for b in content:
                t = getattr(b, "type", None)
                if t == "openai_raw":      # reasoning / message items, replayed verbatim
                    items.append(b.item)
                elif t == "tool_use":
                    # The raw function_call item (carrying its server id) was already
                    # replayed above; only synthesize one if it wasn't kept.
                    if not any(i.get("call_id") == b.id for i in items):
                        items.append({"type": "function_call", "call_id": b.id, "name": b.name,
                                      "arguments": json.dumps(b.input)})
                    pending.append(b.id)
            continue

        # user turn. Every function_call needs an output item. Anthropic lets a user
        # turn skip the tool_result (the multi-view re-query does); answer with a stub.
        answered = {b.get("tool_use_id") for b in content if b.get("type") == "tool_result"}
        for call_id in pending:
            if call_id not in answered:
                items.append({"type": "function_call_output", "call_id": call_id, "output": "Received."})
        pending = []
        parts: list[dict[str, Any]] = []
        for b in content:
            kind = b.get("type")
            if kind == "tool_result":
                body = b.get("content", "")
                if b.get("is_error"):
                    body = f"ERROR: {body}"
                items.append({"type": "function_call_output", "call_id": b["tool_use_id"],
                              "output": body})
            elif kind == "image":
                src = b["source"]
                parts.append({"type": "input_image",
                              "image_url": f"data:{src['media_type']};base64,{src['data']}"})
            elif kind == "text":
                parts.append({"type": "input_text", "text": b["text"]})
        if parts:
            items.append({"role": "user", "content": parts})
    return items


def _system_text(system: Any) -> str:
    if not system or isinstance(system, str):
        return system or ""
    return "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")


def _convert_response(resp: Any) -> Any:
    blocks: list[Any] = []
    refusal = None
    has_call = False
    for item in resp.output:
        t = item.type
        if t == "function_call":
            has_call = True
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__unparseable_arguments__": item.arguments}
            blocks.append(SimpleNamespace(type="openai_raw", item=item.model_dump(exclude_none=True)))
            blocks.append(SimpleNamespace(type="tool_use", id=item.call_id, name=item.name, input=args))
        elif t == "message":
            for c in item.content:
                if getattr(c, "type", None) == "refusal":
                    refusal = c.refusal
                elif getattr(c, "type", None) == "output_text":
                    blocks.append(SimpleNamespace(type="text", text=c.text))
        elif t == "reasoning":
            blocks.append(SimpleNamespace(type="openai_raw", item=item.model_dump(exclude_none=True)))

    incomplete = getattr(resp, "incomplete_details", None)
    reason = getattr(incomplete, "reason", None)
    stop = ("refusal" if refusal or reason == "content_filter"
            else "tool_use" if has_call
            else "max_tokens" if reason == "max_output_tokens" else "end_turn")
    # usage stays the raw object: token_tracker.normalize_usage reads input_tokens /
    # output_tokens / input_tokens_details.cached_tokens.
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=resp.usage, stop_details=refusal, id=getattr(resp, "id", None))


class _Messages:
    def __init__(self, client: Any):
        self._client = client

    def create(self, *, model: str, max_tokens: int, system: Any, messages: list,
               tools: list, tool_choice: dict[str, Any], **_ignored: Any) -> Any:
        import openai  # lazy: module imports without the package present

        tool_name = tool_choice["name"]
        kwargs: dict[str, Any] = dict(
            model=model,
            instructions=_system_text(system),
            input=_convert_input(messages),
            tools=_to_openai_tools(tools),
            max_output_tokens=max_tokens,
        )
        effort = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip().lower()
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        try:
            resp = self._client.responses.create(
                tool_choice={"type": "function", "name": tool_name}, **kwargs)
        except openai.BadRequestError as e:
            if "tool_choice" not in str(e).lower():
                raise
            log.warning("%s rejected forced tool_choice; retrying with auto.", model)
            kwargs["input"].append({"role": "user", "content": [
                {"type": "input_text", "text": _NUDGE.format(name=tool_name)}]})
            resp = self._client.responses.create(tool_choice="auto", **kwargs)
        return _convert_response(resp)


class OpenAIAnthropicShim:
    """``client.messages.create(...)`` with Anthropic-style args, served by OpenAI."""

    def __init__(self, api_key: str, max_retries: int):
        import openai

        self._client = openai.OpenAI(api_key=api_key, max_retries=max_retries)
        self.messages = _Messages(self._client)
