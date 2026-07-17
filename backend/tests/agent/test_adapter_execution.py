"""Test ``ToolRegistryAdapter`` — risoluzione bare tool name (fix review T12).

Copre ``describe()`` (match esatto, unique-suffix fallback, ambiguità,
sconosciuto) e ``execute()`` (nessun pre-gate su ``exists``: delega sempre a
``execute_tool``, che risolve internamente). Il registry di piattaforma è uno
stub minimale (non un ``MagicMock``): espone solo ``tools`` (il dict namespaced
-> ``ToolDefinition`` letto da ``_tool_lookup.resolve_tool_definition``),
``get_tool_definition`` e ``execute_tool`` — le stesse API consumate
dall'adapter e dalla piattaforma reale (``backend/core/tool_registry.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.services.agent.adapters.execution import ToolRegistryAdapter
from backend.services.agent.models import ToolInvocation


class StubToolRegistry:
    """Stub minimale di ``ToolRegistry``: solo l'API pubblica che l'adapter consuma
    (``get_tool_definition``, ``get_all_tools``, ``execute_tool`` — niente stato
    privato, per restare fedele al contratto reale di ``core/tool_registry.py``).
    """

    def __init__(self, tools: dict[str, ToolDefinition]) -> None:
        self._tools_by_name = tools
        self.execute_calls: list[tuple[str, dict[str, Any], ExecutionContext]] = []
        self.execute_result: ToolResult = ToolResult.ok("ok")
        self.execute_delay_s: float = 0.0

    def get_tool_definition(self, name: str) -> ToolDefinition | None:
        return self._tools_by_name.get(name)

    def get_all_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {**td.to_openai_format()["function"], "name": ns_name},
            }
            for ns_name, td in self._tools_by_name.items()
        ]

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        self.execute_calls.append((tool_name, args, context))
        if self.execute_delay_s:
            await asyncio.sleep(self.execute_delay_s)
        return self.execute_result


def _call(name: str, args: dict[str, Any] | None = None) -> ToolInvocation:
    return ToolInvocation(call_id="call_1", name=name, args=args or {}, raw_args="{}")


def _registry_with(**tools: ToolDefinition) -> StubToolRegistry:
    return StubToolRegistry(tools=tools)


def _tool_def(name: str, *, timeout_ms: int = 30_000) -> ToolDefinition:
    return ToolDefinition(name=name, description="d", timeout_ms=timeout_ms)


def _adapter(registry: StubToolRegistry) -> ToolRegistryAdapter:
    return ToolRegistryAdapter(registry, default_timeout_s=5.0)


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


async def test_describe_exact_match() -> None:
    registry = _registry_with(memory_remember=_tool_def("remember"))
    adapter = _adapter(registry)

    meta = adapter.describe("memory_remember")

    assert meta.exists is True


async def test_describe_unique_suffix_match() -> None:
    registry = _registry_with(memory_remember=_tool_def("remember"))
    adapter = _adapter(registry)

    meta = adapter.describe("remember")

    assert meta.exists is True


async def test_describe_unknown_tool() -> None:
    registry = _registry_with(memory_remember=_tool_def("remember"))
    adapter = _adapter(registry)

    meta = adapter.describe("ghost")

    assert meta.exists is False


async def test_describe_ambiguous_suffix_does_not_resolve() -> None:
    registry = _registry_with(a_run=_tool_def("run"), b_run=_tool_def("run"))
    adapter = _adapter(registry)

    meta = adapter.describe("run")

    assert meta.exists is False


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


async def test_execute_bare_name_delegates_to_execute_tool() -> None:
    """Nessun pre-gate su ``exists``: execute() delega sempre, anche per bare name."""
    registry = _registry_with(memory_remember=_tool_def("remember"))
    registry.execute_result = ToolResult.ok("ricordato")
    adapter = _adapter(registry)

    output = await adapter.execute(
        _call("remember", {"text": "ciao"}), client_ip=None, conversation_id="c1",
    )

    assert len(registry.execute_calls) == 1
    called_name, called_args, _ctx = registry.execute_calls[0]
    assert called_name == "remember"  # l'adapter passa il nome as-is: risolto DENTRO execute_tool
    assert called_args == {"text": "ciao"}
    assert output.ok is True
    assert output.content == "ricordato"


async def test_execute_unknown_tool_still_delegates_no_short_circuit() -> None:
    """Anche per un nome davvero sconosciuto, execute() non intercetta prima:
    delega a execute_tool, che (nello stub come nella piattaforma reale) torna
    un ``ToolResult`` d'errore pulito senza sollevare.
    """
    registry = _registry_with(memory_remember=_tool_def("remember"))
    registry.execute_result = ToolResult.error("Tool 'ghost' not available: not found in registry")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("ghost"), client_ip=None, conversation_id="c1")

    assert len(registry.execute_calls) == 1
    assert registry.execute_calls[0][0] == "ghost"
    assert output.ok is False
    assert "not found" in (output.error or "")


async def test_execute_timeout_returns_ok_false_with_timeout_message() -> None:
    """Timeout per-tool (§6.13): ``asyncio.wait_for`` scade -> ``ToolExecutionOutput``
    ``ok=False`` con messaggio di timeout, MAI un'eccezione che risale — la call
    produce comunque una risposta sintetica pulita (§6.1: ramo "timeout")."""
    registry = _registry_with(slow=_tool_def("slow", timeout_ms=10))
    registry.execute_delay_s = 0.05
    adapter = _adapter(registry)

    output = await adapter.execute(_call("slow"), client_ip=None, conversation_id="c1")

    assert output.ok is False
    assert output.error is not None and "timeout" in output.error.lower()
