"""Focused tests for chat turn-assembly wiring helpers (Task 2.2).

Covers ``_coerce_tier_guidance`` — the tier-string → ``PermissionMode`` mapping
that feeds the user's per-tier guidance overrides into ``policy_for`` during
turn assembly.  The full ``TurnAssembler.assemble`` path requires a live DB
session + WebSocket + LLM stub harness, so the load-bearing wiring it adds
(custom guidance resolution) is verified here at the unit boundary and end to
end against ``policy_for``.
"""

from __future__ import annotations

from backend.api.routes.chat._assembly import _coerce_tier_guidance
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
