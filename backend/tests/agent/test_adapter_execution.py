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
from backend.core.tool_progress import current_progress_emitter, emit_tool_progress
from backend.services.agent.adapters.execution import ToolRegistryAdapter
from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import ToolImage


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


# ---------------------------------------------------------------------------
# guardia image/*: mai base64 grezzo verso il motore (I1 Fase 2 Mossa 1)
# ---------------------------------------------------------------------------


async def test_execute_image_result_becomes_placeholder() -> None:
    """Un ``ToolResult`` con ``content_type`` image/* NON passa il base64 al
    motore: ``content`` diventa un placeholder compatto (il base64 di uno
    screenshot vale ~33K token, un'immagine da 5 MiB ~1.75M — context bomb).
    Il ``content_type`` resta sull'output (il frame wire lo espone)."""
    b64 = "aGVsbG8td29ybGQ=" * 100  # payload base64 riconoscibile
    registry = _registry_with(fs_read=_tool_def("read_text_file"))
    registry.execute_result = ToolResult.ok(b64, content_type="image/png")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("fs_read"), client_ip=None, conversation_id="c1")

    assert output.ok is True
    assert b64 not in output.content
    assert "aGVsbG8" not in output.content
    assert "immagine" in output.content
    assert "image/png" in output.content
    assert "byte" in output.content
    assert len(output.content) < 300
    assert output.content_type == "image/png"


async def test_execute_image_placeholder_reports_decoded_size() -> None:
    """La size nel placeholder è quella dei byte DECODIFICATI (stima
    aritmetica dal base64), non la lunghezza della stringa base64."""
    import base64 as b64mod

    raw = b"\x89PNG" + b"\x00" * 996  # 1000 byte decodificati
    encoded = b64mod.b64encode(raw).decode("ascii")
    registry = _registry_with(shot=_tool_def("take_screenshot"))
    registry.execute_result = ToolResult.ok(encoded, content_type="image/png")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("shot"), client_ip=None, conversation_id="c1")

    assert "1.000 byte" in output.content or "1,000 byte" in output.content


async def test_execute_image_does_not_mutate_tool_result() -> None:
    """Il ``ToolResult`` originale della piattaforma resta INTEGRO
    (raw_content/audit non toccati): la guardia agisce solo sull'output
    verso il motore."""
    b64 = "QUJDREVGRw==" * 50
    result = ToolResult.ok(b64, content_type="image/png")
    registry = _registry_with(shot=_tool_def("take_screenshot"))
    registry.execute_result = result
    adapter = _adapter(registry)

    await adapter.execute(_call("shot"), client_ip=None, conversation_id="c1")

    assert result.content == b64
    assert result.content_type == "image/png"


async def test_execute_textual_result_passes_unchanged() -> None:
    """Un ``ToolResult`` testuale (non image/*) passa INVARIATO."""
    text = "contenuto testuale con /home/user e roba varia " * 20
    registry = _registry_with(fs_read=_tool_def("read_text_file"))
    registry.execute_result = ToolResult.ok(text, content_type="text/plain")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("fs_read"), client_ip=None, conversation_id="c1")

    assert output.ok is True
    assert output.content == text
    assert output.content_type == "text/plain"


# ---------------------------------------------------------------------------
# ToolImage: il base64 attraversa la porta fuori banda (T12 Fase 2 Mossa 2)
# ---------------------------------------------------------------------------


async def test_image_result_populates_images_and_placeholder() -> None:
    """Un ``ToolResult`` image/* riuscito popola ``images`` con il base64
    fuori banda (``ToolImage``); il placeholder in ``content`` resta INVARIATO
    (la guardia anti context-bomb non cambia)."""
    b64 = "aGVsbG8td29ybGQ=" * 100
    registry = _registry_with(shot=_tool_def("take_screenshot"))
    registry.execute_result = ToolResult.ok(b64, content_type="image/png")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("shot"), client_ip=None, conversation_id="c1")

    assert output.content.startswith("[immagine image/png")
    assert output.images == (ToolImage(mime="image/png", base64_data=b64),)


async def test_text_result_has_no_images() -> None:
    """Un ``ToolResult`` testuale non produce immagini: ``images`` resta ``()``."""
    registry = _registry_with(fs_read=_tool_def("read_text_file"))
    registry.execute_result = ToolResult.ok("testo", content_type="text/plain")
    adapter = _adapter(registry)

    output = await adapter.execute(_call("fs_read"), client_ip=None, conversation_id="c1")

    assert output.images == ()


async def test_failed_image_result_has_no_images() -> None:
    """``success=False`` con ``content_type`` image/* NON produce immagini:
    ``images`` vuoto e ``content`` segue il path errore attuale (invariato)."""
    b64 = "QUJDREVGRw==" * 50
    registry = _registry_with(shot=_tool_def("take_screenshot"))
    registry.execute_result = ToolResult(
        success=False, content=b64, content_type="image/png", error_message="boom",
    )
    adapter = _adapter(registry)

    output = await adapter.execute(_call("shot"), client_ip=None, conversation_id="c1")

    assert output.ok is False
    assert output.images == ()
    assert output.content == b64  # path errore attuale: nessuna guardia, nessuna immagine


# ---------------------------------------------------------------------------
# tool progress: ContextVar wiring (carry #1)
# ---------------------------------------------------------------------------


class _ProgressEmittingRegistry(StubToolRegistry):
    """``execute_tool`` chiama ``emit_tool_progress`` prima di ritornare, come
    farebbe un tool lungo (es. ``cad_generate_from_image``)."""

    def __init__(self, tools: dict[str, ToolDefinition], payload: dict[str, Any]) -> None:
        super().__init__(tools)
        self._payload = payload

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        await emit_tool_progress(self._payload)
        return await super().execute_tool(tool_name, args, context)


async def test_execute_forwards_tool_progress_to_on_progress() -> None:
    """(a) Un tool che chiama ``emit_tool_progress`` fa arrivare il payload alla
    callback ``on_progress`` passata dall'engine (ContextVar wired)."""
    registry = _ProgressEmittingRegistry(
        {"cad": _tool_def("cad")}, payload={"phase": "sampling", "percent": 25},
    )
    adapter = _adapter(registry)
    received: list[dict[str, Any]] = []

    async def _cb(payload: dict[str, Any]) -> None:
        received.append(payload)

    output = await adapter.execute(
        _call("cad"), client_ip=None, conversation_id="c1", on_progress=_cb,
    )

    assert received == [{"phase": "sampling", "percent": 25}]
    assert output.ok is True


async def test_execute_resets_context_var_after_return() -> None:
    """(b) Dopo il ritorno di ``execute`` il ContextVar è di nuovo None."""
    registry = _registry_with(cad=_tool_def("cad"))
    adapter = _adapter(registry)

    async def _cb(payload: dict[str, Any]) -> None:
        return None

    assert current_progress_emitter.get() is None
    await adapter.execute(
        _call("cad"), client_ip=None, conversation_id="c1", on_progress=_cb,
    )
    assert current_progress_emitter.get() is None


async def test_execute_resets_context_var_after_timeout() -> None:
    """(c) Il reset avviene anche quando la call va in timeout (ramo finally)."""
    registry = _registry_with(slow=_tool_def("slow", timeout_ms=10))
    registry.execute_delay_s = 0.05
    adapter = _adapter(registry)

    async def _cb(payload: dict[str, Any]) -> None:
        return None

    output = await adapter.execute(
        _call("slow"), client_ip=None, conversation_id="c1", on_progress=_cb,
    )

    assert output.ok is False
    assert current_progress_emitter.get() is None
