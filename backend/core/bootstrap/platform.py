"""AL\\CE — Bootstrap stage: platform services (Fase 5).

Orchestrator, layered configuration, model downloader, persisted user
preferences, and persisted plugin toggle state.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.core.context import AppContext
from backend.core.service_orchestrator import ServiceOrchestrator


async def stage_platform(ctx: AppContext, *, testing: bool) -> None:
    """Wire the platform group and apply persisted preferences/plugin state.

    Args:
        ctx: The application context being bootstrapped.
        testing: When ``True``, skip persisted-preferences / plugin-seed
            I/O (no DB round-trips in the test lifespan).
    """
    config = ctx.config

    # -- Service orchestrator ----------------------------------------------
    # Created early so concrete service constructors below can attach
    # themselves as they are instantiated.  Concrete services are still
    # started inline (legacy path); the orchestrator only owns health
    # polling, restarts, and the WS ``service.status`` event stream.
    orchestrator = ServiceOrchestrator(ctx.event_bus)
    ctx.orchestrator = orchestrator

    # -- Secret store (OS keyring) -------------------------------------------
    # Built before the config service so its synchronous ``cached()`` reader
    # can be passed straight in as the secrets provider.
    from backend.services.secret_store import create_secret_store

    secret_store = create_secret_store(prefer_memory=testing)
    if not testing:
        try:
            await secret_store.load_cache()
        except Exception as exc:  # noqa: BLE001 — keyring failure must not kill boot
            logger.warning("Secret cache load failed: {}", exc)
    ctx.secret_store = secret_store

    # -- Layered configuration service (defaults/system/user/runtime) -------
    # Built early so any subsequent service can read merged config through
    # ``ctx.config`` exactly as before.  The service rebuilds ``ctx.config``
    # whenever a layer mutation succeeds.
    from backend.services.config_service import LayeredConfigService

    config_service = LayeredConfigService(
        event_bus=ctx.event_bus,
        secrets_provider=secret_store.cached,
    )
    ctx.config_service = config_service
    ctx.config = config_service.get_resolved()
    config = ctx.config  # keep local alias in sync for the rest of this stage

    async def _refresh_ctx_config(**_kwargs: object) -> None:
        ctx.config = config_service.get_resolved()
        # A config change may switch the active model, which changes the
        # context window; drop the cached value so the next probe refreshes it.
        if getattr(ctx, "llm_service", None) is not None:
            ctx.llm_service.invalidate_context_window_cache()

    ctx.event_bus.subscribe("config.changed", _refresh_ctx_config)

    # -- Model downloader (STT/TTS) ----------------------------------------
    # Provides idempotent + resumable downloads of Whisper / Piper models
    # with progress events forwarded to the events WebSocket.
    from backend.services.model_downloader import PROGRESS_EVENT, ModelDownloader

    # In a PyInstaller --onedir bundle ``__file__`` lives inside ``_internal/``
    # which is read-only on Windows by user expectation; we keep models next to
    # ``backend.exe`` so the in-app downloader can write to them and bundled
    # defaults staged by ``build-installer.ps1`` are picked up automatically.
    if getattr(sys, "frozen", False):
        models_root = Path(sys.executable).resolve().parent / "models"
    else:
        models_root = PROJECT_ROOT / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    ctx.model_downloader = ModelDownloader(models_root, ctx.event_bus)

    async def _forward_download_progress(**kwargs: object) -> None:
        if ctx.ws_connection_manager is None:
            return
        await ctx.ws_connection_manager.broadcast({
            "type": PROGRESS_EVENT,
            **kwargs,
        })

    ctx.event_bus.subscribe(PROGRESS_EVENT, _forward_download_progress)

    # -- Load persisted user preferences ------------------------------------
    from backend.services.preferences_service import PreferencesLayerStore

    assert ctx.db is not None, "stage_database must run before stage_platform"
    session_factory = ctx.db

    preferences_store = PreferencesLayerStore(session_factory)
    ctx.preferences_store = preferences_store
    ctx.preferences_service = preferences_store  # legacy alias, dies in Task 11

    if not testing:
        from backend.services.config_migration import run_secret_migrations

        try:
            # 1. Load prefs ONCE for the migration's username source (the row
            #    may exist only in the DB, not in YAML).
            prefs = await preferences_store.load_all()
            email_username = str(
                prefs.get("email", {}).get("username", "") or config.email.username
            )

            # 2. Migrate legacy secrets (DB rows / YAML / legacy keyring name).
            await run_secret_migrations(
                secret_store, session_factory, config_service,
                email_username=email_username,
            )

            # 3. Load the preferences layer AND rebuild (replaces the bare
            #    ``rebuild()``) so migrated+pruned rows are what the layer
            #    sees, and future writes to the PREFERENCES layer persist
            #    through this same store.
            ctx.config = await config_service.load_preferences_layer(preferences_store)
            config = ctx.config

            # 4. RELOAD prefs (migration pruned secret/dead rows: the reloaded
            #    dict can no longer smear a raw string over a SecretStr field)
            #    and apply the legacy overlay onto the NEW resolved object.
            #    Double application of identical values is harmless now that
            #    the preferences layer and this overlay hold the same data;
            #    the overlay dies in Task 11.
            prefs = await preferences_store.load_all()
            preferences_store.apply_to_config(config, prefs)
        except Exception as exc:
            logger.warning("Failed to load persisted preferences: {}", exc)

    # -- Restore persisted plugin toggle states -----------------------------
    from backend.db.plugin_state import PluginStateRepository

    plugin_state_repo = PluginStateRepository(session_factory)
    ctx.plugin_state_repo = plugin_state_repo

    if not testing:
        try:
            # On first run: seed DB from default.yaml list.
            await plugin_state_repo.initialize_defaults(
                config.plugins.enabled
            )
            # Replace in-memory list with the persisted user choices.
            persisted = await plugin_state_repo.get_all()
            config.plugins.enabled = [
                name for name, enabled in persisted.items() if enabled
            ]
            logger.debug(
                "Plugin states restored from DB: enabled={}",
                config.plugins.enabled,
            )
        except Exception as exc:
            logger.warning("Failed to restore plugin states: {}", exc)
