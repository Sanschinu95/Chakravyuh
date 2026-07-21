"""Thin async wrapper around the Anthropic Messages API.

Two rules encoded here:

* The LLM never decides anything numeric. Callers pass solver output in and get
  prose or structured labels back. Nothing in this module computes a barrel,
  a price or a cost.
* Every call degrades. If ANTHROPIC_API_KEY is absent the caller gets a
  deterministic fallback and the payload is tagged so the UI can say so. A
  missing key must never take the demo down.
"""

from __future__ import annotations

import json
from typing import Any

from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_FAST_MODEL, ANTHROPIC_MODEL

try:  # the SDK is a hard dependency, but never let an import kill the app
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover
    AsyncAnthropic = None  # type: ignore[assignment]

_client: Any = None


def llm_available() -> bool:
    return bool(ANTHROPIC_API_KEY) and AsyncAnthropic is not None


def _get_client() -> Any:
    global _client
    if _client is None and llm_available():
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


async def complete(
    system: str,
    user: str,
    max_tokens: int = 2000,
    effort: str = "medium",
    fast: bool = False,
) -> str | None:
    """Prose completion. Returns None if the LLM is unavailable or errors."""
    client = _get_client()
    if client is None:
        return None
    try:
        # Streaming keeps long narrations under the SDK's HTTP timeout.
        async with client.messages.stream(
            model=ANTHROPIC_FAST_MODEL if fast else ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = await stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the pipeline
        print(f"[llm] completion failed: {type(exc).__name__}: {exc}")
        return None


async def extract(
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
    effort: str = "low",
    fast: bool = True,
) -> dict[str, Any] | None:
    """Schema-constrained extraction.

    Uses structured outputs so the response is guaranteed to satisfy `schema`
    rather than hoping the model returns clean JSON. Still parsed defensively.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        msg = await client.messages.create(
            model=ANTHROPIC_FAST_MODEL if fast else ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if not text:
            return None
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[llm] extraction failed: {type(exc).__name__}: {exc}")
        return None


async def tool_loop(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    dispatch: Any,
    max_iterations: int = 8,
    max_tokens: int = 4000,
    effort: str = "high",
) -> dict[str, Any] | None:
    """Agentic tool-use loop.

    `dispatch(name, input) -> str` executes a tool and returns its result. Used
    by the red team agent so Claude can actually run attacks against the
    simulator and LP rather than imagining their effects.

    Returns {"text": final assistant prose, "trace": [...steps]} or None.
    """
    client = _get_client()
    if client is None:
        return None

    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    trace: list[dict[str, Any]] = []

    try:
        for _ in range(max_iterations):
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                tools=tools,
                messages=messages,
            )

            if msg.stop_reason == "refusal":
                return None

            # A server-side tool paused the turn; resend to let it continue.
            if msg.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": msg.content})
                continue

            messages.append({"role": "assistant", "content": msg.content})

            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in msg.content if b.type == "text")
                return {"text": text.strip(), "trace": trace}

            results = []
            for tu in tool_uses:
                try:
                    out = await dispatch(tu.name, tu.input)
                    is_err = False
                except Exception as exc:  # noqa: BLE001
                    out = f"tool error: {type(exc).__name__}: {exc}"
                    is_err = True
                trace.append({"tool": tu.name, "input": tu.input,
                              "result_preview": str(out)[:400], "error": is_err})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": str(out),
                    "is_error": is_err,
                })
            messages.append({"role": "user", "content": results})

        return {"text": "", "trace": trace, "exhausted": True}
    except Exception as exc:  # noqa: BLE001
        print(f"[llm] tool loop failed: {type(exc).__name__}: {exc}")
        return {"text": "", "trace": trace, "error": str(exc)} if trace else None
