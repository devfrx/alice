"""AL\\CE — CLI dell'eval harness: ``python -m backend.evals``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import keyring
from loguru import logger

from backend.evals.loader import SCENARIOS_DIR, load_scenarios
from backend.evals.report import load_report, render_text, save_report
from backend.evals.runner import PINNED_MODEL, run_suite

#: Directory di default degli output (gitignored).
DEFAULT_OUTPUT_DIR = Path("evals_output")


def build_parser() -> argparse.ArgumentParser:
    """Costruisce il parser: subcomandi ``run`` e ``list``."""
    parser = argparse.ArgumentParser(
        prog="python -m backend.evals",
        description="Eval harness agentico di AL\\CE (Fase 0 Agent v2).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Esegue la suite (modello pinnato via OpenRouter)")
    run.add_argument("--filter", default=None, help="Sottostringa degli id da eseguire")
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    run.add_argument("--no-judge", action="store_true", help="Salta il judge LLM")
    run.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="report.json di riferimento per il confronto",
    )

    sub.add_parser("list", help="Elenca gli scenari della suite")
    return parser


def resolve_api_key() -> str | None:
    """API key OpenRouter: env prima, poi Windows Credential Manager."""
    key = os.environ.get("ALICE_LLM__OPENROUTER_API_KEY")
    if key:
        return key
    try:
        return keyring.get_password("alice", "llm.openrouter_api_key")
    except Exception as exc:
        logger.warning("Lettura keyring fallita: {}", exc)
        return None


def _cmd_list() -> int:
    for scenario in load_scenarios(SCENARIOS_DIR):
        print(f"{scenario.id:28} {scenario.domain:12} {scenario.title}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Esegue la suite: forza l'ambiente PRIMA di ``create_app`` (via ``run_suite``).

    Note:
        Isolamento Qdrant (aggiunta sanzionata dalla review del Task 7): il
        lifespan in modalita' testing apre comunque l'embedded Qdrant reale
        (``data/qdrant``, ``QdrantConfig.path``) perche' ``stage_knowledge``
        non ha un flag testing dedicato. Un run eval con LLM vero
        scriverebbe quindi nel vector store dell'utente e contenderebbe il
        lock del file con un eventuale backend live. Per isolare il run
        settiamo (solo se non gia' presente in ambiente, cosi' l'utente puo'
        sempre override-are esplicitamente) ``ALICE_QDRANT__PATH`` sulla
        sottocartella ``qdrant`` dell'output dir del run: la memoria resta
        abilitata (gli scenari ``knowledge`` continuano a funzionare) ma
        scrive in uno store temporaneo per-run, mai in quello reale.
    """
    key = resolve_api_key()
    if not key:
        print(
            "ERRORE: nessuna API key OpenRouter (env ALICE_LLM__OPENROUTER_API_KEY "
            "o Credential Manager 'alice / llm.openrouter_api_key').",
            file=sys.stderr,
        )
        return 2
    os.environ["ALICE_LLM__OPENROUTER_API_KEY"] = key
    os.environ["ALICE_LLM__PROVIDER"] = "openrouter"
    os.environ["ALICE_LLM__OPENROUTER_MODEL"] = PINNED_MODEL

    scenarios = load_scenarios(SCENARIOS_DIR, filter_substring=args.filter)
    if not scenarios:
        print("Nessuno scenario selezionato.", file=sys.stderr)
        return 2

    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    output_dir = args.output / run_id

    # Isolamento Qdrant per-run (vedi docstring): mai il vector store reale.
    os.environ.setdefault("ALICE_QDRANT__PATH", str(output_dir / "qdrant"))

    report = asyncio.run(
        run_suite(
            scenarios,
            output_dir=output_dir,
            run_id=run_id,
            started_at=now.isoformat(timespec="seconds"),
            judge_enabled=not args.no_judge,
        ),
    )
    save_report(report, output_dir / "report.json")
    baseline = load_report(args.baseline) if args.baseline else None
    print(render_text(report, baseline))
    print(f"\nReport: {output_dir / 'report.json'}")
    return 0 if all(r.passed for r in report.scenarios) else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point della CLI."""
    # I titoli degli scenari contengono Unicode (→, accenti): su console
    # Windows cp1252 print() crasherebbe — forza UTF-8 quando possibile.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return _cmd_list()
    return _cmd_run(args)
