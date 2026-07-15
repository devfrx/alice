"""AL\\CE — LLM streaming/completion client.

Talks to LM Studio's native ``/api/v1/chat`` SSE API and the
OpenAI-compatible ``/v1/chat/completions`` SSE API, plus the
non-streaming ``complete_nonstreaming`` helper used for summarization.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.llm.model_resolution import ModelResolver
from backend.services.llm.prompting import PromptBuilder
from backend.services.model_capability_registry import ModelCapabilityRegistry
from backend.services.thinking_parser import ThinkTagParser


class LLMClient:
    """Stream chat completions from any OpenAI-compatible API.

    Args:
        config: The ``LLMConfig`` holding provider URL, model name, etc.
        http: Shared ``httpx.AsyncClient`` owned by the ``LLMService``
            facade.
        resolver: The :class:`ModelResolver` used to pick the active
            model and its capability profile.
        model_registry: Dynamic per-model capability registry, used to
            record runtime-learned facts (reasoning param acceptance,
            native reasoning emission).
        prompts: The :class:`PromptBuilder`, used to fold the system
            prompt into the first user message when required.
    """

    def __init__(
        self,
        config: LLMConfig,
        http: httpx.AsyncClient,
        resolver: ModelResolver,
        model_registry: ModelCapabilityRegistry | None,
        prompts: PromptBuilder,
    ) -> None:
        self._config = config
        self._http = http
        self._resolver = resolver
        self._model_registry = model_registry
        self._prompts = prompts
        # Derived from the (runtime-immutable) config — ModelResolver
        # derives the same flag independently; not shared mutable state.
        self._is_ollama = config.provider == "ollama"
        self._is_openrouter = config.provider == "openrouter"
        self._response_ids: OrderedDict[str, str] = OrderedDict()
        self._response_ids_max = 500
        # None = unknown, True = supported, False = not supported
        self._supports_stream_options: bool | None = None
        # Same idea for ``response_format`` — some LM Studio builds only
        # accept ``json_schema``/``text`` and reject ``json_object`` with
        # a 400.  Once we observe the rejection we stop sending it to
        # avoid a wasted round-trip on every classifier/planner/critic
        # call.
        self._supports_response_format: bool | None = None

    def clear_response_ids(self) -> None:
        """Drop the per-conversation response-id chain (used on close)."""
        self._response_ids.clear()

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
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
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
            and not self._is_openrouter
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
                response_format=response_format,
                temperature=temperature,
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

        active_model = await self._resolver.resolve()
        profile = self._resolver.get_model_profile(active_model)

        # Build the input field — multimodal array or plain string.
        input_field: str | list[dict[str, Any]]
        if attachments and profile.supports_vision:
            parts: list[dict[str, Any]] = [
                {"type": "text", "content": user_content},
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
            sys_prompt = self._prompts._get_dynamic_system_prompt()
            if memory_context and sys_prompt:
                sys_prompt = f"{sys_prompt}\n\n{memory_context}"
            elif memory_context:
                sys_prompt = memory_context
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

        # Decide whether to send "reasoning": "on" based on the model
        # profile.  accepts_reasoning_param tracks runtime learning:
        #   None  = unknown → try it (model might support it)
        #   True  = confirmed accepted
        #   False = previously rejected → skip to avoid wasted retry
        send_reasoning = (
            profile.supports_thinking
            and profile.accepts_reasoning_param is not False
        )
        if send_reasoning:
            payload["reasoning"] = "on"

        logger.debug(
            "LM Studio native chat — model={}, reasoning={}, profile={}",
            active_model,
            payload.get("reasoning", "off"),
            profile.source,
        )

        try:
            async for event in self._stream_lmstudio_native_sse(
                url, payload, _stream_timeout, cancel_event, conversation_id,
            ):
                yield event
                if event.get("type") == "done":
                    # Reasoning param was accepted — remember for next time.
                    if send_reasoning and self._model_registry:
                        self._model_registry.mark_reasoning_param_accepted(
                            active_model,
                        )
                    return
        except httpx.HTTPStatusError as exc:
            if not (
                send_reasoning
                and exc.response.status_code == 400
                and "reasoning" in payload
            ):
                raise
            # Model rejected the reasoning param — learn and retry once.
            if self._model_registry:
                self._model_registry.mark_reasoning_param_rejected(
                    active_model,
                )
            else:
                logger.warning(
                    "Model '{}' rejected 'reasoning' param — "
                    "retrying without it",
                    active_model,
                )
            payload.pop("reasoning", None)
            async for event in self._stream_lmstudio_native_sse(
                url, payload, _stream_timeout, cancel_event, conversation_id,
            ):
                yield event
                if event.get("type") == "done":
                    return

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
        # Track whether the caller explicitly requested reasoning param.
        # Used to distinguish "reasoning param accepted" from
        # "model reasons natively without the param".
        explicit_reasoning = "reasoning" in payload
        active_model: str = payload.get("model", "")

        async with self._http.stream(
            "POST", url, json=payload, timeout=timeout,
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode(errors="replace")
                logger.error(
                    "LM Studio native API returned {} — body: {}",
                    resp.status_code,
                    body[:500],
                )
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
                        if not saw_reasoning_event:
                            saw_reasoning_event = True
                            # If reasoning events appear without the param,
                            # the model has thinking baked in — learn this.
                            if not explicit_reasoning and self._model_registry and active_model:
                                self._model_registry.mark_emits_reasoning_natively(
                                    active_model,
                                )
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
                        # No reasoning events seen and no param was sent →
                        # this model definitely doesn't reason natively.
                        if not explicit_reasoning and self._model_registry and active_model:
                            self._model_registry.mark_no_reasoning_natively(
                                active_model,
                            )
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
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
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
        url = f"{self._config.effective_base_url}/v1/chat/completions"

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
        should_fold = not self._is_ollama and not self._is_openrouter and not tools
        actual_messages = (
            self._prompts._fold_system_into_user(messages)
            if should_fold
            else messages
        )

        active_model = await self._resolver.resolve()
        payload: dict[str, Any] = {
            "model": active_model,
            "messages": actual_messages,
            "temperature": (
                temperature if temperature is not None else self._config.temperature
            ),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        effective_max = max_output_tokens or (
            self._config.max_tokens if self._config.max_tokens > 0 else None
        )
        if effective_max is not None and effective_max > 0:
            payload["max_tokens"] = effective_max
        if response_format is not None and self._supports_response_format is not False:
            # LM Studio / OpenAI accept ``{"type": "json_object"}``.  When
            # the server rejects it (legacy backends), the OAI-compat
            # retry loop below strips it on the first 400 and we cache the
            # rejection in ``_supports_response_format`` so subsequent
            # requests skip the field entirely.
            payload["response_format"] = response_format
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

        # Up to 3 attempts: each 400 may flag a different offending field
        # (stream_options, response_format, or a combination).  We inspect
        # the body to drop the right one rather than guessing.
        for _attempt in range(3):
            async with self._http.stream(
                "POST", url, json=payload, timeout=_stream_timeout,
            ) as resp:
                if resp.status_code == 400 and _attempt < 2:
                    body = (await resp.aread()).decode(errors="replace")
                    body_lc = body.lower()
                    # Detect which field the server complained about.
                    # Inspect response_format FIRST: some servers reject
                    # the field outright (e.g. require json_schema/text),
                    # which has nothing to do with stream_options.
                    if (
                        "response_format" in body_lc
                        and "response_format" in payload
                    ):
                        logger.warning(
                            "OAI-compat 400 with response_format — retrying "
                            "without it. Server said: {}", body[:300],
                        )
                        self._supports_response_format = False
                        payload.pop("response_format", None)
                        continue
                    if (
                        "stream_options" in body_lc
                        and "stream_options" in payload
                    ):
                        logger.warning(
                            "OAI-compat 400 with stream_options — retrying "
                            "without it. Server said: {}", body[:300],
                        )
                        self._supports_stream_options = False
                        payload.pop("stream_options", None)
                        continue
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    logger.error(
                        "OAI-compat chat error {} — {}",
                        resp.status_code, body[:500],
                    )
                    resp.raise_for_status()
                if self._supports_stream_options is None and "stream_options" in payload:
                    self._supports_stream_options = True
                if self._supports_response_format is None and "response_format" in payload:
                    self._supports_response_format = True

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
        url = f"{self._config.effective_base_url}/v1/chat/completions"
        active_model = await self._resolver.resolve()
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
            resp = await self._http.post(
                url, json=payload, timeout=_compress_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.warning("Non-streaming completion failed: {}", exc)
            return ""
