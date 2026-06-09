"""Unit tests for :class:`LLMService` system-prompt assembly.

Covers the optional global persona block (Task T3) and the
:class:`AgentPromptsConfig` defaults.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.config import AgentPromptsConfig, LLMConfig
from backend.services.llm_service import LLMService

_BASE_PROMPT = "Sei AL\\CE."


def _service(tmp_path: Path) -> LLMService:
    """Build an ``LLMService`` whose base prompt is a known temp file."""
    prompt_file = tmp_path / "system_prompt.md"
    prompt_file.write_text(_BASE_PROMPT, encoding="utf-8")
    config = LLMConfig(
        system_prompt_enabled=True,
        system_prompt_file=str(prompt_file),
    )
    return LLMService(config)


# ---------------------------------------------------------------------------
# get_system_prompt — persona block
# ---------------------------------------------------------------------------


def test_persona_block_present_after_base(tmp_path: Path) -> None:
    """A truthy persona inserts the '## Istruzioni personalizzate' block."""
    service = _service(tmp_path)
    prompt = service.get_system_prompt(persona="Sii conciso.")

    assert "## Istruzioni personalizzate" in prompt
    assert "Sii conciso." in prompt
    # The persona block follows the base prompt text.
    assert prompt.index(_BASE_PROMPT) < prompt.index("## Istruzioni personalizzate")


def test_persona_block_precedes_memory_context(tmp_path: Path) -> None:
    """When both are present, the persona block sits before memory_context."""
    service = _service(tmp_path)
    memory = "## Memorie\n\nRicorda X."
    prompt = service.get_system_prompt(
        memory_context=memory, persona="Sii conciso."
    )

    assert "## Istruzioni personalizzate" in prompt
    assert "Sii conciso." in prompt
    assert memory in prompt
    assert prompt.index("Sii conciso.") < prompt.index(memory)


def test_temporal_precedes_persona_precedes_memory(tmp_path: Path) -> None:
    """Assembly order: temporal block -> persona block -> memory_context."""
    service = _service(tmp_path)
    memory = "## Memorie\n\nRicorda X."
    prompt = service.get_system_prompt(
        memory_context=memory, persona="Sii conciso."
    )

    temporal_idx = prompt.index("## Data e ora corrente")
    persona_idx = prompt.index("## Istruzioni personalizzate")
    memory_idx = prompt.index(memory)

    assert temporal_idx < persona_idx < memory_idx


def test_persona_none_identical_to_no_persona(tmp_path: Path) -> None:
    """persona=None must reproduce the prior output exactly (no block)."""
    service = _service(tmp_path)
    baseline = service.get_system_prompt()
    with_none = service.get_system_prompt(persona=None)

    assert with_none == baseline
    assert "## Istruzioni personalizzate" not in with_none


def test_persona_empty_string_identical_to_no_persona(tmp_path: Path) -> None:
    """persona='' is falsy and must not insert the block."""
    service = _service(tmp_path)
    baseline = service.get_system_prompt()
    with_empty = service.get_system_prompt(persona="")

    assert with_empty == baseline
    assert "## Istruzioni personalizzate" not in with_empty


def test_persona_with_memory_matches_baseline_when_falsy(tmp_path: Path) -> None:
    """A falsy persona leaves the memory_context path unchanged."""
    service = _service(tmp_path)
    memory = "## Memorie\n\nRicorda X."
    baseline = service.get_system_prompt(memory_context=memory)
    with_none = service.get_system_prompt(memory_context=memory, persona=None)

    assert with_none == baseline


# ---------------------------------------------------------------------------
# AgentPromptsConfig defaults
# ---------------------------------------------------------------------------


def test_agent_prompts_config_defaults() -> None:
    """The nested prompts model defaults to an empty persona / guidance."""
    cfg = AgentPromptsConfig()

    assert cfg.persona == ""
    assert cfg.tier_guidance == {}


def test_agent_config_has_prompts_attached() -> None:
    """``AgentConfig.prompts`` is an ``AgentPromptsConfig`` instance."""
    from backend.core.config import AgentConfig

    agent = AgentConfig()

    assert isinstance(agent.prompts, AgentPromptsConfig)
    assert agent.prompts.persona == ""
    assert agent.prompts.tier_guidance == {}
