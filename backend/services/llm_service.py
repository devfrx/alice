"""AL\\CE — LLM service for OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.thinking_parser import ThinkTagParser


def _sanitize_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure every tool_call has valid JSON in ``function.arguments``.

    LLMs may truncate output mid-generation (e.g. hitting max_tokens),
    producing a syntactically broken ``arguments`` string.  If this is
    saved to DB and later replayed in the conversation history, the
    provider API (LM Studio, Ollama, etc.) will return a 500.

    This helper validates each ``arguments`` value and replaces broken
    JSON with ``"{}"`` so the history remains sendable.
    """
    sanitized: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            json.loads(raw_args)
            sanitized.append(tc)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Sanitised malformed tool_call arguments for '{}' "
                "(len={})",
                fn.get("name", "?"),
                len(raw_args) if isinstance(raw_args, str) else 0,
            )
            fixed_tc = {
                **tc,
                "function": {**fn, "arguments": "{}"},
            }
            sanitized.append(fixed_tc)
    return sanitized


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

        # Skip system messages — the system prompt is always added fresh
        # by build_messages() to avoid duplication.
        if role == "system":
            continue

        if role == "user":
            normalized.append({"role": role, "content": content})
        elif role == "assistant":
            tc = msg.get("tool_calls")
            if tc:
                sanitized_tcs = _sanitize_tool_calls(tc)
                normalized.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": sanitized_tcs,
                })
            else:
                normalized.append({"role": "assistant", "content": content})
        elif role == "tool":
            entry: dict[str, Any] = {"role": "tool", "content": content}
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id is not None:
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
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.timeout,
                write=10.0,
                pool=10.0,
            ),
        )
        self._is_ollama = config.provider == "ollama"
        self._system_prompt: str | None = None
        self._response_ids: OrderedDict[str, str] = OrderedDict()
        self._response_ids_max = 500
        # Cache for "auto" model resolution: (resolved_id, resolved_at_monotonic)
        self._auto_model_cache: tuple[str, float] | None = None
        self._auto_model_ttl: float = 30.0  # seconds
        # None = unknown, True = supported, False = not supported
        self._supports_stream_options: bool | None = None

    # ------------------------------------------------------------------
    # Model resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_embedding_model(item: dict[str, Any]) -> bool:
        """Check if a model entry represents an embedding model.

        Checks both the explicit ``type`` field (LM Studio v1 API) and
        the model name/id/path for heuristic detection (OAI-compat API).
        """
        if item.get("type") == "embedding":
            return True
        # Heuristic: check if name/id/path contains "embed"
        for key in ("id", "name", "path"):
            val = item.get(key, "")
            if val and "embed" in val.lower():
                return True
        return False

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    @property
    def supports_vision(self) -> bool:
        """Whether the active model supports multimodal (vision) input."""
        return self._config.supports_vision

    async def _resolve_model(self) -> str:
        """Return the effective model ID to use in API requests.

        When ``config.model`` is ``"auto"``, queries LM Studio (via the
        OAI-compatible ``/v1/models`` endpoint) for the first loaded model
        and caches the result for ``_auto_model_ttl`` seconds.  Falls back to
        ``"auto"`` itself if the query fails so LM Studio chooses for us.

        Returns:
            The resolved model ID string.
        """
        if self._config.model != "auto":
            return self._config.model

        now = time.monotonic()
        if (
            self._auto_model_cache is not None
            and now - self._auto_model_cache[1] < self._auto_model_ttl
        ):
            return self._auto_model_cache[0]

        # Try LM Studio v1 API first, then OAI-compat fallback.
        resolved: str | None = None
        v1_url = (
            f"{self._config.base_url}/api/v1/models"
            if not self._is_ollama
            else f"{self._config.base_url}/api/tags"
        )
        try:
            resp = await self._client.get(
                v1_url,
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("models") or data.get("data") or []
            if items:
                # Prefer a loaded LLM (skip embedding models — LM Studio v1 API
                # returns "type": "llm" | "embedding" for each entry, and
                # sending chat/completions to an embedding model will fail).
                for item in items:
                    if self._is_embedding_model(item):
                        continue
                    state = item.get("state", "")
                    if state in ("loaded", "loading", ""):
                        resolved = item.get("path") or item.get("id") or item.get("name")
                        if resolved:
                            break
                if not resolved:
                    # Fall back to first non-embedding model regardless of state
                    for item in items:
                        if not self._is_embedding_model(item):
                            resolved = item.get("path") or item.get("id") or item.get("name")
                            break
                if not resolved:
                    logger.debug(
                        "LM Studio v1 API returned {} model(s), all "
                        "embedding — falling back to OAI-compat",
                        len(items),
                    )
        except Exception as exc:
            logger.debug("LM Studio v1 model query failed ({}), trying OAI-compat", exc)

        if not resolved:
            # Final fallback: OAI-compat /v1/models
            try:
                resp = await self._client.get(
                    f"{self._config.base_url}/v1/models",
                    timeout=httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0),
                )
                resp.raise_for_status()
                items = resp.json().get("data", [])
                # Skip embedding models in OAI-compat responses too
                for item in items:
                    if not self._is_embedding_model(item):
                        resolved = item.get("id")
                        if resolved:
                            break
                if not resolved and items:
                    logger.warning(
                        "All {} model(s) from OAI-compat API are embedding "
                        "models — cannot use for chat",
                        len(items),
                    )
            except Exception as exc2:
                logger.warning("OAI-compat auto model resolution failed: {}", exc2)

        if resolved:
            prev = self._auto_model_cache
            self._auto_model_cache = (resolved, now)
            if prev is None or prev[0] != resolved:
                logger.info("Auto-resolved LLM model: {}", resolved)
            return resolved

        # Could not resolve — let the server decide.
        logger.warning("Could not auto-resolve model; sending 'auto'")
        return "auto"

    def _invalidate_model_cache(self) -> None:
        """Invalidate the cached auto-resolved model ID."""
        self._auto_model_cache = None

    def _load_system_prompt(self) -> str:
        """Read the system prompt from the configured file path.

        Appends dynamic environment info (username, home directory)
        so the LLM can build correct file paths.

        Returns:
            The system prompt text.

        Raises:
            FileNotFoundError: If the configured system prompt file is missing.
        """
        if not self._config.system_prompt_enabled:
            return ""

        if self._system_prompt is not None:
            return self._system_prompt

        path = Path(self._config.system_prompt_file)
        if not path.exists():
            raise FileNotFoundError(
                f"System prompt file not found: {path}"
            )

        base = path.read_text(encoding="utf-8").strip()

        # Append dynamic environment context
        try:
            username = os.getlogin()
        except OSError:
            username = os.environ.get("USERNAME") or os.environ.get("USER") or "User"
        home = str(Path.home())
        desktop = str(Path.home() / "Desktop")
        env_block = (
            f"\n\n## Ambiente utente\n\n"
            f"- **Username**: {username}\n"
            f"- **Home**: {home}\n"
            f"- **Desktop**: {desktop}\n"
        )

        self._system_prompt = base + env_block
        logger.debug("Loaded system prompt from {}", path)
        return self._system_prompt

    def invalidate_system_prompt_cache(self) -> None:
        """Clear the cached system prompt so it is reloaded on next access."""
        self._system_prompt = None

    def _get_dynamic_system_prompt(self) -> str:
        """Return system prompt with current date/time appended.

        The base prompt is cached; only the temporal context is
        regenerated on each call so the LLM always knows "today's" date.
        """
        base = self._load_system_prompt()
        if not base:
            return ""

        now = datetime.now()
        # Italian locale-aware day/month names
        days_it = [
            "lunedì", "martedì", "mercoledì", "giovedì",
            "venerdì", "sabato", "domenica",
        ]
        months_it = [
            "", "gennaio", "febbraio", "marzo", "aprile", "maggio",
            "giugno", "luglio", "agosto", "settembre", "ottobre",
            "novembre", "dicembre",
        ]
        day_name = days_it[now.weekday()]
        month_name = months_it[now.month]
        date_str = f"{day_name} {now.day} {month_name} {now.year}"

        time_block = (
            f"## Data e ora corrente\n\n"
            f"- **Data odierna**: {date_str}\n"
            f"- **Data ISO**: {now.strftime('%Y-%m-%d')}\n"
            f"- **Ora**: {now.strftime('%H:%M')}\n"

        )
        # Prepend temporal context so it sits at the TOP of the system prompt
        # (beginning of context window = maximum model attention).
        # Appending it at the end risks "lost in the middle" suppression,
        # causing the model to revert to its training-time date assumption.
        return time_block + base

    def get_system_prompt(
        self, memory_context: str | None = None,
    ) -> str:
        """Build the full system prompt with optional memory context.

        Use this to build the prompt once per request and pass it to
        both ``build_messages`` and ``build_continuation_messages``
        via the ``system_prompt`` parameter to avoid redundant work.

        Args:
            memory_context: Optional block of relevant memories/MCP
                context to append.

        Returns:
            The complete system prompt string.
        """
        base = self._get_dynamic_system_prompt()
        if memory_context and base:
            return f"{base}\n\n{memory_context}"
        if memory_context:
            return memory_context
        return base

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    @staticmethod
    def _fold_system_into_user(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Move the system prompt out of \"system\" role into user content.

        LM Studio's OAI-compat endpoint suppresses ``reasoning_content``
        when a ``system`` role message is present.  This helper folds the
        system prompt into the first user message so that reasoning models
        can still produce reasoning tokens.

        Non-system messages are passed through unchanged.
        """
        system_parts: list[str] = []
        rest: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg["content"])
            else:
                rest.append(msg)

        if not system_parts:
            return rest

        system_block = "\n\n".join(system_parts)

        # Find the first user message and prepend the system prompt.
        for i, msg in enumerate(rest):
            if msg.get("role") == "user":
                content = msg["content"]
                if isinstance(content, str):
                    rest[i] = {
                        **msg,
                        "content": (
                            f"[System Instructions]\n{system_block}"
                            f"\n[/System Instructions]\n\n{content}"
                        ),
                    }
                else:
                    # Multimodal content (list of parts) — prepend text part.
                    rest[i] = {
                        **msg,
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"[System Instructions]\n{system_block}"
                                    "\n[/System Instructions]\n\n"
                                ),
                            },
                            *content,
                        ],
                    }
                break
        else:
            # No user message found — prepend as a user message.
            rest.insert(0, {
                "role": "user",
                "content": (
                    f"[System Instructions]\n{system_block}"
                    "\n[/System Instructions]"
                ),
            })

        return rest

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build a full message list with system prompt, history, and user msg.

        Args:
            user_content: The new user message text.
            history: Optional prior messages to include.
            attachments: Optional list of dicts with ``file_path`` (absolute)
                and ``content_type`` keys for vision-model image inputs.
            memory_context: Optional block of relevant memories to append
                to the system prompt.  Ignored when *system_prompt* is
                provided (it should already include memory context).
            system_prompt: Pre-built system prompt (from
                ``get_system_prompt``).  When provided, *memory_context*
                is ignored and the prompt is used as-is.

        Returns:
            A list of message dicts ready for the chat completions API.
        """
        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            sys_prompt = system_prompt
        else:
            sys_prompt = self._get_dynamic_system_prompt()
            if memory_context and sys_prompt:
                sys_prompt = f"{sys_prompt}\n\n{memory_context}"
            elif memory_context:
                sys_prompt = memory_context
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
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
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages for tool-loop continuation (no new user message).

        Used when the LLM needs to be re-queried after tool execution.
        The history already contains the user message, assistant tool_calls,
        and tool results, so no additional user message is appended.

        Args:
            history: Full conversation history including tool messages.
            memory_context: Optional block of relevant memories to append
                to the system prompt.  Ignored when *system_prompt* is
                provided.
            system_prompt: Pre-built system prompt (from
                ``get_system_prompt``).  When provided, *memory_context*
                is ignored.

        Returns:
            A list of message dicts: system prompt + normalized history.
        """
        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            sys_prompt = system_prompt
        else:
            sys_prompt = self._get_dynamic_system_prompt()
            if memory_context and sys_prompt:
                sys_prompt = f"{sys_prompt}\n\n{memory_context}"
            elif memory_context:
                sys_prompt = memory_context
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        if history:
            messages.extend(normalize_history(history))
        return messages

    # ------------------------------------------------------------------
    # Streaming chat — public dispatcher
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        *,
        user_content: str | None = None,
        conversation_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, choosing the best backend.

        Uses LM Studio's native ``/api/v1/chat`` when possible (no
        tools, not Ollama, user_content provided).  Falls back to the
        OpenAI-compatible ``/v1/chat/completions`` otherwise.

        Args:
            messages: Full message list (used by OAI-compat path).
            tools: Optional tool definitions for function calling.
            cancel_event: Optional cancellation event.
            user_content: Raw user message (enables native API path).
            conversation_id: Conversation UUID string for response_id
                tracking.
            attachments: Optional image attachment dicts with
                ``file_path`` / ``content_type`` / ``_bytes`` keys.
            memory_context: Optional pre-formatted memory block to
                inject into the system prompt (native path only;
                OAI-compat path already has it baked into *messages*).
                Ignored when *system_prompt* is provided.
            system_prompt: Pre-built system prompt.  When provided,
                *memory_context* is ignored in the native path.

        Yields:
            Dicts with a ``type`` key — same contract for both paths.
        """
        use_native = (
            not self._is_ollama
            and tools is None
            and user_content is not None
        )
        if use_native:
            async for event in self._chat_lmstudio_native(
                user_content=user_content,
                cancel_event=cancel_event,
                conversation_id=conversation_id,
                attachments=attachments,
                memory_context=memory_context,
                system_prompt=system_prompt,
                max_output_tokens=max_output_tokens,
            ):
                yield event
        else:
            async for event in self._chat_openai_compat(
                messages, tools=tools, cancel_event=cancel_event,
                max_output_tokens=max_output_tokens,
            ):
                yield event

    # ------------------------------------------------------------------
    # LM Studio native API streaming
    # ------------------------------------------------------------------

    async def _chat_lmstudio_native(
        self,
        user_content: str,
        cancel_event: asyncio.Event | None = None,
        conversation_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream via LM Studio native REST API ``/api/v1/chat``.

        This endpoint natively separates reasoning from content via
        dedicated SSE event types (``reasoning.delta`` /
        ``message.delta``).  For models that embed ``<think>`` tags in
        ``message.delta`` content instead, a ``ThinkTagParser`` extracts
        them when ``supports_thinking`` is enabled.

        Args:
            user_content: The raw user message text.
            cancel_event: Optional cancellation event.
            conversation_id: Conversation UUID string for multi-turn
                response_id tracking.
            attachments: Optional image attachment dicts.
            memory_context: Optional pre-formatted memory block to
                append to the system prompt.

        Yields:
            ``{"type": "thinking"|"token"|"done", ...}``
        """
        url = f"{self._config.base_url}/api/v1/chat"

        # Build the input field — multimodal array or plain string.
        input_field: str | list[dict[str, Any]]
        if attachments and self._config.supports_vision:
            parts: list[dict[str, Any]] = [
                {"type": "message", "content": user_content},
            ]
            for att in attachments:
                if "_bytes" in att:
                    image_bytes = att["_bytes"]
                else:
                    image_bytes = await asyncio.to_thread(
                        Path(att["file_path"]).read_bytes,
                    )
                b64 = base64.b64encode(image_bytes).decode("ascii")
                mime = att["content_type"]
                parts.append({
                    "type": "image",
                    "data_url": f"data:{mime};base64,{b64}",
                })
            input_field = parts
        else:
            input_field = user_content

        if system_prompt is not None:
            sys_prompt = system_prompt
        else:
            sys_prompt = self._get_dynamic_system_prompt()
            if memory_context and sys_prompt:
                sys_prompt = f"{sys_prompt}\n\n{memory_context}"
            elif memory_context:
                sys_prompt = memory_context
        active_model = await self._resolve_model()
        payload: dict[str, Any] = {
            "model": active_model,
            "input": input_field,
            "stream": True,
            "temperature": self._config.temperature,
            "store": True,
        }
        effective_max = max_output_tokens or (
            self._config.max_tokens if self._config.max_tokens > 0 else None
        )
        if effective_max is not None and effective_max > 0:
            payload["max_output_tokens"] = effective_max
        if sys_prompt:
            payload["system_prompt"] = sys_prompt

        # Multi-turn: include previous response_id if available.
        if conversation_id:
            prev_id = self._response_ids.get(conversation_id)
            if prev_id:
                payload["previous_response_id"] = prev_id

        _stream_timeout = httpx.Timeout(
            connect=self._config.connect_timeout,
            read=max(self._config.timeout, 600.0),
            write=10.0,
            pool=10.0,
        )

        # Try with explicit reasoning parameter first; some models
        # reject it, so fall back to a request without it.
        if self._config.supports_thinking:
            payload["reasoning"] = "on"

        logger.debug(
            "LM Studio native chat — model={}, reasoning={}",
            active_model,
            payload.get("reasoning", "off"),
        )

        try:
            async for event in self._stream_lmstudio_native_sse(
                url, payload, _stream_timeout, cancel_event, conversation_id,
            ):
                yield event
                if event.get("type") == "done":
                    return
        except httpx.HTTPStatusError as exc:
            if not (
                self._config.supports_thinking
                and exc.response.status_code == 400
                and "reasoning" in payload
            ):
                raise
            logger.warning(
                "Model rejected 'reasoning' param — retrying without it",
            )
            payload.pop("reasoning", None)
            try:
                async for event in self._stream_lmstudio_native_sse(
                    url, payload, _stream_timeout, cancel_event, conversation_id,
                ):
                    yield event
                    if event.get("type") == "done":
                        return
            except (
                httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError,
            ) as retry_exc:
                logger.warning(
                    "Connection lost during LM Studio native stream "
                    "(retry): {}", retry_exc,
                )
        except (
            httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError,
        ) as exc:
            logger.warning(
                "Connection lost during LM Studio native stream: {}", exc,
            )

        # Stream ended without chat.end — cancelled or connection lost.
        cancelled = (
            cancel_event is not None and cancel_event.is_set()
        )
        # If not cancelled, the model likely ran out of context
        # (LM Studio drops the SSE stream without chat.end).
        yield {
            "type": "done",
            "finish_reason": (
                "cancelled" if cancelled else "length"
            ),
        }

    # ------------------------------------------------------------------
    # LM Studio native SSE helper
    # ------------------------------------------------------------------

    async def _stream_lmstudio_native_sse(
        self,
        url: str,
        payload: dict[str, Any],
        timeout: httpx.Timeout,
        cancel_event: asyncio.Event | None,
        conversation_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Low-level SSE reader for the LM Studio native API.

        Yields event dicts (``thinking``, ``token``, ``done``, ``error``).
        Raises ``httpx.HTTPStatusError`` on HTTP errors so the caller
        can decide to retry.
        """
        # Always parse inline think tags — transparent when absent.
        think_parser = ThinkTagParser()
        # When the model emits native reasoning.delta events, disable
        # the tag parser to avoid duplicate extraction.
        saw_reasoning_event = False

        async with self._client.stream(
            "POST", url, json=payload, timeout=timeout,
        ) as resp:
            resp.raise_for_status()

            async for raw_line in resp.aiter_lines():
                if cancel_event and cancel_event.is_set():
                    logger.debug("LM Studio native stream cancelled")
                    break

                line = raw_line.strip()
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[len("data: "):]
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping malformed native SSE: {}",
                        data_str[:200],
                    )
                    continue

                evt_type = data.get("type", "")

                if evt_type == "reasoning.delta":
                    chunk = data.get("content", "")
                    if chunk:
                        saw_reasoning_event = True
                        yield {
                            "type": "thinking",
                            "content": chunk,
                        }
                elif evt_type == "message.delta":
                    chunk = data.get("content", "")
                    if chunk:
                        if not saw_reasoning_event:
                            for kind, text in think_parser.feed(chunk):
                                yield {
                                    "type": "thinking" if kind == "thinking" else "token",
                                    "content": text,
                                }
                        else:
                            yield {
                                "type": "token",
                                "content": chunk,
                            }
                elif evt_type == "chat.end":
                    if not saw_reasoning_event:
                        for kind, text in think_parser.flush():
                            yield {
                                "type": "thinking" if kind == "thinking" else "token",
                                "content": text,
                            }
                    result = data.get("result", {})
                    resp_id = result.get("response_id")
                    stats = result.get("stats", {})
                    if stats.get("input_tokens"):
                        yield {
                            "type": "usage",
                            "input_tokens": stats["input_tokens"],
                            "output_tokens": stats.get(
                                "total_output_tokens", 0,
                            ),
                        }
                    if resp_id and conversation_id:
                        self._response_ids[conversation_id] = (
                            resp_id
                        )
                        self._response_ids.move_to_end(
                            conversation_id,
                        )
                        if len(self._response_ids) > (
                            self._response_ids_max
                        ):
                            self._response_ids.popitem(
                                last=False,
                            )
                        logger.debug(
                            "Stored response_id {} for conv {}",
                            resp_id, conversation_id,
                        )
                    yield {
                        "type": "done",
                        "finish_reason": "stop",
                        "response_id": resp_id,
                    }
                    return
                elif evt_type == "error":
                    err_obj = data.get("error", {})
                    err_msg = err_obj.get(
                        "message", "Unknown error",
                    )
                    err_type = err_obj.get("type", "unknown")
                    logger.error(
                        "LM Studio native API error ({}): {}",
                        err_type, err_msg,
                    )
                    if conversation_id:
                        self._response_ids.pop(
                            conversation_id, None,
                        )
                    yield {
                        "type": "error",
                        "content": err_msg,
                    }
                    yield {
                        "type": "done",
                        "finish_reason": "error",
                    }
                    return
                # Ignore: chat.start, reasoning.start/end,
                # message.start/end, prompt_processing.*, model_load.*

            # Stream ended without chat.end — flush any buffered thinking.
            if think_parser:
                for kind, text in think_parser.flush():
                    yield {
                        "type": "thinking" if kind == "thinking" else "token",
                        "content": text,
                    }

    # ------------------------------------------------------------------
    # OpenAI-compatible streaming
    # ------------------------------------------------------------------

    async def _chat_openai_compat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion via the OAI-compatible endpoint.

        Sends a POST to ``{base_url}/v1/chat/completions`` with
        ``stream=True`` and yields parsed event dicts.

        Args:
            messages: The full list of messages for the API.
            tools: Optional tool definitions for function calling.
            cancel_event: Optional event that, when set, signals the
                stream to stop early.

        Yields:
            Dicts with a ``type`` key:
            - ``{"type": "token", "content": "..."}``
            - ``{"type": "thinking", "content": "..."}``
            - ``{"type": "tool_call", "id": "...", "function": {...}}``
            - ``{"type": "done", "finish_reason": "stop"|"cancelled"}``
        """
        url = f"{self._config.base_url}/v1/chat/completions"

        # LM Studio suppresses reasoning_content when a 'system' role
        # message is present in the messages array.  Work around this
        # by folding the system prompt into the first user message.
        #
        # However, when tools are provided, the system role must stay
        # intact: LM Studio appends tool definitions to the system
        # message in the model's chat template.  Folding the system
        # prompt into user content breaks this — the model sees the
        # tools but cannot emit structured tool_calls.  Thinking is
        # still captured via inline <think> tags (ThinkTagParser).
        should_fold = not self._is_ollama and not tools
        actual_messages = (
            self._fold_system_into_user(messages)
            if should_fold
            else messages
        )

        active_model = await self._resolve_model()
        payload: dict[str, Any] = {
            "model": active_model,
            "messages": actual_messages,
            "temperature": self._config.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        effective_max = max_output_tokens or (
            self._config.max_tokens if self._config.max_tokens > 0 else None
        )
        if effective_max is not None and effective_max > 0:
            payload["max_tokens"] = effective_max
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self._is_ollama:
            payload["options"] = {
                "num_gpu": self._config.num_gpu,
                "num_ctx": self._config.num_ctx,
            }
            payload["keep_alive"] = self._config.keep_alive

        # Accumulator for tool calls that arrive across multiple chunks.
        # Keyed by index (int) -> {"id": str, "name": str, "arguments": str}
        tool_calls_acc: dict[int, dict[str, str]] = {}
        last_finish_reason: str | None = None
        _last_usage: dict[str, Any] | None = None

        # Always parse inline <think> tags — transparent when absent.
        # Covers any model that embeds reasoning in content, regardless
        # of the supports_thinking config flag.
        think_parser: ThinkTagParser | None = ThinkTagParser()
        # When the model emits native reasoning_content deltas, disable
        # the tag parser to avoid duplicate / interfering extraction.
        saw_reasoning_content = False

        # Use a generous read timeout for the streaming request.
        # Reasoning models may think for several minutes before
        # producing the first token; the default client timeout
        # would fire prematurely.  Cancellation is handled via
        # cancel_event + task.cancel() on the caller side.
        _stream_timeout = httpx.Timeout(
            connect=self._config.connect_timeout,
            read=max(self._config.timeout, 600.0),
            write=10.0,
            pool=10.0,
        )

        # Skip stream_options if a previous request already confirmed
        # the server doesn't support it.
        if self._supports_stream_options is False:
            payload.pop("stream_options", None)

        for _attempt in range(2):
            async with self._client.stream(
                "POST", url, json=payload, timeout=_stream_timeout,
            ) as resp:
                if resp.status_code == 400 and _attempt == 0 and "stream_options" in payload:
                    body = (await resp.aread()).decode(errors="replace")
                    logger.warning(
                        "OAI-compat 400 with stream_options — retrying without it. "
                        "Server said: {}",
                        body[:300],
                    )
                    self._supports_stream_options = False
                    payload.pop("stream_options")
                    continue  # exit async with, try again without stream_options
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    logger.error(
                        "OAI-compat chat error {} — {}",
                        resp.status_code, body[:500],
                    )
                    resp.raise_for_status()
                if self._supports_stream_options is None and "stream_options" in payload:
                    self._supports_stream_options = True

                async for raw_line in resp.aiter_lines():
                    # Check for cancellation before processing each SSE line.
                    if cancel_event and cancel_event.is_set():
                        logger.debug("LLM stream cancelled by cancel_event")
                        break

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
                            if not tc["name"]:
                                logger.warning(
                                    "Discarding incomplete tool call: {}", tc,
                                )
                                continue
                            if not tc["id"]:
                                tc["id"] = f"call_{uuid.uuid4().hex[:24]}"
                            yield {
                                "type": "tool_call",
                                "id": tc["id"],
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            }
                        if _last_usage:
                            yield {
                                "type": "usage",
                                "input_tokens": _last_usage.get("prompt_tokens", 0),
                                "output_tokens": _last_usage.get("completion_tokens", 0),
                            }
                        yield {
                            "type": "done",
                            "finish_reason": last_finish_reason or "stop",
                        }
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed SSE chunk: {}", data_str)
                        continue

                    # Capture usage data from final chunk (if present).
                    if chunk.get("usage"):
                        _last_usage = chunk["usage"]

                    # Detect error responses from the LLM server (e.g.
                    # Jinja template rendering failures in LM Studio).
                    if "error" in chunk:
                        err = chunk["error"]
                        err_msg = (
                            err.get("message", str(err))
                            if isinstance(err, dict)
                            else str(err)
                        )
                        logger.error(
                            "LLM server error during streaming: {}", err_msg,
                        )
                        yield {"type": "error", "content": err_msg}
                        yield {
                            "type": "done",
                            "finish_reason": "error",
                        }
                        return

                    choices = chunk.get("choices")
                    if not choices:
                        continue

                    chunk_finish = choices[0].get("finish_reason")
                    if chunk_finish:
                        last_finish_reason = chunk_finish

                    delta = choices[0].get("delta", {})

                    # --- explicit reasoning_content (LM Studio / Ollama extension) ---
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        if not saw_reasoning_content:
                            saw_reasoning_content = True
                            think_parser = None
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
                        if func.get("arguments") is not None:
                            tool_calls_acc[idx]["arguments"] += func["arguments"]

            break  # success — no retry needed

        # Stream ended without [DONE] — either cancelled or connection closed.
        cancelled = cancel_event is not None and cancel_event.is_set()
        if not cancelled and not tool_calls_acc and last_finish_reason is None:
            logger.warning(
                "LLM stream ended without [DONE] and no content/tool_calls "
                "— possible server error (e.g. Jinja template failure)"
            )
        finish = "cancelled" if cancelled else (last_finish_reason or "stop")

        if think_parser:
            for kind, text in think_parser.flush():
                yield {
                    "type": "thinking" if kind == "thinking" else "token",
                    "content": text,
                }
        for _idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[_idx]
            if not tc["name"]:
                logger.warning(
                    "Discarding incomplete tool call: {}", tc,
                )
                continue
            if not tc["id"]:
                tc["id"] = f"call_{uuid.uuid4().hex[:24]}"
            yield {
                "type": "tool_call",
                "id": tc["id"],
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
        if _last_usage:
            yield {
                "type": "usage",
                "input_tokens": _last_usage.get("prompt_tokens", 0),
                "output_tokens": _last_usage.get("completion_tokens", 0),
            }
        yield {"type": "done", "finish_reason": finish}

    # ------------------------------------------------------------------
    # Non-streaming chat
    # ------------------------------------------------------------------

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        """Complete a chat request without streaming (for summarization).

        Uses the OAI-compatible endpoint with ``stream=False``.
        Returns the assistant content or empty string on any error.

        Args:
            messages: Full message list (caller controls content).
            max_tokens: Maximum tokens for the response.

        Returns:
            The assistant's response text, or ``""`` on failure.
        """
        url = f"{self._config.base_url}/v1/chat/completions"
        active_model = await self._resolve_model()
        payload: dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "stream": False,
        }
        _compress_timeout = httpx.Timeout(
            connect=5.0,
            read=self._config.context_compression_timeout,
            write=5.0,
            pool=5.0,
        )
        try:
            resp = await self._client.post(
                url, json=payload, timeout=_compress_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"] or ""
            # Strip <think>…</think> tags that reasoning models may
            # produce even in non-streaming mode, keeping summaries clean.
            if raw_content:
                parser = ThinkTagParser()
                parts = parser.feed(raw_content)
                parts.extend(parser.flush())
                content_only = "".join(
                    text for kind, text in parts if kind == "content"
                )
                return content_only.strip() or raw_content
            return raw_content
        except Exception as exc:
            logger.warning("Non-streaming completion failed: {}", exc)
            return ""

    async def get_active_context_window(
        self, lmstudio_manager: Any = None,
    ) -> int:
        """Return the context window of the currently loaded model.

        Queries the LM Studio v1 API for loaded model metadata.
        Falls back to 32768 if unavailable.

        Args:
            lmstudio_manager: Optional LMStudioManager for v1 API calls.

        Returns:
            Context window size in tokens.
        """
        try:
            if lmstudio_manager is not None:
                data = await lmstudio_manager.list_models()
                for model in data.get("models", []):
                    if model.get("type") == "embedding":
                        continue
                    instances = model.get("loaded_instances", [])
                    if instances:
                        ctx_len = instances[0].get("config", {}).get(
                            "context_length", 0,
                        )
                        if ctx_len > 0:
                            return ctx_len
        except Exception as exc:
            logger.debug("Failed to query context window: {}", exc)
        return 32768

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client and release caches."""
        await self._client.aclose()
        self._response_ids.clear()
        self._auto_model_cache = None
        logger.debug("LLMService httpx client closed")
