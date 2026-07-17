"""I double rispettano i contratti delle porte (structural typing)."""

import asyncio

from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation, ToolMeta
from backend.tests.agent.doubles import (
    MapExecutionPort,
    RecordingEventPort,
    ScriptedInteractionPort,
    ScriptedLLMPort,
)

CALL = ToolInvocation(call_id="c1", name="echo", args={}, raw_args="{}")


async def test_scripted_llm_yields_steps_in_order() -> None:
    port = ScriptedLLMPort(steps=[
        [ports.LLMTextDelta(text="ciao"),
         ports.LLMStepDone(finish_reason="stop", tool_calls=())],
    ])
    got = [e async for e in port.stream_step(
        system_prompt="s", messages=[], tools=[], max_tokens=None,
        cancel=asyncio.Event(),
    )]
    assert isinstance(got[0], ports.LLMTextDelta)
    assert isinstance(got[-1], ports.LLMStepDone)


async def test_map_execution_port_executes_and_describes() -> None:
    port = MapExecutionPort(tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")})
    assert port.describe("echo") == ToolMeta(exists=True)
    assert port.describe("nope").exists is False
    out = await port.execute(CALL, client_ip=None, conversation_id="c")
    assert out.ok and out.content == "hi"


async def test_recording_event_port_never_raises() -> None:
    port = RecordingEventPort()
    from backend.services.agent.events import TurnStartedEvent
    await port.emit(TurnStartedEvent(turn_id="t", conversation_id="c", source="chat"))
    assert len(port.events) == 1


async def test_scripted_interaction_confirm_returns_disconnected_as_data() -> None:
    port = ScriptedInteractionPort(confirm=ports.InteractionOutcome.DISCONNECTED)
    call = ToolInvocation(call_id="c1", name="t", args={}, raw_args="{}")
    verdict = ports.GateVerdict(action=ports.GateAction.CONFIRM, outcome="needs_confirmation")
    out = await port.confirm_tool(
        call, interaction_id="ix", verdict=verdict, timeout_s=1.0, cancel=asyncio.Event()
    )
    assert out is ports.InteractionOutcome.DISCONNECTED
