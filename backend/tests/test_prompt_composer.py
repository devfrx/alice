"""Tests for the system-prompt dynamic-context composer."""

from __future__ import annotations

from backend.services.prompt_composer import (
    build_orchestration_block,
    compose_dynamic_context,
)


class TestBuildOrchestrationBlock:

    def test_none_when_no_fragments(self) -> None:
        assert build_orchestration_block([]) is None

    def test_none_when_only_blank_fragments(self) -> None:
        assert build_orchestration_block(["", "   "]) is None

    def test_renders_intro_and_bullets(self) -> None:
        block = build_orchestration_block(["Prima regola.", "Seconda regola."])
        assert block is not None
        assert block.startswith("[ORCHESTRAZIONE]\n")
        assert block.endswith("\n[/ORCHESTRAZIONE]")
        assert "- Prima regola.\n- Seconda regola." in block
        # The fixed intro line sits between the tag and the bullets.
        assert block.index("Regole vincolanti") < block.index("- Prima regola.")


class TestComposeDynamicContext:

    def test_none_when_everything_empty(self) -> None:
        assert compose_dynamic_context() is None
        assert compose_dynamic_context(permission_block="  ", aux_context="") is None

    def test_declared_order(self) -> None:
        out = compose_dynamic_context(
            permission_block="[AMBITO]",
            orchestration_block="[ORCHESTRAZIONE]",
            aux_context="[MEMORIE]",
            plan_document_block="[PIANO]",
            task_steps_block="[TASK]",
        )
        assert out == (
            "[AMBITO]\n\n[ORCHESTRAZIONE]\n\n[MEMORIE]\n\n[PIANO]\n\n[TASK]"
        )

    def test_empty_blocks_skipped(self) -> None:
        out = compose_dynamic_context(
            orchestration_block="[ORCHESTRAZIONE]",
            task_steps_block="[TASK]",
        )
        assert out == "[ORCHESTRAZIONE]\n\n[TASK]"
