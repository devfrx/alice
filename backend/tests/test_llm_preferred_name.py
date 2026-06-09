"""The user's preferred name is injected into the system prompt env block."""

from __future__ import annotations

from pathlib import Path

from backend.core.config import LLMConfig
from backend.services.llm_service import LLMService


def _service(tmp_path: Path, name: str) -> LLMService:
    prompt_file = tmp_path / "system_prompt.md"
    prompt_file.write_text("Sei AL\\CE.", encoding="utf-8")
    config = LLMConfig(
        system_prompt_enabled=True,
        system_prompt_file=str(prompt_file),
        user_preferred_name=name,
    )
    return LLMService(config)


def test_preferred_name_present_in_system_prompt(tmp_path: Path) -> None:
    service = _service(tmp_path, "Marco")
    prompt = service.get_system_prompt()
    assert "Come preferisci essere chiamato" in prompt
    assert "Marco" in prompt


def test_no_name_omits_the_line(tmp_path: Path) -> None:
    service = _service(tmp_path, "")
    prompt = service.get_system_prompt()
    assert "Come preferisci essere chiamato" not in prompt
