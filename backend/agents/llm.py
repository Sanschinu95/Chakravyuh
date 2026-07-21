"""Provider-agnostic async LLM layer.

Groq is the default provider (OpenAI-compatible, fast, and what this project
is keyed for); Anthropic is used instead when ANTHROPIC_API_KEY is present and
LLM_PROVIDER is not pinned to groq.

Two rules encoded here, unchanged by the provider swap:

* The LLM never decides anything numeric. Callers pass solver output in and get
  prose or structured labels back. Nothing in this module computes a barrel,
  a price, or a cost.
* Every call degrades. With no key the caller gets None and falls back to a
  deterministic path, tagged so the UI can say so. A missing key must never
  take the demo down.
"""

from __future__ import annotations

import json
from typing import Any

from backend.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GROQ_API_KEY,
    GROQ_FAST_MODEL,
    GROQ_MODEL,
    LLM_PROVIDER,
)

_groq: Any = None
_anthropic: Any = None


def provider() -> str | None:
    """Which provider is actually usable right now."""
    if LLM_PROVIDER == "groq" and GROQ_API_KEY:
        return "groq"
    if LLM_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
        return "anthropic"
    if GROQ_API_KEY:
        return "groq"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def llm_available() -> bool:
    return provider() is not None


def provider_label() -> str:
    p = provider()
    if p == "groq":
        return f"Groq · {GROQ_MODEL}"
    if p == "anthropic":
        return f"Anthropic · {ANTHROPIC_MODEL}"
    return "no LLM configured"


def _groq_client() -> Any:
    global _groq
    if _groq is None:
        from groq import AsyncGroq

        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq


def _anthropic_client() -> Any:
    global _anthropic
    if _anthropic is None:
        from anthropic import AsyncAnthropic

        _anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic


# --------------------------------------------------------------------------
# Prose completion
# --------------------------------------------------------------------------
async def complete(
    system: str,
    user: str,
    max_tokens: int = 2000,
    effort: str = "medium",
    fast: bool = False,
) -> str | None:
    p = provider()
    try:
        if p == "groq":
            client = _groq_client()
            r = await client.chat.completions.create(
                model=GROQ_FAST_MODEL if fast else GROQ_MODEL,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return (r.choices[0].message.content or "").strip() or None

        if p == "anthropic":
            client = _anthropic_client()
            async with client.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                messages=[{"role": "user", "content": user}],
            ) as stream:
                msg = await stream.get_final_message()
            return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the pipeline
        print(f"[llm] completion failed ({p}): {type(exc).__name__}: {exc}")
    return None


# --------------------------------------------------------------------------
# Structured extraction
# --------------------------------------------------------------------------
async def extract(
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
    effort: str = "low",
    fast: bool = True,
) -> dict[str, Any] | None:
    """Schema-guided JSON extraction, parsed defensively."""
    p = provider()
    try:
        if p == "groq":
            client = _groq_client()
            r = await client.chat.completions.create(
                model=GROQ_FAST_MODEL if fast else GROQ_MODEL,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{system}\n\nReturn JSON only, matching this schema "
                            f"exactly. No prose, no markdown fences.\n"
                            f"{json.dumps(schema)}"
                        ),
                    },
                    {"role": "user", "content": user},
                ],
            )
            return _loads(r.choices[0].message.content)

        if p == "anthropic":
            client = _anthropic_client()
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": user}],
            )
            return _loads(next((b.text for b in msg.content if b.type == "text"), None))
    except Exception as exc:  # noqa: BLE001
        print(f"[llm] extraction failed ({p}): {type(exc).__name__}: {exc}")
    return None


def _loads(text: str | None) -> dict[str, Any] | None:
    """Parse JSON that may arrive wrapped in prose or markdown fences."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


# --------------------------------------------------------------------------
# Agentic tool loop
# --------------------------------------------------------------------------
async def tool_loop(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    dispatch: Any,
    max_iterations: int = 8,
    max_tokens: int = 4000,
    effort: str = "high",
) -> dict[str, Any] | None:
    """Let the model actually run tools rather than imagine their results.

    `tools` uses the OpenAI function-calling shape; it is translated for
    Anthropic when that provider is active. `dispatch(name, args) -> str`
    executes one tool.
    """
    p = provider()
    if p is None:
        return None
    trace: list[dict[str, Any]] = []

    try:
        if p == "groq":
            client = _groq_client()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            for _ in range(max_iterations):
                r = await client.chat.completions.create(
                    model=GROQ_MODEL,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice="auto",
                    messages=messages,
                )
                m = r.choices[0].message
                calls = m.tool_calls or []
                messages.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.function.name,
                                      "arguments": c.function.arguments}}
                        for c in calls
                    ] or None,
                })
                if not calls:
                    return {"text": (m.content or "").strip(), "trace": trace}

                for c in calls:
                    args = _loads(c.function.arguments) or {}
                    try:
                        out = await dispatch(c.function.name, args)
                        err = False
                    except Exception as exc:  # noqa: BLE001
                        out, err = f"tool error: {type(exc).__name__}: {exc}", True
                    trace.append({"tool": c.function.name, "input": args,
                                  "result_preview": str(out)[:400], "error": err})
                    messages.append({"role": "tool", "tool_call_id": c.id,
                                     "content": str(out)})
            return {"text": "", "trace": trace, "exhausted": True}

        # -- anthropic ----------------------------------------------------
        client = _anthropic_client()
        atools = [
            {"name": t["function"]["name"],
             "description": t["function"].get("description", ""),
             "input_schema": t["function"]["parameters"]}
            for t in tools
        ]
        amsgs: list[dict[str, Any]] = [{"role": "user", "content": user}]
        for _ in range(max_iterations):
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=max_tokens, system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                tools=atools, messages=amsgs,
            )
            if msg.stop_reason == "refusal":
                return None
            amsgs.append({"role": "assistant", "content": msg.content})
            if msg.stop_reason == "pause_turn":
                continue
            uses = [b for b in msg.content if b.type == "tool_use"]
            if not uses:
                text = "".join(b.text for b in msg.content if b.type == "text")
                return {"text": text.strip(), "trace": trace}
            results = []
            for tu in uses:
                try:
                    out = await dispatch(tu.name, tu.input)
                    err = False
                except Exception as exc:  # noqa: BLE001
                    out, err = f"tool error: {type(exc).__name__}: {exc}", True
                trace.append({"tool": tu.name, "input": tu.input,
                              "result_preview": str(out)[:400], "error": err})
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": str(out), "is_error": err})
            amsgs.append({"role": "user", "content": results})
        return {"text": "", "trace": trace, "exhausted": True}

    except Exception as exc:  # noqa: BLE001
        print(f"[llm] tool loop failed ({p}): {type(exc).__name__}: {exc}")
        return {"text": "", "trace": trace, "error": str(exc)} if trace else None
