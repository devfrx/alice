"""run_headless_turn accetta un sink iniettato (default: NullEventSink)."""

from __future__ import annotations

import inspect

from backend.api.routes.chat.headless import run_headless_turn


def test_run_headless_turn_accepts_sink_kwarg() -> None:
    sig = inspect.signature(run_headless_turn)
    assert "sink" in sig.parameters
    param = sig.parameters["sink"]
    assert param.default is None
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
