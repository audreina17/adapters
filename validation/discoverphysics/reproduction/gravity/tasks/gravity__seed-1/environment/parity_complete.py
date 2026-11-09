#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import anthropic
import openai
from metadata_hook import install, records
install("/tmp/inference-http.jsonl")


def response_text(content: Iterable[Any]) -> str:
    return "".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    )


def openai_complete(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    # Match the pinned upstream llm_client._openai_complete request shape.
    messages = []
    if payload["system"]:
        messages.append({"role": "system", "content": str(payload["system"])})
    messages.extend(payload["messages"])
    response = openai.OpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        timeout=3600.0,
    ).chat.completions.create(
        model=str(payload["model"]),
        messages=messages,
        max_tokens=int(payload["max_tokens"]),
    )
    text = response.choices[0].message.content
    usage = response.usage
    return {
        "text": text,
        "inference_metadata": records,
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "cache_tokens": int(
            getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
            or 0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one pinned upstream-compatible completion."
    )
    parser.add_argument("payload_file", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid completion payload: {exc}") from exc

    provider = payload.get("provider", "anthropic")
    if provider == "openai":
        print(json.dumps(openai_complete(payload)))
        return
    if provider != "anthropic":
        raise SystemExit(f"Unsupported completion provider: {provider}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required")
    response = anthropic.Anthropic(api_key=api_key, timeout=3600.0).messages.create(
        model=str(payload["model"]),
        messages=list(payload["messages"]),
        system=str(payload["system"]),
        max_tokens=int(payload["max_tokens"]),
    )
    usage = response.usage
    text = response_text(response.content)
    if not text:
        raise SystemExit("Anthropic response contained no text block")
    print(
        json.dumps(
            {
                "text": text,
        "inference_metadata": records,
                "input_tokens": int(usage.input_tokens),
                "output_tokens": int(usage.output_tokens),
                "cache_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            }
        )
    )


if __name__ == "__main__":
    main()
