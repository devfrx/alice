"""AL\\CE — Streaming parser for reasoning tags.

Detects and separates thinking/reasoning blocks from regular content
in a streamed LLM response.  Case-insensitive matching ensures that
``<think>``, ``<Think>``, ``<THINK>`` (and the bracket variant) are
all recognized regardless of which model produces them.

Supported tag formats::

    <think>…</think>   — Qwen, DeepSeek-R1, QwQ, Nemotron, etc.
    [THINK]…[/THINK]   — Mistral reasoning models
"""

from __future__ import annotations

# Each entry: (open_tag, close_tag) — stored **lowercase**.
# Matching is always performed against a lowered copy of the buffer.
_TAG_FORMATS: list[tuple[str, str]] = [
    ("<think>", "</think>"),
    ("[think]", "[/think]"),
]


class ThinkTagParser:
    """Separate thinking blocks from regular content in a stream.

    Auto-detects which tag format the model uses on the first occurrence.
    Before detection, all candidate open-tag prefixes are held back to
    avoid emitting a partial tag as content.

    All tag matching is **case-insensitive** — ``<Think>``, ``<THINK>``,
    ``[think]`` etc. are all handled transparently.

    Example::

        parser = ThinkTagParser()
        for chunk in stream:
            for kind, text in parser.feed(chunk):
                if kind == "thinking":
                    yield {"type": "thinking", "content": text}
                else:
                    yield {"type": "token", "content": text}
        for kind, text in parser.flush():
            ...
    """

    def __init__(self) -> None:
        self._in_thinking: bool = False
        self._buffer: str = ""
        # None until the first open tag is found; then locked.
        self._open: str | None = None
        self._close: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, text: str) -> list[tuple[str, str]]:
        """Feed the next streamed chunk and extract tagged segments.

        Returns:
            A list of ``(kind, text)`` tuples where *kind* is
            ``"thinking"`` or ``"content"``.
        """
        self._buffer += text
        results: list[tuple[str, str]] = []

        while self._buffer:
            if self._open is None:
                # Tag format unknown yet — try to detect it.
                if not self._try_detect():
                    # No complete open tag found; hold back partial prefixes.
                    safe, held = self._split_at_any_partial_open(self._buffer)
                    if safe:
                        results.append(("content", safe))
                    self._buffer = held
                    break
                # Detected — fall through to normal parsing.

            tag = self._close if self._in_thinking else self._open
            assert tag is not None  # guaranteed after detection

            idx = self._buffer.lower().find(tag)
            if idx == -1:
                safe, held = self._split_at_partial(self._buffer, tag)
                if safe:
                    kind = "thinking" if self._in_thinking else "content"
                    results.append((kind, safe))
                self._buffer = held
                break

            if idx > 0:
                kind = "thinking" if self._in_thinking else "content"
                results.append((kind, self._buffer[:idx]))

            self._buffer = self._buffer[idx + len(tag):]
            self._in_thinking = not self._in_thinking

        return results

    def flush(self) -> list[tuple[str, str]]:
        """Flush any remaining buffered text after the stream ends."""
        if not self._buffer:
            return []

        kind = "thinking" if self._in_thinking else "content"
        result = [(kind, self._buffer)]
        self._buffer = ""
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_detect(self) -> bool:
        """Try to detect the tag format from the buffer.

        Searches for the earliest complete open tag among all candidates
        using case-insensitive matching.
        Returns True if a format was locked in.
        """
        lower_buf = self._buffer.lower()
        best_idx = len(self._buffer)
        best_fmt: tuple[str, str] | None = None
        for open_tag, close_tag in _TAG_FORMATS:
            idx = lower_buf.find(open_tag)
            if idx != -1 and idx < best_idx:
                best_idx = idx
                best_fmt = (open_tag, close_tag)
        if best_fmt is None:
            return False
        self._open, self._close = best_fmt
        return True

    @staticmethod
    def _split_at_any_partial_open(text: str) -> tuple[str, str]:
        """Hold back text that could be the start of any known open tag."""
        lower_text = text.lower()
        earliest = len(text)
        for open_tag, _ in _TAG_FORMATS:
            max_check = min(len(lower_text), len(open_tag) - 1)
            for length in range(max_check, 0, -1):
                if open_tag.startswith(lower_text[-length:]):
                    earliest = min(earliest, len(text) - length)
                    break
        return text[:earliest], text[earliest:]

    @staticmethod
    def _split_at_partial(text: str, tag: str) -> tuple[str, str]:
        """Split *text* so that a trailing prefix of *tag* is held back."""
        lower_text = text.lower()
        max_check = min(len(lower_text), len(tag) - 1)
        for length in range(max_check, 0, -1):
            if tag.startswith(lower_text[-length:]):
                return text[:-length], text[-length:]
        return text, ""
