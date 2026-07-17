"""AL\\CE — Runner dell'eval harness: boot app, scenari, suite."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from backend.core.app import create_app
from backend.evals.checks import evaluate_checks
from backend.evals.judge import judge_response
from backend.evals.models import JudgeVerdict, RunReport, Scenario, ScenarioResult, TraceSummary
from backend.evals.trace import summarize_trace, write_trace_jsonl

if TYPE_CHECKING:
    from backend.core.context import AppContext

#: Modello pinnato dei run ufficiali (spec Fase 0, scelto dall'utente).
PINNED_MODEL = "z-ai/glm-5.2"


@asynccontextmanager
async def eval_app() -> AsyncIterator[AppContext]:
    """Boota l'app in modalità testing (DB in-memory) e cede l'AppContext."""
    application = create_app(testing=True)
    async with application.router.lifespan_context(application):
        yield application.state.context


def _populate_sandbox(sandbox: Path, scenario: Scenario) -> None:
    """Crea i file di setup dentro *sandbox* (path traversal rifiutato)."""
    for spec in scenario.setup.sandbox:
        target = (sandbox / spec.path).resolve()
        if not target.is_relative_to(sandbox.resolve()):
            raise ValueError(f"setup path fuori sandbox: {spec.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.content, encoding="utf-8")


async def run_scenario(
    ctx: AppContext,
    scenario: Scenario,
    *,
    output_dir: Path,
    judge_enabled: bool = True,
) -> ScenarioResult:
    """Esegue UNO scenario contro l'app già bootata e ne valuta l'esito.

    Args:
        ctx: L'AppContext dell'app (da :func:`eval_app` o dai test).
        scenario: Lo scenario da eseguire.
        output_dir: Directory dove scrivere la trace JSONL.
        judge_enabled: Se ``False`` salta il judge anche quando lo scenario
            lo definisce.

    Returns:
        Lo :class:`ScenarioResult`; gli errori dell'harness (timeout,
        eccezioni) finiscono in ``error`` senza propagare.
    """
    from backend.api.routes.chat.headless import run_headless_turn
    from backend.db.models import Conversation
    from backend.services.permission_mode_service import PermissionMode
    from backend.services.turn.sink import RecordingEventSink

    sandbox = Path(tempfile.mkdtemp(prefix=f"alice-eval-{scenario.id}-"))
    started = time.perf_counter()
    sink = RecordingEventSink()
    try:
        _populate_sandbox(sandbox, scenario)

        if ctx.db is None:
            raise RuntimeError("DB non disponibile nell'app di eval")
        conv = Conversation(title=f"eval:{scenario.id}")
        async with ctx.db() as session:
            session.add(conv)
            await session.commit()
        conv_id = str(conv.id)

        if ctx.scope_service is not None:
            await ctx.scope_service.set_scope(conv_id, [str(sandbox)])
        if ctx.permission_mode_service is not None:
            mode = PermissionMode.coerce(
                scenario.setup.permission_mode,
                PermissionMode.AUTO_EDITS,
            )
            await ctx.permission_mode_service.set_mode(conv_id, mode)

        prompt = scenario.prompt.replace("{sandbox}", str(sandbox))
        result = await asyncio.wait_for(
            run_headless_turn(
                ctx,
                conversation_id=conv_id,
                prompt=prompt,
                origin="eval",
                sink=sink,
            ),
            timeout=scenario.budget.max_seconds,
        )

        if result is None:
            raise RuntimeError("run_headless_turn ha restituito None (assembly fallita)")

        trace = summarize_trace(
            sink.events,
            finish_reason=result.finish_reason,
            cost=result.cost,
        )
        response = result.content or ""
        check_results = evaluate_checks(
            scenario.checks,
            sandbox=sandbox,
            response=response,
            trace=trace,
        )
        verdicts: list[JudgeVerdict] = []
        if judge_enabled and scenario.judge is not None and ctx.llm_service is not None:
            verdicts = await judge_response(
                ctx.llm_service,
                spec=scenario.judge,
                task_prompt=prompt,
                response=response,
            )

        scenario_result = ScenarioResult(
            scenario_id=scenario.id,
            domain=scenario.domain,
            passed=all(c.passed for c in check_results),
            checks=check_results,
            judge=verdicts,
            trace=trace,
            response=response,
            duration_seconds=round(time.perf_counter() - started, 2),
        )
        write_trace_jsonl(
            output_dir / f"{scenario.id}.jsonl",
            sink.events,
            final=scenario_result.model_dump(),
        )
        return scenario_result
    except TimeoutError:
        logger.warning("Scenario {} in timeout ({}s)", scenario.id, scenario.budget.max_seconds)
        failed = ScenarioResult(
            scenario_id=scenario.id,
            domain=scenario.domain,
            passed=False,
            trace=TraceSummary(finish_reason="timeout"),
            duration_seconds=round(time.perf_counter() - started, 2),
            error=f"timeout dopo {scenario.budget.max_seconds}s",
        )
        with contextlib.suppress(Exception):
            write_trace_jsonl(
                output_dir / f"{scenario.id}.jsonl",
                sink.events,
                final=failed.model_dump(),
            )
        return failed
    except Exception as exc:
        logger.exception("Scenario {} fallito nell'harness", scenario.id)
        failed = ScenarioResult(
            scenario_id=scenario.id,
            domain=scenario.domain,
            passed=False,
            duration_seconds=round(time.perf_counter() - started, 2),
            error=str(exc),
        )
        with contextlib.suppress(Exception):
            write_trace_jsonl(
                output_dir / f"{scenario.id}.jsonl",
                sink.events,
                final=failed.model_dump(),
            )
        return failed
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


async def run_suite(
    scenarios: list[Scenario],
    *,
    output_dir: Path,
    run_id: str,
    started_at: str,
    model: str = PINNED_MODEL,
    judge_enabled: bool = True,
) -> RunReport:
    """Esegue la suite (seriale) dentro una singola app bootata.

    Args:
        scenarios: Gli scenari, già filtrati e ordinati dal chiamante.
        output_dir: Directory del run (trace + report).
        run_id: Identificativo del run (timestamp, dal chiamante).
        started_at: Timestamp ISO di inizio (dal chiamante).
        model: Nome del modello (solo metadato del report).
        judge_enabled: Propagato a ogni scenario.

    Returns:
        Il :class:`RunReport` completo (non ancora salvato su disco).
    """
    results: list[ScenarioResult] = []
    async with eval_app() as ctx:
        for scenario in scenarios:
            logger.info("Eval scenario {} ({})", scenario.id, scenario.domain)
            results.append(
                await run_scenario(
                    ctx,
                    scenario,
                    output_dir=output_dir,
                    judge_enabled=judge_enabled,
                ),
            )
    return RunReport(
        run_id=run_id,
        model=model,
        started_at=started_at,
        scenarios=results,
    )
