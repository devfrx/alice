"""O.M.N.I.A. — LLM service for OpenAI-compatible APIs."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.thinking_parser import ThinkTagParser


def normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw DB message dicts into OpenAI-compatible message format.

    Handles assistant messages with ``tool_calls``, tool-role messages with
    ``tool_call_id``, and plain user/system/assistant messages.  Items
    without tool-specific keys pass through unchanged (backward compatible).

    Args:
        history: List of message dicts, typically from the DB with keys
            ``role``, ``content``, and optionally ``tool_calls`` /
            ``tool_call_id``.

    Returns:
        List of dicts ready for the OpenAI chat completions API.
    """
    normalized: list[dict[str, Any]] = []
    if not history:
        return normalized
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role in ("user", "system"):
            normalized.append({"role": role, "content": content})
        elif role == "assistant":
            tc = msg.get("tool_calls")
            if tc:
                normalized.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": tc,
                })
            else:
                normalized.append({"role": "assistant", "content": content})
        elif role == "tool":
            entry: dict[str, Any] = {"role": "tool", "content": content}
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            normalized.append(entry)
        else:
            normalized.append({"role": role, "content": content})

    return normalized


class LLMService:
    """Communicate with any OpenAI-compatible API (LM Studio, Ollama, etc.).

    Args:
        config: The ``LLMConfig`` holding provider URL, model name, etc.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(timeout=config.timeout)
        self._system_prompt: str | None = None

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        """Read the system prompt from the configured file path.

        Returns:
            The system prompt text.

        Raises:
            FileNotFoundError: If the configured system prompt file is missing.
        """
        if self._system_prompt is not None:
            return self._system_prompt

        path = Path(self._config.system_prompt_file)
        if not path.exists():
            raise FileNotFoundError(
                f"System prompt file not found: {path}"
            )

        self._system_prompt = path.read_text(encoding="utf-8").strip()
        logger.debug("Loaded system prompt from {}", path)
        return self._system_prompt

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build a full message list with system prompt, history, and user msg.

        Args:
            user_content: The new user message text.
            history: Optional prior messages to include.
            attachments: Optional list of dicts with ``file_path`` (absolute)
                and ``content_type`` keys for vision-model image inputs.

        Returns:
            A list of message dicts ready for the chat completions API.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._load_system_prompt()},
        ]
        if history:
            messages.extend(normalize_history(history))

        # Build the user message — multimodal when vision attachments exist.
        if attachments and self._config.supports_vision:
            content_parts: list[dict[str, Any]] = [
                {"type": "text", "text": user_content},
            ]
            for att in attachments:
                image_bytes = (
                    att["_bytes"]
                    if "_bytes" in att
                    else Path(att["file_path"]).read_bytes()
                )
                b64 = base64.b64encode(image_bytes).decode("ascii")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{att['content_type']};base64,{b64}",
                        },
                    }
                )
            messages.append({"role": "user", "content": content_parts})
            logger.debug(
                "Built multimodal message with {} image(s)", len(attachments)
            )
        else:
            messages.append({"role": "user", "content": user_content})

        return messages

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build messages for tool-loop continuation (no new user message).

        Used when the LLM needs to be re-queried after tool execution.
        The history already contains the user message, assistant tool_calls,
        and tool results, so no additional user message is appended.

        Args:
            history: Full conversation history including tool messages.

        Returns:
            A list of message dicts: system prompt + normalized history.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._load_system_prompt()},
        ]
        if history:
            messages.extend(normalize_history(history))
        return messages

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion via SSE.

        Sends a POST to ``{base_url}/v1/chat/completions`` with
        ``stream=True`` and yields parsed event dicts.

        Yields:
            Dicts with a ``type`` key:
            - ``{"type": "token", "content": "..."}``
            - ``{"type": "thinking", "content": "..."}``  (reasoning models)
            - ``{"type": "tool_call", "id": "...", "function": {...}}``
            - ``{"type": "done"}``
        """
        url = f"{self._config.base_url}/v1/chat/completions"

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # Accumulator for tool calls that arrive across multiple chunks.
        # Keyed by index (int) -> {"id": str, "name": str, "arguments": str}
        tool_calls_acc: dict[int, dict[str, str]] = {}

        # Inline <think> tag parser for models that embed reasoning in content.
        think_parser: ThinkTagParser | None = (
            ThinkTagParser() if self._config.supports_thinking else None
        )

        async with self._client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()

            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[len("data: "):]

                if data_str == "[DONE]":
                    # Flush thinking parser leftovers.
                    if think_parser:
                        for kind, text in think_parser.flush():
                            yield {
                                "type": "thinking" if kind == "thinking" else "token",
                                "content": text,
                            }
                    # Flush any accumulated tool calls before finishing.
                    for _idx in sorted(tool_calls_acc):
                        tc = tool_calls_acc[_idx]
                        yield {
                            "type": "tool_call",
                            "id": tc["id"],
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                    yield {"type": "done"}
                    return

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed SSE chunk: {}", data_str)
                    continue

                choices = chunk.get("choices")
                if not choices:
                    continue

                delta = choices[0].get("delta", {})

                # --- explicit reasoning_content (Ollama/OpenAI extension) ---
                if self._config.supports_thinking:
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield {"type": "thinking", "content": reasoning}

                # --- content token (may contain inline <think> tags) ---
                content = delta.get("content")
                if content:
                    if think_parser:
                        for kind, text in think_parser.feed(content):
                            yield {
                                "type": "thinking" if kind == "thinking" else "token",
                                "content": text,
                            }
                    else:
                        yield {"type": "token", "content": content}

                # --- tool calls (streamed in pieces) ---
                for tc_delta in delta.get("tool_calls", []):
                    idx: int = tc_delta.get("index", 0)

                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }

                    if tc_delta.get("id"):
                        tool_calls_acc[idx]["id"] = tc_delta["id"]

                    func = tc_delta.get("function", {})
                    if func.get("name"):
                        tool_calls_acc[idx]["name"] = func["name"]
                    if func.get("arguments"):
                        tool_calls_acc[idx]["arguments"] += func["arguments"]

        # If stream ended without [DONE], flush anyway.
        if think_parser:
            for kind, text in think_parser.flush():
                yield {
                    "type": "thinking" if kind == "thinking" else "token",
                    "content": text,
                }
        for _idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[_idx]
            yield {
                "type": "tool_call",
                "id": tc["id"],
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Non-streaming chat
    # ------------------------------------------------------------------

    async def chat_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a non-streaming chat completion request.

        Args:
            messages: The full list of messages.
            tools: Optional tool definitions.

        Returns:
            The raw JSON response dict from the API.
        """
        url = f"{self._config.base_url}/v1/chat/completions"

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
        logger.debug("LLMService httpx client closed")
