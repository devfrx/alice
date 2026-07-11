"""Tests for backend.core.service_groups + AppContext thin root (Fase 5)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext, create_context
from backend.core.event_bus import EventBus
from backend.core.service_groups import (
    ConversationServices,
    InferenceServices,
    KnowledgeServices,
    PlatformServices,
    WorkspaceServices,
)


@pytest.fixture(scope="module")
def config():
    return load_config()


class TestConstruction:
    def test_create_context_builds_groups(self, config):
        ctx = create_context(config)
        assert isinstance(ctx.inference, InferenceServices)
        assert isinstance(ctx.knowledge, KnowledgeServices)
        assert isinstance(ctx.workspace, WorkspaceServices)
        assert isinstance(ctx.conversation, ConversationServices)
        assert isinstance(ctx.platform, PlatformServices)
        assert isinstance(ctx.event_bus, EventBus)
        assert ctx.config is config

    def test_legacy_kwargs_land_in_groups(self, config):
        lmstudio = MagicMock()
        ctx = AppContext(
            config=config, event_bus=EventBus(), lmstudio_manager=lmstudio,
        )
        assert ctx.inference.lmstudio_manager is lmstudio
        assert ctx.lmstudio_manager is lmstudio

    def test_db_kwarg_accepted(self, config):
        ctx = AppContext(config=config, event_bus=EventBus(), db=None)
        assert ctx.db is None
        assert ctx.conversation.db is None

    def test_unknown_kwarg_raises(self, config):
        with pytest.raises(TypeError):
            AppContext(config=config, event_bus=EventBus(), nonsense=1)


class TestFlatDelegation:
    """Every legacy flat name reads/writes through its group."""

    def test_flat_set_reaches_group(self, config):
        ctx = create_context(config)
        svc = MagicMock()
        ctx.llm_service = svc
        assert ctx.inference.llm_service is svc

    def test_group_set_reaches_flat(self, config):
        ctx = create_context(config)
        svc = MagicMock()
        ctx.knowledge.knowledge_service = svc
        assert ctx.knowledge_service is svc

    def test_event_bus_delegates_to_platform(self, config):
        ctx = create_context(config)
        assert ctx.event_bus is ctx.platform.event_bus

    def test_every_flat_field_roundtrips_into_its_group(self, config):
        """Roundtrip AND placement: a cross-group delegation typo would
        still roundtrip (non-slots dataclasses grow attributes silently),
        so each sentinel must land on a field DECLARED by the expected
        group — the executable form of the plan's field→group mapping."""
        from dataclasses import fields as dc_fields

        group_of: dict[str, str] = {}
        group_of.update(dict.fromkeys((
            "llm_service", "stt_service", "tts_service", "lmstudio_manager",
            "vram_monitor", "model_registry", "model_downloader",
            "embedding_client",
        ), "inference"))
        group_of.update(dict.fromkeys((
            "knowledge_service", "memory_service", "qdrant_service",
            "continuum_client", "rag_readiness",
        ), "knowledge"))
        group_of.update(dict.fromkeys((
            "scope_service", "permission_service", "permission_mode_service",
            "permission_rule_service", "terminal_session_manager",
        ), "workspace"))
        group_of.update(dict.fromkeys((
            "db", "engine", "context_manager", "plan_service",
            "plan_document_service", "artifact_registry",
        ), "conversation"))
        group_of.update(dict.fromkeys((
            "event_bus", "config_service", "ws_connection_manager",
            "plugin_manager", "tool_registry", "orchestrator",
            "plugin_state_repo", "preferences_service", "email_service",
            "plugin_local_state",
        ), "platform"))
        assert set(group_of) == set(AppContext.FLAT_FIELDS)

        ctx = create_context(config)
        for name in AppContext.FLAT_FIELDS:
            if name in ("event_bus", "plugin_local_state"):
                continue
            sentinel = object()
            setattr(ctx, name, sentinel)
            assert getattr(ctx, name) is sentinel, name
            group = getattr(ctx, group_of[name])
            declared = {f.name for f in dc_fields(group)}
            assert name in declared, f"{name} not declared on {group_of[name]}"
            assert getattr(group, name) is sentinel, name


class TestGroupSwap:
    def test_knowledge_group_atomic_swap(self, config):
        ctx = create_context(config)
        ctx.qdrant_service = MagicMock()
        new_group = KnowledgeServices(qdrant_service=MagicMock())
        old_group = ctx.knowledge
        ctx.knowledge = new_group
        assert ctx.knowledge is new_group
        assert ctx.qdrant_service is new_group.qdrant_service
        assert old_group is not new_group


class TestPluginState:
    async def test_get_set_plugin_state_still_work(self, config):
        ctx = create_context(config)
        await ctx.set_plugin_state("demo", "k", 1)
        assert dict(ctx.get_plugin_state("demo")) == {"k": 1}
        assert ctx.platform.plugin_local_state["demo"]["k"] == 1
