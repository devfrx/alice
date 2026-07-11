"""AL\\CE — System-prompt composition and chat-message building.

Owns the base/scoped system prompt cache, the temporal block, and the
assembly of the message list sent to the chat-completions API
(including history normalization and the vision-attachment manifest).
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.config import LLMConfig


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


class PromptBuilder:
    """Compose system prompts and build chat-completions message lists.

    Args:
        config: The ``LLMConfig`` holding the system-prompt file path,
            temperature, user-preferred name, etc.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._system_prompt: str | None = None
        # Cache of alternate, task-scoped base prompts keyed by file path
        # (e.g. the Continuum-scoped agent persona). Kept separate from
        # ``_system_prompt`` so scopes never clobber the default prompt.
        self._scoped_prompts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

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
        if self._config.user_preferred_name:
            env_block += (
                f"- **Come preferisci essere chiamato/a**: "
                f"{self._config.user_preferred_name}\n"
            )

        self._system_prompt = base + env_block
        logger.debug("Loaded system prompt from {}", path)
        return self._system_prompt

    def invalidate_system_prompt_cache(self) -> None:
        """Clear the cached system prompt so it is reloaded on next access."""
        self._system_prompt = None
        self._scoped_prompts.clear()

    def _temporal_block(self) -> str:
        """Build the 'current date/time' block prepended to system prompts.

        Regenerated on every call so the LLM always knows "today's" date.
        """
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
        return (
            f"## Data e ora corrente\n\n"
            f"- **Data odierna**: {date_str}\n"
            f"- **Data ISO**: {now.strftime('%Y-%m-%d')}\n"
            f"- **Ora**: {now.strftime('%H:%M')}\n"
        )

    def _get_dynamic_system_prompt(self) -> str:
        """Return system prompt with current date/time appended.

        The base prompt is cached; only the temporal context is
        regenerated on each call so the LLM always knows "today's" date.
        """
        base = self._load_system_prompt()
        if not base:
            return ""

        # Prepend temporal context so it sits at the TOP of the system prompt
        # (beginning of context window = maximum model attention).
        # Appending it at the end risks "lost in the middle" suppression,
        # causing the model to revert to its training-time date assumption.
        return self._temporal_block() + base

    def get_system_prompt(
        self,
        memory_context: str | None = None,
        *,
        persona: str | None = None,
    ) -> str:
        """Build the full system prompt with optional persona + memory context.

        Use this to build the prompt once per request and pass it to
        both ``build_messages`` and ``build_continuation_messages``
        via the ``system_prompt`` parameter to avoid redundant work.

        The assembly order is: temporal block + base prompt (+ env block),
        then the optional global persona block, then the optional memory
        context. The persona text is supplied by the caller (it lives under
        the agent config, not the LLM config) so this service stays agnostic
        of the agent tree.

        Args:
            memory_context: Optional block of relevant memories/MCP
                context to append last.
            persona: Optional free-text persona/instructions appended
                globally as a ``## Istruzioni personalizzate`` block between
                the base prompt and ``memory_context``. Falsy values
                (``None`` / empty) add nothing and reproduce the prior output.

        Returns:
            The complete system prompt string.
        """
        base = self._get_dynamic_system_prompt()
        if persona and base:
            base = f"{base}\n\n## Istruzioni personalizzate\n\n{persona}"
        if memory_context and base:
            return f"{base}\n\n{memory_context}"
        if memory_context:
            return memory_context
        return base

    def _load_scoped_prompt(self, path_str: str) -> str:
        """Read and cache an alternate, task-scoped base prompt file.

        Unlike :meth:`_load_system_prompt`, the OS-environment block is
        intentionally omitted so the scoped persona stays clean. A missing
        file is treated as a soft failure (logged, empty string returned)
        so callers can transparently fall back to the default prompt.

        Args:
            path_str: Absolute path to the scoped prompt markdown file.

        Returns:
            The scoped prompt text, or ``""`` if the file is missing.
        """
        cached = self._scoped_prompts.get(path_str)
        if cached is not None:
            return cached

        path = Path(path_str)
        if not path.exists():
            logger.warning("Scoped system prompt file not found: {}", path)
            return ""

        base = path.read_text(encoding="utf-8").strip()
        self._scoped_prompts[path_str] = base
        logger.debug("Loaded scoped system prompt from {}", path)
        return base

    def get_scoped_system_prompt(
        self,
        base_prompt_path: str,
        memory_context: str | None = None,
    ) -> str:
        """Build a task-scoped system prompt from an ALTERNATE base file.

        Used by callers that need a focused agent persona (e.g. the
        Continuum-scoped agent) instead of Alice's general-purpose
        prompt. The temporal context block is reused, but the local-OS
        environment block is omitted to keep the scope clean. If the
        scoped file is missing, this transparently falls back to the
        default system prompt so chats never break.

        Args:
            base_prompt_path: Absolute path to the scoped prompt file.
            memory_context: Optional block of relevant memories/context
                to append.

        Returns:
            The complete scoped system prompt string.
        """
        base = self._load_scoped_prompt(base_prompt_path)
        if not base:
            # Soft fallback: behave exactly like the default prompt.
            return self.get_system_prompt(memory_context=memory_context)

        prompt = self._temporal_block() + base
        if memory_context:
            return f"{prompt}\n\n{memory_context}"
        return prompt

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
                    logger.debug(
                        "Folded system prompt into multimodal user message ({} parts)",
                        len(content) + 1,
                    )
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
        *,
        supports_vision: bool = False,
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
            supports_vision: Whether the active model accepts image inputs
                (resolved by the caller via
                :attr:`~backend.services.llm.model_resolution.ModelResolver.supports_vision`
                — this module has no capability-resolution knowledge of
                its own, by design).

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
        _vision_capable = supports_vision

        # Build a machine-readable attachment manifest so the LLM can
        # forward the exact ``file_path`` to tools (e.g.
        # ``cad_generate_from_image``) instead of hallucinating one.
        # This is appended to the text regardless of vision capability,
        # because path-based tools work without seeing the image.
        path_hints = "\n".join(
            f"- {att.get('filename', 'file')}: {att['file_path']}"
            for att in (attachments or [])
            if att.get("file_path")
        )
        text_with_hints = (
            f"{user_content}\n\n[Allegati disponibili (usa esattamente "
            f"questi file_path con i tool):\n{path_hints}]"
            if path_hints else user_content
        )

        if attachments and _vision_capable:
            content_parts: list[dict[str, Any]] = [
                {"type": "text", "text": text_with_hints},
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
            messages.append({"role": "user", "content": text_with_hints})

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
