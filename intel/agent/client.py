"""
Anthropic client singleton + agentic tool-loop helper.

Key design choices:
- claude-opus-4-7 with adaptive thinking + effort "high"
- Prompt caching via cache_control on system block (see prompts.py)
- Manual tool-use loop (not tool_runner) so LangGraph nodes keep full control
- Usage tracking so callers can log cache hits to metadata
"""
from __future__ import annotations

import os
from typing import Any

import anthropic

# ── Client singleton ───────────────────────────────────────────────────────────

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Add it to your .env file or export it before running the agent."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# Model constants
MODEL = "claude-opus-4-7"
MAX_TOKENS = 8192       # per-turn cap; increase to 32768 for long briefings


# ── Agentic tool loop ──────────────────────────────────────────────────────────

def run_agent_turn(
    *,
    system: list[dict],
    messages: list[dict],
    tools: list[dict],
    max_iterations: int = 8,
    max_tokens: int = MAX_TOKENS,
    effort: str = "high",
) -> tuple[str, list[dict], dict[str, int]]:
    """
    Run one agentic turn: call Claude, handle all tool_use blocks in a loop,
    and return (final_text, updated_messages, usage_totals).

    Args:
        system:          Cached system block list from prompts.get_cached_system_block()
        messages:        Anthropic messages list (mutated copy is returned)
        tools:           Tool definition dicts from tools.TOOL_DEFINITIONS
        max_iterations:  Safety cap on tool-call rounds
        max_tokens:      Per-turn token cap
        effort:          Anthropic effort level: low | medium | high | max

    Returns:
        final_text:      Last text block from Claude (empty string if only tools ran)
        messages:        Updated message list including assistant + tool result turns
        usage:           Dict with input_tokens, output_tokens, cache_read, cache_write
    """
    from .tools import execute_tool

    client = get_client()
    usage: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    messages = list(messages)  # shallow copy so we don't mutate the caller's list
    final_text = ""

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=system,
            tools=tools if tools else anthropic.NOT_GIVEN,
            messages=messages,
        )

        # Accumulate usage
        u = response.usage
        usage["input_tokens"] += u.input_tokens
        usage["output_tokens"] += u.output_tokens
        usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # Extract any text
        for block in response.content:
            if block.type == "text":
                final_text = block.text  # keep the last text block

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results: list[dict] = []
            for block in response.content:
                if block.type == "tool_use":
                    result_str = execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        }
                    )
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            continue  # next iteration

        # Any other stop reason (max_tokens, etc.) — break
        break

    return final_text, messages, usage


def stream_agent_turn(
    *,
    system: list[dict],
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 16_384,
    effort: str = "high",
):
    """
    Stream a single (no tool-use) Claude response. Yields text chunks.
    Use this for the briefing generator node where we want live output.

    Returns a context manager that exposes .text_stream and .get_final_message().
    """
    client = get_client()
    return client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=system,
        tools=tools if tools else anthropic.NOT_GIVEN,
        messages=messages,
    )
