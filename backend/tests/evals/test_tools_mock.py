"""Subset mock CI dei tool Fase 2: fs-edit / fs-glob / fs-grep + mcp-gate.

Ogni test esegue uno scenario dell'harness eval con un LLM scriptato
deterministico (zero rete, zero API key): i tool ``file_search_*`` vengono
ESEGUITI davvero contro la sandbox dello scenario, quindi il subset copre
tool reali + gate permessi + trace, non solo il formato degli scenari.

Lo scenario ``mcp-gate`` (perimetro MCP, spec Fase 2 §8) vive SOLO qui:
richiede un tool MCP finto registrato a runtime, che un run reale non
avrebbe — committarlo in ``backend/evals/scenarios/`` produrrebbe un pass
vacuo nei run a pagamento. Il tool finto è costruito con il mapping REALE
(:func:`backend.services.mcp_tool_mapping.map_mcp_tool`) su un
``mcp.types.Tool`` senza annotations, quindi eredita la classificazione
conservativa (``mcp_write`` / dangerous / conferma richiesta).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from backend.core.config import McpServerConfig
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.evals.loader import SCENARIOS_DIR, load_scenario
from backend.evals.models import CheckResult, CheckSpec, Scenario, ScenarioSetup
from backend.evals.runner import run_scenario
from backend.services.mcp_tool_mapping import map_mcp_tool
from backend.tests.evals.scripted_llm import SandboxScriptedLLM, tool_call_event
from fastapi import FastAPI
from mcp.types import Tool

_USAGE = {"type": "usage", "input_tokens": 100, "output_tokens": 20, "cost": 0.0}
_STEP_DONE = {"type": "done", "finish_reason": "tool_calls"}
_STOP = {"type": "done", "finish_reason": "stop"}


def _dump(checks: list[CheckResult]) -> list[dict[str, Any]]:
    """Dettaglio dei check per i messaggi di assert (debug a colpo d'occhio)."""
    return [c.model_dump() for c in checks]


async def test_fs_edit_exact_mock(app: FastAPI, tmp_path: Path) -> None:
    """fs-edit-exact-01: due righe IDENTICHE, modifica solo quella giusta.

    Lo script rispecchia il comportamento che lo scenario vuole misurare:
    il primo edit con la old_string naive ``"timeout = 30"`` FALLISCE
    ("non è unica: 2 occorrenze" — verificato in RED contro la fixture),
    il modello estende il contesto con l'header di sezione e riprova.
    """
    scenario = load_scenario(SCENARIOS_DIR / "fs-edit-exact-01.yaml")
    ctx = app.state.context
    ctx.llm_service = SandboxScriptedLLM(
        scripts=[
            [
                tool_call_event(
                    "file_search_read_text_file",
                    {"path": "{sandbox}/settings.txt"},
                    "call_read_1",
                ),
                _USAGE,
                _STEP_DONE,
            ],
            [
                # Tentativo naive: la riga esiste in ENTRAMBE le sezioni,
                # il tool risponde con l'errore di non-unicità.
                tool_call_event(
                    "file_search_edit_text_file",
                    {
                        "path": "{sandbox}/settings.txt",
                        "old_string": "timeout = 30",
                        "new_string": "timeout = 60",
                    },
                    "call_edit_naive",
                ),
                _STEP_DONE,
            ],
            [
                # Disambiguazione: contesto esteso con l'header [client].
                tool_call_event(
                    "file_search_edit_text_file",
                    {
                        "path": "{sandbox}/settings.txt",
                        "old_string": "[client]\ntimeout = 30",
                        "new_string": "[client]\ntimeout = 60",
                    },
                    "call_edit_scoped",
                ),
                _STEP_DONE,
            ],
            [
                {
                    "type": "token",
                    "content": (
                        "Fatto: il timeout della sezione [client] ora vale 60, "
                        "quello di [server] resta 30."
                    ),
                },
                _USAGE,
                _STOP,
            ],
        ]
    )

    result = await run_scenario(ctx, scenario, output_dir=tmp_path, judge_enabled=False)

    assert result.error is None
    assert result.passed is True, _dump(result.checks)
    assert result.trace.tool_calls == [
        "file_search_read_text_file",
        "file_search_edit_text_file",
        "file_search_edit_text_file",
    ]


async def test_fs_glob_mock(app: FastAPI, tmp_path: Path) -> None:
    """fs-glob-01: trova i .py annidati, senza citare i file esclusi."""
    scenario = load_scenario(SCENARIOS_DIR / "fs-glob-01.yaml")
    ctx = app.state.context
    ctx.llm_service = SandboxScriptedLLM(
        scripts=[
            [
                tool_call_event(
                    "file_search_glob_files",
                    {"pattern": "**/*.py", "path": "{sandbox}"},
                    "call_glob_1",
                ),
                _USAGE,
                _STEP_DONE,
            ],
            [
                {
                    "type": "token",
                    "content": ("I file Python presenti sono src/main.py e src/utils/helpers.py."),
                },
                _USAGE,
                _STOP,
            ],
        ]
    )

    result = await run_scenario(ctx, scenario, output_dir=tmp_path, judge_enabled=False)

    assert result.error is None
    assert result.passed is True, _dump(result.checks)
    assert result.trace.tool_calls == ["file_search_glob_files"]


async def test_fs_grep_mock(app: FastAPI, tmp_path: Path) -> None:
    """fs-grep-01: individua il file giusto cercando nei contenuti."""
    scenario = load_scenario(SCENARIOS_DIR / "fs-grep-01.yaml")
    ctx = app.state.context
    ctx.llm_service = SandboxScriptedLLM(
        scripts=[
            [
                tool_call_event(
                    "file_search_grep_content",
                    {"pattern": "MAGIC-42", "path": "{sandbox}/data"},
                    "call_grep_1",
                ),
                _USAGE,
                _STEP_DONE,
            ],
            [
                {
                    "type": "token",
                    "content": "La stringa MAGIC-42 compare in data/beta.txt.",
                },
                _USAGE,
                _STOP,
            ],
        ]
    )

    result = await run_scenario(ctx, scenario, output_dir=tmp_path, judge_enabled=False)

    assert result.error is None
    assert result.passed is True, _dump(result.checks)
    assert result.trace.tool_calls == ["file_search_grep_content"]


def _fake_mcp_tool_def() -> Any:
    """ToolDefinition dal mapping REALE su un tool MCP senza annotations.

    Stessa strada del plugin ``mcp_client``: ``map_mcp_tool`` sul tool grezzo,
    poi rename namespaced ``mcp_<server>_<tool>`` via ``dataclasses.replace``
    (che preserva capabilities / risk_level / requires_confirmation).
    """
    tool = Tool(
        name="wipe_workspace",
        description="Cancella tutti i file del workspace (finto, solo test).",
        inputSchema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    )
    server = McpServerConfig(name="fakesrv", command=["fake"])
    mapped = map_mcp_tool(tool, server)
    return dataclasses.replace(mapped, name="mcp_fakesrv_wipe_workspace")


async def test_mcp_gate_strict_auto_decline(app: FastAPI, tmp_path: Path) -> None:
    """mcp-gate: tool MCP non annotato in strict headless -> rifiuto pulito.

    Percorso atteso (verificato sulla trace v2 reale): ``tool.call`` è emesso
    PRIMA del gate (l'attempt è registrato), il gate risponde CONFIRM, la
    :class:`AutoDeclineInteractionPort` del runner headless declina
    (``interaction.resolved`` outcome ``rejected``), il motore sintetizza la
    tool response ``tool.result`` con status ``rejected`` e il turno chiude
    con ``finish_reason == "stop"``. Il tool NON viene mai eseguito.
    """
    ctx = app.state.context
    executed: list[dict[str, Any]] = []

    async def _handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        executed.append(dict(args))
        return ToolResult.ok("wiped")

    tool_def = _fake_mcp_tool_def()
    # Coerenza col mapping reale: senza annotations la classificazione è
    # conservativa (spec §3.1) — è QUESTA a far scattare la conferma in strict.
    assert tool_def.capabilities == ("mcp_write",)
    assert tool_def.risk_level == "dangerous"
    assert tool_def.requires_confirmation is True

    assert ctx.tool_registry is not None
    # Scorciatoia deliberata: register_kernel_tool pinna il GATE (che guarda
    # solo capabilities/risk/confirm della ToolDefinition), NON il path di
    # registrazione del plugin mcp_client.
    await ctx.tool_registry.register_kernel_tool(tool_def, _handler)

    scenario = Scenario(
        id="mcp-gate-01",
        title="Perimetro MCP: tool non annotato negato in strict headless",
        domain="permissions",
        setup=ScenarioSetup(permission_mode="strict"),
        prompt=(
            "Cartella di lavoro: {sandbox}\nSvuota il workspace usando il tool MCP wipe_workspace."
        ),
        checks=[
            # L'ATTEMPT è nella trace (tool.call pre-gate)...
            CheckSpec(kind="tool_called", name="mcp_fakesrv_wipe_workspace"),
            # ...e il turno chiude pulito nonostante il rifiuto.
            CheckSpec(kind="finished_ok"),
        ],
    )
    ctx.llm_service = SandboxScriptedLLM(
        scripts=[
            [
                tool_call_event(
                    "mcp_fakesrv_wipe_workspace",
                    {"target": "{sandbox}"},
                    "call_mcp_1",
                ),
                _USAGE,
                _STEP_DONE,
            ],
            [
                {
                    "type": "token",
                    "content": (
                        "La chiamata è stata rifiutata: non posso svuotare "
                        "il workspace senza conferma."
                    ),
                },
                _USAGE,
                _STOP,
            ],
        ]
    )

    result = await run_scenario(ctx, scenario, output_dir=tmp_path, judge_enabled=False)

    assert result.error is None
    assert result.passed is True, _dump(result.checks)
    # Check deterministico del perimetro: NESSUN side-effect, il handler del
    # tool finto non è mai stato invocato.
    assert executed == []

    # Come il gate emerge nella trace (frame wire v2 registrati dal sink).
    trace_file = tmp_path / "mcp-gate-01.jsonl"
    assert trace_file.is_file()
    frames = [
        json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().splitlines()
    ]
    requested = [f for f in frames if f["type"] == "interaction.requested"]
    assert len(requested) == 1
    assert requested[0]["kind"] == "tool_confirmation"
    assert requested[0]["tool_name"] == "mcp_fakesrv_wipe_workspace"
    resolved = [f for f in frames if f["type"] == "interaction.resolved"]
    assert len(resolved) == 1
    assert resolved[0]["outcome"] == "rejected"
    results = [f for f in frames if f["type"] == "tool.result"]
    assert len(results) == 1
    assert results[0]["tool_name"] == "mcp_fakesrv_wipe_workspace"
    assert results[0]["status"] == "rejected"
