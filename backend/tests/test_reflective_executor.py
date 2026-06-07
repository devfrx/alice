"""Tests for :class:`ReflectiveTurnExecutor`.

The reflective executor is the model-driven default wrapper: it delegates
the turn to a (mock) direct executor and, when reflection is enabled, runs
a single non-blocking critic pass that may emit ``agent.critic_invoked`` and
``agent.warning`` events. It must never alter the returned result.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

from backend.services.turn._reflection import ReflectionVerdict
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.reflective_executor import ReflectiveTurnExecutor


class RecordingSink:
    """Minimal sink that records every event sent to it."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def _ws(self) -> None:
        return None


class MockDirect:
    """Stub direct executor returning a fixed :class:`TurnResult`."""

    def __init__(self, default: TurnResult) -> None:
        self._default = default

    async def execute(
        self,
        turn: TurnInput,
        sink: Any,
        cancel_event: asyncio.Event,
        session: Any,
        channel: Any = None,
    ) -> TurnResult:
        return self._default


class MockCritic:
    """Stub reflection critic returning queued :class:`ReflectionVerdict`s."""

    def __init__(self, verdicts: list[ReflectionVerdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[dict[str, Any]] = []

    async def evaluate(
        self,
        *,
        output: str,
        finish_reason: str | None,
        goal: str,
        cancel_event: asyncio.Event | None = None,
    ) -> ReflectionVerdict:
        self.calls.append(
            {"output": output, "finish_reason": finish_reason, "goal": goal},
        )
        if self._verdicts:
            return self._verdicts.pop(0)
        return ReflectionVerdict(ok=True, reason="ok", source="llm")


def make_agent_turn() -> TurnInput:
    """Build a minimal :class:`TurnInput` for executor tests."""
    return TurnInput(
        conv_id=uuid.uuid4(),
        user_msg_id=uuid.uuid4(),
        user_content="richiesta",
        history=[],
        messages=[],
        tools=None,
        memory_context=None,
        cached_sys_prompt=None,
        attachment_info=None,
        context_window=8192,
        version_group_id=None,
        version_index=0,
        client_ip="127.0.0.1",
        resolved_max_tokens=None,
    )


def _cfg(*, enabled: bool, tool_turns_only: bool = True) -> Any:
    return SimpleNamespace(
        reflection=SimpleNamespace(
            enabled=enabled, tool_turns_only=tool_turns_only,
        ),
    )


def _result(
    *, content: str = "risposta", finish_reason: str = "stop",
    had_tool_calls: bool = True,
) -> TurnResult:
    return TurnResult(
        content=content,
        thinking="",
        input_tokens=0,
        output_tokens=0,
        finish_reason=finish_reason,
        had_tool_calls=had_tool_calls,
    )


async def _run(
    *,
    cfg: Any,
    result: TurnResult,
    verdicts: list[ReflectionVerdict] | None = None,
) -> tuple[TurnResult, RecordingSink, MockCritic]:
    direct = MockDirect(default=result)
    critic = MockCritic(verdicts or [])
    executor = ReflectiveTurnExecutor(direct=direct, critic=critic, cfg=cfg)
    sink = RecordingSink()
    out = await executor.execute(
        make_agent_turn(), sink, asyncio.Event(), session=None,
    )
    return out, sink, critic


def _event_types(sink: RecordingSink) -> set[str]:
    return {e.get("type") for e in sink.events}


# ---------------------------------------------------------------------------


async def test_reflection_disabled_skips_critic() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=False), result=_result(),
    )
    assert critic.calls == []
    assert sink.events == []
    assert out.content == "risposta"


async def test_reflection_skips_non_tool_turn_when_tool_only() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True, tool_turns_only=True),
        result=_result(had_tool_calls=False),
    )
    assert critic.calls == []
    assert sink.events == []


async def test_reflection_runs_on_tool_turn_verdict_ok() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True),
        result=_result(had_tool_calls=True),
        verdicts=[ReflectionVerdict(ok=True, reason="ok", source="llm")],
    )
    assert len(critic.calls) == 1
    assert "agent.critic_invoked" in _event_types(sink)
    assert "agent.warning" not in _event_types(sink)


async def test_reflection_warns_on_non_ok_verdict() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True),
        result=_result(had_tool_calls=True),
        verdicts=[
            ReflectionVerdict(ok=False, reason="degenerato", source="detector"),
        ],
    )
    types = _event_types(sink)
    assert "agent.critic_invoked" in types
    assert "agent.warning" in types
    warning = next(e for e in sink.events if e["type"] == "agent.warning")
    assert warning["code"] == "degenerated_output"


async def test_reflection_runs_every_turn_when_not_tool_only() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True, tool_turns_only=False),
        result=_result(had_tool_calls=False),
        verdicts=[ReflectionVerdict(ok=True, reason="ok", source="llm")],
    )
    assert len(critic.calls) == 1


async def test_reflection_skips_errored_turn() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True),
        result=_result(finish_reason="error", had_tool_calls=True),
    )
    assert critic.calls == []


async def test_reflection_skips_empty_content() -> None:
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True),
        result=_result(content="   ", had_tool_calls=True),
    )
    assert critic.calls == []


async def test_result_returned_unchanged() -> None:
    original = _result(content="originale", had_tool_calls=True)
    out, sink, critic = await _run(
        cfg=_cfg(enabled=True),
        result=original,
        verdicts=[ReflectionVerdict(ok=False, reason="x", source="llm")],
    )
    # Reflection never rewrites the answer.
    assert out.content == "originale"
    assert out is original
