"""Profile a long-ish llama-cpp streaming completion in isolation.

Drives the chat provider directly with a prompt that produces a 100+
token reply so the per-token loop dominates the flame.
Used by profile_core_cells.sh as the Core-Llama-Stream cell.
"""

from __future__ import annotations

import sys

from lilbee.core.services import get_services

_REQUIRED_ARGS = 2  # script name + prompt


def main() -> int:
    if len(sys.argv) < _REQUIRED_ARGS:
        print("usage: probe_llm_stream.py <prompt>", file=sys.stderr)
        return 2
    prompt = sys.argv[1]
    services = get_services()
    provider = services.provider
    messages = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": prompt},
    ]
    stream = provider.chat(messages=messages, stream=True)
    n = 0
    try:
        for _chunk in stream:
            n += 1
            if n % 32 == 0:
                print(".", end="", flush=True)
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    print(f"\nstreamed {n} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
