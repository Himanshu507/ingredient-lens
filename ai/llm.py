"""The one module in this codebase allowed to call an LLM provider
(ARCHITECTURE.md Section 4: "ai/ is isolated ... this makes 'did we
accidentally send raw data to a third-party API' a one-directory audit").

`generate_with_tools` is the tool-calling entry point `ai.answer.ask` uses:
the model is given a `search_evidence` tool (defined in `ai.answer`) and
decides for itself what to search for and how many times, rather than being
handed a single fixed evidence block. Still never touches raw source
payloads or the database directly -- the tool it's given is a bounded,
read-only search function, executed by `ai.answer`, not by the model.
"""

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class CompletionResult:
    content: str | None
    tool_calls: list[ToolCall]


def generate_with_tools(
    messages: list[dict[str, Any]], *, tools: list[dict[str, Any]]
) -> CompletionResult:
    """One turn of a tool-calling conversation. The caller (`ai.answer.ask`)
    owns the loop: appends this result to `messages`, executes any tool
    calls itself, appends the tool results, and calls again until the model
    responds with plain content instead of a tool call.
    """
    client = _get_client()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        temperature=0,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    message = response.choices[0].message
    tool_calls = [
        ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments))
        for tc in (message.tool_calls or [])
    ]
    return CompletionResult(content=message.content, tool_calls=tool_calls)
