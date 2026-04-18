"""AL\\CE — Context window management and compression service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger

try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TIKTOKEN_AVAILABLE = False

from backend.core.config import LLMConfig


class CompressionError(Exception):
    """Raised when context compression fails (empty summary, etc.)."""


@dataclass
class ContextUsage:
    """Snapshot of context window utilization."""

    used_tokens: int
    available_tokens: int
    context_window: int
    percentage: float
    was_compressed: bool
    messages_summarized: int
    is_estimated: bool


@dataclass
class CompressionResult:
    """Result of a context compression operation."""

    messages: list[dict[str, Any]]
    usage: ContextUsage
    split_index: int
    summary_text: str


class ContextManager:
    """Manages context window tracking and LLM-based compression.

    Args:
        config: The LLM configuration holding compression thresholds.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._enc: tiktoken.Encoding | None = None
        if _TIKTOKEN_AVAILABLE:
            try:
                self._enc = tiktoken.get_encoding("o200k_base")
                logger.info("Token counting: tiktoken o200k_base loaded")
            except Exception:
                logger.warning(
                    "tiktoken available but failed to load encoding, "
                    "falling back to char÷4 heuristic",
                )

    def estimate_tokens(self, text: str) -> int:
        """Count tokens using tiktoken if available, else char ÷ 4.

        Args:
            text: The text to estimate.

        Returns:
            Token count (minimum 1).
        """
        if not text:
            return 1
        if self._enc is not None:
            return max(1, len(self._enc.encode(text, disallowed_special=())))
        return max(1, len(text) // 4)

    def estimate_message_tokens(self, msg: dict[str, Any]) -> int:
        """Estimate token count for a single message dict.

        Accounts for role overhead, content, and tool_calls JSON.

        Args:
            msg: A message dict with at least ``role`` and ``content``.

        Returns:
            Estimated token count.
        """
        tokens = 4  # role/metadata overhead
        content = msg.get("content") or ""
        tokens += self.estimate_tokens(content)
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            try:
                tc_str = (
                    json.dumps(tool_calls)
                    if not isinstance(tool_calls, str)
                    else tool_calls
                )
                tokens += self.estimate_tokens(tc_str)
            except (TypeError, ValueError):
                pass
        return tokens

    def count_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Sum estimated tokens across all messages.

        Args:
            messages: List of message dicts.

        Returns:
            Total estimated token count.
        """
        return sum(self.estimate_message_tokens(m) for m in messages)

    def get_usage_estimated(
        self, messages: list[dict[str, Any]], context_window: int,
    ) -> ContextUsage:
        """Build a ContextUsage from char÷4 estimates.

        Args:
            messages: The message list about to be sent to the LLM.
            context_window: Total context window size in tokens.

        Returns:
            ContextUsage with ``is_estimated=True``.
        """
        used = self.count_messages_tokens(messages)
        available = max(0, context_window - used)
        pct = (used / context_window) if context_window > 0 else 0.0
        return ContextUsage(
            used_tokens=used,
            available_tokens=available,
            context_window=context_window,
            percentage=round(pct, 4),
            was_compressed=False,
            messages_summarized=0,
            is_estimated=True,
        )

    def get_usage_real(
        self, input_tokens: int, context_window: int,
    ) -> ContextUsage:
        """Build a ContextUsage from real API-reported token counts.

        Args:
            input_tokens: Actual prompt token count from the API.
            context_window: Total context window size in tokens.

        Returns:
            ContextUsage with ``is_estimated=False``.
        """
        available = max(0, context_window - input_tokens)
        pct = (input_tokens / context_window) if context_window > 0 else 0.0
        return ContextUsage(
            used_tokens=input_tokens,
            available_tokens=available,
            context_window=context_window,
            percentage=round(pct, 4),
            was_compressed=False,
            messages_summarized=0,
            is_estimated=False,
        )

    def should_compress(self, usage: ContextUsage) -> bool:
        """Check whether compression should be triggered.

        Triggers when the usage percentage meets or exceeds the
        configured threshold, OR when the remaining tokens are
        below the configured reserve (not enough room for a
        reasonable response).

        Args:
            usage: Current context usage snapshot.

        Returns:
            True if compression is recommended.
        """
        if usage.percentage >= self._config.context_compression_threshold:
            return True
        if (
            usage.available_tokens > 0
            and usage.available_tokens
            <= self._config.context_compression_reserve
        ):
            return True
        return False

    async def compress(
        self,
        messages: list[dict[str, Any]],
        llm: Any,
        context_window: int,
        reserve: int,
        tool_tokens: int = 0,
    ) -> CompressionResult:
        """Compress context by summarizing older messages via LLM.

        Keeps the system prompt and most recent messages, summarizes
        everything in between using a non-streaming LLM call.

        Args:
            messages: Full message list (system + history).
            llm: LLM service with ``complete_nonstreaming`` method.
            context_window: Total context window in tokens.
            reserve: Tokens reserved for output generation.
            tool_tokens: Estimated tokens consumed by tool definitions
                (passed separately to the LLM but sharing the context
                window).  Subtracted from the target budget.

        Returns:
            CompressionResult with compressed messages and metadata.

        Raises:
            CompressionError: If the LLM returns an empty summary.
        """
        if len(messages) < 4:
            raise CompressionError("Not enough messages to compress")

        # Separate system prompt from conversation messages.
        system_msgs: list[dict[str, Any]] = []
        conv_msgs: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                system_msgs.append(m)
            else:
                conv_msgs.append(m)

        if len(conv_msgs) < 3:
            raise CompressionError(
                "Not enough conversation messages to compress",
            )

        # Target: keep enough recent messages to stay below 60% after
        # summary.  Tool definitions aren't in ``messages`` but still
        # occupy context window space, so we subtract them.
        target_tokens = int(context_window * 0.60) - reserve - tool_tokens
        keep_count = 0
        keep_tokens = sum(
            self.estimate_message_tokens(m) for m in system_msgs
        )

        for msg in reversed(conv_msgs):
            msg_tokens = self.estimate_message_tokens(msg)
            if keep_tokens + msg_tokens > target_tokens and keep_count >= 2:
                break
            keep_tokens += msg_tokens
            keep_count += 1

        keep_count = max(2, keep_count)
        split_index = len(conv_msgs) - keep_count
        if split_index < 1:
            raise CompressionError(
                "Cannot determine split point for compression",
            )

        to_archive = conv_msgs[:split_index]
        to_keep = conv_msgs[split_index:]

        # Build summary prompt including any prior summaries.
        archive_text_parts: list[str] = []
        for m in to_archive:
            role = m.get("role", "unknown")
            content = m.get("content") or ""
            if (
                m.get("is_context_summary")
                or content.startswith("[Context summary of ")
            ):
                archive_text_parts.append(f"[Previous summary]: {content}")
            elif role == "tool" and len(content) > 800:
                # Truncate large tool results for summary input.
                archive_text_parts.append(
                    f"[tool]: {content[:800]}... [truncated]",
                )
            elif content:
                archive_text_parts.append(f"[{role}]: {content}")

        archive_text = "\n".join(archive_text_parts)
        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "You are a context compression assistant. Summarize "
                    "the following conversation excerpt concisely, "
                    "preserving key facts, decisions, and context needed "
                    "for continuation. Output ONLY the summary, no "
                    "preamble."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Summarize this conversation for context "
                    f"retention:\n\n{archive_text}"
                ),
            },
        ]

        logger.info(
            "Compressing context: archiving {} messages, keeping {}",
            split_index, keep_count,
        )

        summary_text = await llm.complete_nonstreaming(
            summary_prompt, max_tokens=512,
        )
        if not summary_text.strip():
            raise CompressionError("LLM returned empty summary")

        # Build compressed message list.
        full_summary_content = (
            f"[Context summary of {split_index} earlier "
            f"messages]:\n{summary_text}"
        )
        summary_msg: dict[str, Any] = {
            "role": "assistant",
            "content": full_summary_content,
        }
        compressed = system_msgs + [summary_msg] + to_keep

        usage = self.get_usage_estimated(compressed, context_window)
        # Tool definitions aren't in messages but share the context
        # window — add them back so the returned usage is realistic.
        if tool_tokens > 0:
            usage.used_tokens += tool_tokens
            usage.available_tokens = max(
                0, context_window - usage.used_tokens,
            )
            usage.percentage = (
                round(usage.used_tokens / context_window, 4)
                if context_window > 0 else 0.0
            )
        usage.was_compressed = True
        usage.messages_summarized = split_index

        return CompressionResult(
            messages=compressed,
            usage=usage,
            split_index=split_index,
            summary_text=summary_text,
        )
