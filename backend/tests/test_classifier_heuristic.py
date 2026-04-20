"""Heuristic pre-LLM short-circuit in :class:`ClassifierService`.

Patterns A/B/C must force ``MULTI_STEP`` *without* invoking the LLM.
"""

from __future__ import annotations

import pytest

from backend.services.agent import ClassifierConfig, ClassifierService, TaskComplexity

from ._recording_llm import RecordingLLM


_ASSERT_NO_LLM = "Heuristic must short-circuit before any LLM call"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        # Pattern A — search verb + artefact noun
        "Cerca le ultime news AI e salva un report.",
        "Trova i dati di vendita e generami un grafico.",
        "Search the latest Python news and create a chart.",
        "Ricerca informazioni sull'azienda Acme e crea una scheda riassuntiva.",
    ],
)
async def test_pattern_a_search_plus_artifact_forces_multi_step(prompt: str) -> None:
    """Search-verb + artefact-creation noun must short-circuit to MULTI_STEP."""
    llm = RecordingLLM(["trivial"])  # would be picked if heuristic missed
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    result = await svc.classify(prompt, has_tools=True)

    assert result == TaskComplexity.MULTI_STEP
    assert llm.calls == [], _ASSERT_NO_LLM


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        # Pattern B — two action verbs joined by a coordinator
        "Leggi il file e poi invia l'email.",
        "Apri il documento, quindi crea un riassunto.",
        "Read the report and then send the summary.",
        "Analizza i log e poi mostra i risultati.",
    ],
)
async def test_pattern_b_two_action_verbs_force_multi_step(prompt: str) -> None:
    """Two coordinated action verbs must force MULTI_STEP without an LLM call."""
    llm = RecordingLLM(["single_tool"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    result = await svc.classify(prompt, has_tools=True)

    assert result == TaskComplexity.MULTI_STEP
    assert llm.calls == [], _ASSERT_NO_LLM


@pytest.mark.asyncio
async def test_pattern_c_long_query_with_imperative_and_conjunction() -> None:
    """A >200 char query with at least one verb + a coordinator triggers MULTI_STEP."""
    prompt = (
        "Vorrei capire come è andata l'ultima campagna marketing del trimestre "
        "scorso e poi mi servirebbe avere un quadro generale dei risultati "
        "principali ottenuti dai vari team coinvolti durante tutto il progetto "
        "negli ultimi mesi."
    )
    assert len(prompt) > 200
    llm = RecordingLLM(["trivial"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    result = await svc.classify(prompt, has_tools=True)

    assert result == TaskComplexity.MULTI_STEP
    assert llm.calls == [], _ASSERT_NO_LLM


@pytest.mark.asyncio
async def test_short_unrelated_query_falls_through_to_llm() -> None:
    """Plain prompts without any pattern must reach the LLM normally."""
    llm = RecordingLLM(["trivial"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    result = await svc.classify("Ciao, come stai?", has_tools=False)

    assert result == TaskComplexity.TRIVIAL
    assert len(llm.calls) == 1, "LLM should be called for non-matching prompts"


@pytest.mark.asyncio
async def test_classify_detailed_marks_heuristic_source() -> None:
    """``classify_detailed`` must report ``source='heuristic'`` on a match."""
    llm = RecordingLLM(["trivial"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    detailed = await svc.classify_detailed(
        "Cerca le news AI e salva un report.", has_tools=True,
    )

    assert detailed.complexity == TaskComplexity.MULTI_STEP
    assert detailed.source == "heuristic"
    assert detailed.confidence == 1.0
    assert llm.calls == []
