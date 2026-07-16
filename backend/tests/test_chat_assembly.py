"""Focused tests for chat turn-assembly wiring helpers (Task 2.2).

Covers ``_coerce_tier_guidance`` — the tier-string → ``PermissionMode`` mapping
that feeds the user's per-tier guidance overrides into ``policy_for`` during
turn assembly.  The full ``TurnAssembler.assemble`` path requires a live DB
session + WebSocket + LLM stub harness, so the load-bearing wiring it adds
(custom guidance resolution) is verified here at the unit boundary and end to
end against ``policy_for``.
"""

from __future__ import annotations

from backend.api.routes.chat._assembly import (
    _coerce_tier_guidance,
    _resolve_output_budget,
)
from backend.core.config import LLMConfig
from backend.services.permission_mode_policy import policy_for
from backend.services.permission_mode_service import PermissionMode


class TestCoerceTierGuidance:
    def test_maps_known_tier_strings_to_modes(self) -> None:
        out = _coerce_tier_guidance(
            {
                "strict": "be careful",
                "plan": "read only",
                "auto_edits": "edit freely",
                "autopilot": "go",
            }
        )
        assert out == {
            PermissionMode.STRICT: "be careful",
            PermissionMode.PLAN: "read only",
            PermissionMode.AUTO_EDITS: "edit freely",
            PermissionMode.AUTOPILOT: "go",
        }

    def test_drops_unknown_keys(self) -> None:
        out = _coerce_tier_guidance({"bogus": "x", "plan": "p"})
        assert out == {PermissionMode.PLAN: "p"}

    def test_drops_empty_or_blank_values(self) -> None:
        out = _coerce_tier_guidance(
            {"strict": "", "plan": "   ", "autopilot": "go"}
        )
        assert out == {PermissionMode.AUTOPILOT: "go"}

    def test_none_and_empty_return_empty_dict(self) -> None:
        assert _coerce_tier_guidance(None) == {}
        assert _coerce_tier_guidance({}) == {}

    def test_result_feeds_policy_for_override(self) -> None:
        # End-to-end: the coerced mapping overrides the built-in guidance for
        # the keyed tier, and leaves un-keyed tiers on their defaults.
        custom = _coerce_tier_guidance({"plan": "CUSTOM PLAN GUIDANCE"})
        plan = policy_for(PermissionMode.PLAN, custom_guidance=custom)
        assert plan.guidance == "CUSTOM PLAN GUIDANCE"
        strict = policy_for(PermissionMode.STRICT, custom_guidance=custom)
        assert strict.guidance == policy_for(PermissionMode.STRICT).guidance


class TestResolveOutputBudget:
    def test_local_provider_gets_remaining_context_as_budget(self) -> None:
        cfg = LLMConfig(
            provider="lmstudio", max_tokens=-1,
            context_compression_reserve=2048,
        )
        assert _resolve_output_budget(cfg, available_tokens=10_000) == 7_952

    def test_local_provider_budget_floors_at_1024(self) -> None:
        cfg = LLMConfig(
            provider="lmstudio", max_tokens=-1,
            context_compression_reserve=2048,
        )
        assert _resolve_output_budget(cfg, available_tokens=100) == 1024

    def test_openrouter_never_derives_a_budget(self) -> None:
        # max_tokens is a hard output commitment on OpenRouter (validated
        # against the serving endpoint's real limits): with the global cap
        # unset the field must be omitted, not derived from the context
        # window.
        cfg = LLMConfig(provider="openrouter", max_tokens=-1)
        assert _resolve_output_budget(cfg, available_tokens=985_000) is None

    def test_explicit_global_cap_disables_derivation(self) -> None:
        # The client itself applies config.max_tokens when > 0.
        for provider in ("lmstudio", "ollama", "openrouter"):
            cfg = LLMConfig(provider=provider, max_tokens=4096)
            assert _resolve_output_budget(cfg, available_tokens=10_000) is None
