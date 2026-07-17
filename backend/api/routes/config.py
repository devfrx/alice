"""AL\\CE — Configuration endpoints (read/update runtime config)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from backend.api.routes.config_reactions import (
    ALL_REACTIVE_PATHS,
    apply_reactions,
    diff_paths,
)
from backend.api.routes.config_schemas import ConfigResponse
from backend.api.routes.models import serialise_model
from backend.core.config import _REMOVED_LEGACY_PATHS, KNOWN_MODELS
from backend.core.context import AppContext
from backend.services.config_policy import is_preference_writable, is_secret_path
from backend.services.config_service import ConfigLayer

router = APIRouter(tags=["config"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


# ---------------------------------------------------------------------------
# Layered configuration endpoints (Phase 1 — Stream C)
# ---------------------------------------------------------------------------


_REDACT_KEYS: frozenset[str] = frozenset({
    "api_token", "token", "password", "secret", "api_key", "openrouter_api_key",
})


def _redact(node: Any) -> Any:
    """Return a deep copy of ``node`` with sensitive scalar values masked."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            lowered = key.lower() if isinstance(key, str) else key
            if (
                isinstance(lowered, str)
                and lowered in _REDACT_KEYS
                and isinstance(value, str)
                and value
            ):
                out[key] = "***"
            else:
                out[key] = _redact(value)
        return out
    if isinstance(node, list):
        return [_redact(item) for item in node]
    return node


def _resolved_dict(ctx: AppContext) -> dict[str, Any]:
    """Return the resolved config as a plain dict (with secrets redacted)."""
    cfg = ctx.config
    return _redact(cfg.model_dump(mode="json"))


@router.get("/config/resolved", response_model=dict[str, Any])
async def get_resolved_config(request: Request) -> dict[str, Any]:
    """Return the full merged-and-validated configuration (secrets redacted).

    Shape: the entire redacted ``AliceConfig`` — deliberately left as
    ``dict[str, Any]`` rather than pinned to a model (see ``ConfigResponse``
    for the narrower, stable ``GET /api/config`` contract).
    """
    return _resolved_dict(_ctx(request))


@router.get("/config/layers", response_model=dict[str, Any])
async def get_config_layers(request: Request) -> dict[str, Any]:
    """Return the raw per-layer dicts (defaults/system/user/runtime).

    Useful for diagnostics: shows exactly which layer contributes each
    value before the merge step.

    Shape: per-layer redacted config dicts — deliberately left as
    ``dict[str, Any]`` (not the stable ``ConfigResponse`` contract).
    """
    ctx = _ctx(request)
    if ctx.config_service is None:
        raise HTTPException(503, "Config service unavailable")
    layers = ctx.config_service.get_all_layers()
    return {name: _redact(data) for name, data in layers.items()}


@router.patch("/config", response_model=dict[str, Any])
async def patch_config(request: Request) -> dict[str, Any]:
    """Set a single dotted-path value in the chosen layer.

    Body schema::

        {
            "path":  "llm.temperature",     # dotted path, required
            "value": 0.9,                    # any JSON value
            "layer": "preferences"           # optional, default "preferences"
        }

    Allowed layers: ``preferences`` (default, persisted to the DB-backed
    preferences layer — policy-gated), ``user`` (persisted to user.yaml —
    power-user escape hatch), ``system`` (persisted to system.yaml — admin
    use), ``runtime`` (in-memory, lost on restart).  ``defaults`` is
    read-only.

    Shape: the full redacted ``AliceConfig`` (same as ``/config/resolved``)
    — deliberately left as ``dict[str, Any]``, not the ``ConfigResponse``
    contract.
    """
    ctx = _ctx(request)
    if ctx.config_service is None:
        raise HTTPException(503, "Config service unavailable")

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(400, "'path' must be a non-empty dotted string")
    if "value" not in body:
        raise HTTPException(400, "'value' is required")
    value = body["value"]

    raw_layer = body.get("layer", ConfigLayer.PREFERENCES.value)
    if not isinstance(raw_layer, str):
        raise HTTPException(400, "'layer' must be a string")
    try:
        layer = ConfigLayer(raw_layer.lower())
    except ValueError as exc:
        raise HTTPException(
            400,
            f"'layer' must be one of: preferences, user, system, runtime "
            f"(got '{raw_layer}')",
        ) from exc
    if layer is ConfigLayer.DEFAULTS:
        raise HTTPException(400, "'defaults' layer is read-only")

    try:
        await ctx.config_service.set(path, value, layer=layer)
    except ValidationError as exc:
        # include_context=False: ``value_error`` entries carry the raw
        # ValueError in ``ctx`` — not JSON-serializable in a response.
        raise HTTPException(
            422, exc.errors(include_url=False, include_context=False),
        ) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc

    ctx.config = ctx.config_service.get_resolved()
    await apply_reactions(ctx, {path})

    if ctx.ws_connection_manager is not None:
        try:
            await ctx.ws_connection_manager.broadcast({
                "type": "config.changed",
                "path": path,
                "value": value if not _is_sensitive_path(path) else "***",
                "layer": layer.value,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("config.changed broadcast failed: {}", exc)

    return _resolved_dict(ctx)


@router.post("/config/reload", response_model=dict[str, Any])
async def reload_config(request: Request) -> dict[str, Any]:
    """Re-read disk layers (defaults/system/user) and revalidate.

    Shape: the full redacted ``AliceConfig`` — deliberately left as
    ``dict[str, Any]``, not the ``ConfigResponse`` contract.
    """
    ctx = _ctx(request)
    if ctx.config_service is None:
        raise HTTPException(503, "Config service unavailable")
    try:
        ctx.config_service.reload()
        ctx.config = ctx.config_service.get_resolved()
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    return _resolved_dict(ctx)


def _is_sensitive_path(path: str) -> bool:
    """Heuristically detect dotted paths that point at a secret."""
    last = path.rsplit(".", 1)[-1].lower()
    return last in _REDACT_KEYS


@router.get("/config/models")
async def list_models(request: Request) -> list[dict[str, Any]]:
    """Fetch locally available models and return enriched metadata.

    Uses the LM Studio v1 API as primary source, falling back to
    OpenAI-compatible ``/v1/models`` or Ollama ``/api/tags``.
    """
    ctx = _ctx(request)

    # -- Primary: LM Studio v1 API ------------------------------------------
    mgr = ctx.lmstudio_manager
    if mgr is not None:
        try:
            data = await mgr.list_models()
            models = data.get("models", [])
            # Refresh the registry with fresh data.
            if ctx.model_registry is not None:
                await ctx.model_registry.refresh_from_api(models)
            return _models_from_v1(models, ctx.model_registry)
        except Exception:
            logger.debug("v1 API unavailable, falling back to legacy")

    # -- Fallback: legacy OpenAI-compat / Ollama ----------------------------
    return await _models_legacy(ctx)


def _models_from_v1(
    models: list[dict[str, Any]],
    registry: Any | None = None,
) -> list[dict[str, Any]]:
    """Map LM Studio v1 response to the frontend-expected shape."""
    return [
        serialise_model(m, registry)
        for m in models
    ]


async def _models_legacy(ctx: AppContext) -> list[dict[str, Any]]:
    """Fetch models via OpenAI-compatible or Ollama endpoint."""
    base_url = ctx.config.llm.base_url
    is_ollama = ctx.config.llm.provider == "ollama"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if is_ollama:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                raw_models = resp.json().get("models", [])
            else:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                raw_models = resp.json().get("data", [])
    except Exception:
        logger.debug("Failed to fetch models from {}", base_url)
        return []

    models: list[dict[str, Any]] = []
    for m in raw_models:
        name = m.get("id", "") or m.get("name", "")
        known = KNOWN_MODELS.get(name, {})
        models.append({
            "name": name,
            "display_name": name,
            "size": m.get("size", 0),
            "modified_at": m.get("modified_at", m.get("created", "")),
            "is_active": True,  # legacy providers always have their model loaded
            "loaded": True,
            "loaded_instances": [],
            "architecture": None,
            "quantization": None,
            "params_string": None,
            "format": None,
            "max_context_length": 0,
            "capabilities": {
                "vision": known.get("vision", False),
                "thinking": known.get("thinking", False),
                "trained_for_tool_use": False,
            },
        })
    return models


@router.get("/config", response_model=ConfigResponse)
async def get_config(request: Request) -> dict[str, Any]:
    """Return the current server configuration as JSON."""
    ctx = _ctx(request)
    cfg = ctx.config
    return {
        "llm": {
            "provider": cfg.llm.provider,
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "temperature": cfg.llm.temperature,
            "max_tokens": cfg.llm.max_tokens,
            "supports_thinking": cfg.llm.supports_thinking,
            "supports_vision": cfg.llm.supports_vision,
            "max_tool_iterations": cfg.llm.max_tool_iterations,
            "context_compression_enabled": cfg.llm.context_compression_enabled,
            "context_compression_threshold": cfg.llm.context_compression_threshold,
            "context_compression_reserve": cfg.llm.context_compression_reserve,
            "tool_rag_enabled": cfg.llm.tool_rag_enabled,
            "tool_rag_top_k": cfg.llm.tool_rag_top_k,
            "user_preferred_name": cfg.llm.user_preferred_name,
            "openrouter_api_key_configured": bool(
                cfg.llm.openrouter_api_key.get_secret_value(),
            ),
            "openrouter_model": cfg.llm.openrouter_model,
            "openrouter_favorites": list(cfg.llm.openrouter_favorites),
        },
        "stt": {
            "engine": cfg.stt.engine,
            "model": cfg.stt.model,
            "language": cfg.stt.language,
            "device": cfg.stt.device,
            "enabled": cfg.stt.enabled,
        },
        "tts": {
            "engine": cfg.tts.engine,
            "voice": cfg.tts.voice,
            "sample_rate": ctx.tts_service.sample_rate if ctx.tts_service else cfg.tts.sample_rate,
            "enabled": cfg.tts.enabled,
            "speed": cfg.tts.speed,
            "kokoro_model": cfg.tts.kokoro_model,
            "kokoro_voices": cfg.tts.kokoro_voices,
            "kokoro_voice": cfg.tts.kokoro_voice,
            "kokoro_language": cfg.tts.kokoro_language,
        },
        "ui": {
            "theme": cfg.ui.theme,
            "language": cfg.ui.language,
        },
        "voice": {
            "auto_tts_response": cfg.voice.auto_tts_response,
            "activation_mode": cfg.voice.activation_mode,
            "wake_word": cfg.voice.wake_word,
        },
        "pc_automation": {
            # Storage moved to the neutral ``permissions`` block in Fase 2;
            # the response keeps the historical shape for the settings UI.
            "confirmations_enabled": cfg.permissions.confirmations_enabled,
            "screenshot_lockout_s": cfg.pc_automation.screenshot_lockout_s,
        },
        "email": {
            "enabled": cfg.email.enabled,
            "imap_host": cfg.email.imap_host,
            "imap_port": cfg.email.imap_port,
            "imap_ssl": cfg.email.imap_ssl,
            "smtp_host": cfg.email.smtp_host,
            "smtp_port": cfg.email.smtp_port,
            "smtp_ssl": cfg.email.smtp_ssl,
            "username": cfg.email.username,
            "fetch_last_n": cfg.email.fetch_last_n,
            "max_fetch": cfg.email.max_fetch,
            "imap_idle_enabled": cfg.email.imap_idle_enabled,
            "archive_folder": cfg.email.archive_folder,
            "password_configured": bool(cfg.email.password.get_secret_value()),
            "service_running": ctx.email_service is not None,
        },
    }


def _flatten_update_body(body: dict[str, Any]) -> dict[str, Any]:
    """Flatten a nested update body into dotted LEAF paths (legacy aliases folded).

    Recurses into nested dicts at every depth, so a deeper body (e.g.
    ``{"agent": {"subagent": {"max_steps": 8}}}``) lands as leaf rows
    (``agent.subagent.max_steps``) in the preferences store instead of a
    dict-valued row that would overlap dotted rows persisted for the same
    subtree. PUT is therefore a per-leaf merge; subtree REPLACE semantics
    stay available via PATCH, whose value is stored as-is. An empty dict
    value flattens to nothing — a no-op, same effect the layer deep-merge
    would have had.

    Removed-legacy paths (``config.py``'s ``_REMOVED_LEGACY_PATHS`` — keys the
    system itself deprecated, e.g. ``email.use_keyring``) are dropped here
    rather than rejected: an older frontend build may still send them in every
    PUT body, and treating them as an unknown/non-writable path would 400 the
    whole request, blocking unrelated fields from saving.
    """
    flat: dict[str, Any] = {}

    def _walk(prefix: str, node: dict[str, Any]) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}"
            if isinstance(value, dict):
                _walk(path, value)
            else:
                flat[path] = value

    for section, updates in body.items():
        if not isinstance(updates, dict):
            raise HTTPException(400, f"'{section}' must be a JSON object")
        _walk(str(section), updates)
    # Historical alias — the UI still sends the pc_automation shape.
    if "pc_automation.confirmations_enabled" in flat:
        flat["permissions.confirmations_enabled"] = flat.pop(
            "pc_automation.confirmations_enabled"
        )
    dropped = [path for path in flat if path in _REMOVED_LEGACY_PATHS]
    if dropped:
        for path in dropped:
            flat.pop(path)
        logger.debug("PUT /api/config: dropped removed-legacy paths {}", sorted(dropped))
    return flat


@router.put("/config", response_model=ConfigResponse)
async def update_config(request: Request) -> dict[str, Any]:
    """Update configuration values (preferences layer + secrets).

    Body: partial nested config dict. Unknown/out-of-policy paths -> 400,
    invalid values -> 422, secrets routed to the SecretStore.
    """
    ctx = _ctx(request)
    if ctx.config_service is None:
        raise HTTPException(503, "Config service unavailable")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    flat = _flatten_update_body(body)

    secret_updates: dict[str, Any] = {}
    pref_updates: dict[str, Any] = {}
    rejected: list[str] = []
    for path, value in flat.items():
        if is_secret_path(path):
            secret_updates[path] = value
        elif is_preference_writable(path):
            pref_updates[path] = value
        else:
            rejected.append(path)
    if rejected:
        raise HTTPException(
            400, f"Unknown or non-writable config paths: {sorted(rejected)}",
        )

    # Pre-flight the secret half BEFORE any commit: a mixed body must not
    # persist a valid secret while the preference half fails validation
    # (or land preferences while the secret half 400s/503s).
    if secret_updates:
        if ctx.secret_store is None:
            raise HTTPException(
                503, "Secret store unavailable — secret values cannot be persisted",
            )
        _validate_secret_updates(secret_updates)

    old_config = ctx.config

    if pref_updates:
        try:
            await ctx.config_service.set_many(
                pref_updates, layer=ConfigLayer.PREFERENCES,
            )
        except ValidationError as exc:
            # include_context=False: ``value_error`` entries carry the raw
            # ValueError in ``ctx`` — not JSON-serializable in a response.
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False),
            ) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ctx.config = ctx.config_service.get_resolved()

    secret_changed = await _apply_secret_updates(ctx, secret_updates)

    changed = diff_paths(
        old_config, ctx.config, set(pref_updates) | ALL_REACTIVE_PATHS,
    ) | secret_changed
    await apply_reactions(ctx, changed)

    return await get_config(request)


_SECRET_MAX_LEN = 512


def _validate_secret_updates(updates: dict[str, Any]) -> None:
    """Reject invalid secret values before anything is committed.

    Pure check (no store I/O) so ``update_config`` can validate the whole
    mixed body — secrets AND preferences — before the first write lands.
    """
    for path, raw in updates.items():
        if raw is None:
            continue
        if len(str(raw).strip()) > _SECRET_MAX_LEN:
            raise HTTPException(400, f"{path} max {_SECRET_MAX_LEN} chars")


async def _apply_secret_updates(
    ctx: AppContext, updates: dict[str, Any],
) -> set[str]:
    """Apply secret writes (keyring semantics) and refresh ``ctx.config``.

    Uniform semantics for every path in ``updates`` (each MUST be a
    ``config_policy.SECRET_PATHS`` member): a non-empty string other than
    ``"***"`` sets the secret; ``""`` or ``"***"`` (the GET mask) is a
    no-op; ``None`` deletes it. When any secret actually changed, the
    config is rebuilt through the layered service so ``ctx.config``
    re-hydrates from the secret store instead of being mutated in place.

    The caller must have pre-flighted the batch — store present (503
    otherwise) and values valid (``_validate_secret_updates``) — BEFORE
    committing anything, so this apply step cannot fail a mixed request
    halfway through.

    Args:
        ctx: App context — reads/writes ``ctx.secret_store`` and rebuilds
            ``ctx.config`` via ``ctx.config_service``.
        updates: Mapping of dotted secret path -> raw request value.

    Returns:
        The set of dotted paths whose stored value actually changed.
    """
    changed: set[str] = set()
    if not updates:
        return changed
    store = ctx.secret_store
    assert store is not None, "update_config pre-flights the store before any commit"
    for path, raw in updates.items():
        assert is_secret_path(path), f"_apply_secret_updates: not a secret path: {path}"
        if raw is None:
            if store.cached().get(path):
                await store.delete(path)
                changed.add(path)
            continue
        value = str(raw).strip()
        if not value or value == "***":
            continue
        if value != store.cached().get(path):
            await store.set(path, value)
            changed.add(path)
    if changed and ctx.config_service is not None:
        ctx.config = await ctx.config_service.rebuild()
    return changed


@router.post("/config/sync-model")
async def sync_model(request: Request) -> dict[str, Any]:
    """Sync config with the model currently loaded in LM Studio.

    Queries LM Studio for loaded models.  If exactly one model is loaded
    and it differs from ``config.llm.model``, the config is updated
    automatically (model name, supports_thinking, supports_vision).

    Returns:
        ``{"synced": true, "model": "..."}`` on success, or
        ``{"synced": false, "reason": "..."}`` when no sync is needed.
    """
    ctx = _ctx(request)
    mgr = ctx.lmstudio_manager
    if mgr is None:
        return {"synced": False, "reason": "LM Studio manager not available"}

    try:
        data = await mgr.list_models()
    except Exception as exc:
        logger.warning("sync-model: cannot reach LM Studio — {}", exc)
        return {"synced": False, "reason": "LM Studio unreachable"}

    loaded = [
        m for m in data.get("models", [])
        if m.get("loaded_instances")
    ]

    if not loaded:
        return {"synced": False, "reason": "no model loaded"}

    cfg = ctx.config

    # When multiple models are loaded, check if the config model is among
    # them — that means the user intentionally loaded extras.
    if len(loaded) > 1:
        if any(m.get("key") == cfg.llm.model for m in loaded):
            return {"synced": False, "reason": "already in sync"}
        return {
            "synced": False,
            "reason": f"{len(loaded)} models loaded — ambiguous",
        }

    loaded_model = loaded[0]
    loaded_key = loaded_model.get("key", "")

    if not loaded_key:
        return {"synced": False, "reason": "loaded model has no key"}

    if loaded_key == cfg.llm.model:
        return {"synced": False, "reason": "already in sync"}

    # Resolve capabilities from live data, fallback to KNOWN_MODELS.
    live_caps = loaded_model.get("capabilities", {})
    known = KNOWN_MODELS.get(loaded_key, {})
    supports_thinking = live_caps.get(
        "thinking", known.get("thinking", False),
    )
    supports_vision = live_caps.get(
        "vision", known.get("vision", False),
    )

    if ctx.config_service is None:
        return {"synced": False, "reason": "config service unavailable"}

    # Preferences layer, NOT runtime: a runtime override on llm.model would
    # mask every later preferences write of the same path — and this is the
    # same value the FE snapshot would persist on its next diff-save anyway.
    # (The old in-place mutation was clobbered by the first config rebuild.)
    await ctx.config_service.set_many(
        {
            "llm.model": loaded_key,
            "llm.supports_thinking": supports_thinking,
            "llm.supports_vision": supports_vision,
        },
        layer=ConfigLayer.PREFERENCES,
    )
    ctx.config = ctx.config_service.get_resolved()

    # Invalidate auto-model cache so the next chat request uses the new model.
    if ctx.llm_service is not None:
        ctx.llm_service.invalidate_model_cache()

    logger.info(
        "sync-model: config updated to '{}' (thinking={}, vision={})",
        loaded_key, supports_thinking, supports_vision,
    )
    return {"synced": True, "model": loaded_key}
