"""The one function in this codebase allowed to call an LLM provider
(ARCHITECTURE.md Section 4: "ai/ is isolated ... this makes 'did we
accidentally send raw data to a third-party API' a one-directory audit").

Only ever receives the system prompt and user prompt built by
`ai.prompting` -- never raw source payloads, never direct database access.
"""

import os

from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def generate(system_prompt: str, user_prompt: str) -> str:
    client = _get_client()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    return content or ""
