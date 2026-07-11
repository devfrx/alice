"""Plugin whiteboard — crea e gestisce lavagne interattive tldraw."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.db.models import ArtifactKind

from .models import SimpleShape, WhiteboardPayload, WhiteboardSpec
from .shape_builder import build_snapshot, merge_shapes_into_snapshot

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.artifacts import ArtifactRegistry


# -- Helpers ----------------------------------------------------------------

def _extract_shapes_summary(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a human-readable list of shapes from a tldraw snapshot."""
    store = snapshot.get("store", {})
    shapes: list[dict[str, Any]] = []
    for key, record in store.items():
        if not key.startswith("shape:"):
            continue
        props = record.get("props", {})
        info: dict[str, Any] = {
            "id": record.get("id", key),
            "type": record.get("type", "unknown"),
            "x": round(record.get("x", 0), 1),
            "y": round(record.get("y", 0), 1),
        }
        if props.get("text"):
            info["text"] = props["text"]
        if props.get("geo"):
            info["geo"] = props["geo"]
        if props.get("color") and props["color"] != "black":
            info["color"] = props["color"]
        if props.get("w"):
            info["w"] = round(props["w"], 1)
        if props.get("h"):
            info["h"] = round(props["h"], 1)
        # Arrow bindings are stored separately; include start/end if present
        if record.get("type") == "arrow":
            start = props.get("start")
            end = props.get("end")
            if isinstance(start, dict) and start.get("boundShapeId"):
                info["from_id"] = start["boundShapeId"]
            if isinstance(end, dict) and end.get("boundShapeId"):
                info["to_id"] = end["boundShapeId"]
        shapes.append(info)
    return shapes


def _parse_artifact_id(value: str) -> UUID | None:
    """Parse *value* as an artifact UUID; ``None`` when malformed."""
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


# -- JSON Schema per i tool ------------------------------------------------

_SIMPLE_SHAPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["geo", "note", "arrow", "text"],
            "description": (
                "Tipo shape: 'geo' (rettangolo, ellisse, diamante, esagono), "
                "'note' (sticky note colorata), 'arrow' (freccia tra nodi), "
                "'text' (testo libero)."
            ),
        },
        "id": {
            "type": "string",
            "description": (
                "ID univoco della shape (opzionale, auto-generato se omesso). "
                "Usalo per collegare frecce tramite from_id/to_id."
            ),
        },
        "x": {
            "type": "number",
            "description": "Posizione X in pixel (coordinate assolute). Default: 0.",
        },
        "y": {
            "type": "number",
            "description": "Posizione Y in pixel (coordinate assolute). Default: 0.",
        },
        "w": {
            "type": "number",
            "description": "Larghezza in pixel (default 200).",
        },
        "h": {
            "type": "number",
            "description": "Altezza in pixel (default 100).",
        },
        "text": {
            "type": "string",
            "description": (
                "Testo da mostrare dentro la shape. OBBLIGATORIO per geo, note e text — "
                "le shape senza testo vengono scartate automaticamente. "
                "Usa testo breve e chiaro (2-5 parole per nodo)."
            ),
        },
        "color": {
            "type": "string",
            "enum": ["cream", "sage", "amber", "steel", "coral", "lavender", "teal"],
            "description": "Colore della shape. Mappato alla palette AL\\CE.",
        },
        "from_id": {
            "type": "string",
            "description": "ID della shape di partenza (solo per type=arrow).",
        },
        "to_id": {
            "type": "string",
            "description": "ID della shape di destinazione (solo per type=arrow).",
        },
        "geo": {
            "type": "string",
            "enum": ["rectangle", "ellipse", "diamond", "hexagon"],
            "description": "Forma geometrica (solo per type=geo). Default: rectangle.",
        },
    },
    "required": ["type"],
}

_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Titolo della lavagna (max 255 caratteri).",
            "maxLength": 255,
        },
        "shapes": {
            "type": "array",
            "items": _SIMPLE_SHAPE_SCHEMA,
            "description": (
                "Shape iniziali da inserire nella lavagna. "
                "Usa coordinate (x,y) assolute in pixel con ~250px di spacing tra nodi collegati. "
                "Per flowchart: crea nodi geo con ID, poi frecce arrow con from_id/to_id."
            ),
        },
        "description": {
            "type": "string",
            "description": "Breve descrizione della lavagna.",
            "maxLength": 500,
        },
        "conversation_id": {
            "type": "string",
            "description": (
                "ID della conversazione associata (opzionale). "
                "Se omesso, viene associata automaticamente alla conversazione corrente."
            ),
        },
    },
    "required": ["title"],
}

_ADD_SHAPES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "board_id": {
            "type": "string",
            "description": "UUID della lavagna a cui aggiungere le shape.",
        },
        "shapes": {
            "type": "array",
            "items": _SIMPLE_SHAPE_SCHEMA,
            "minItems": 1,
            "description": "Shape da aggiungere alla lavagna esistente.",
        },
    },
    "required": ["board_id", "shapes"],
}

_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "board_id": {
            "type": "string",
            "description": "UUID della lavagna da sovrascrivere.",
        },
        "shapes": {
            "type": "array",
            "items": _SIMPLE_SHAPE_SCHEMA,
            "description": "Nuove shape che sostituiscono TUTTO il contenuto.",
        },
        "title": {
            "type": "string",
            "description": "Nuovo titolo (opzionale — omettere per mantenere il corrente).",
            "maxLength": 255,
        },
    },
    "required": ["board_id", "shapes"],
}

_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conversation_id": {
            "type": "string",
            "description": (
                "Filtra per ID conversazione. "
                "Se omesso, mostra automaticamente solo le lavagne "
                "della conversazione corrente."
            ),
        },
        "limit": {
            "type": "integer",
            "description": "Numero massimo di lavagne da restituire (default 20, max 100).",
            "default": 20,
            "minimum": 1,
            "maximum": 100,
        },
        "offset": {
            "type": "integer",
            "description": "Numero di lavagne da saltare per paginazione (default 0).",
            "default": 0,
            "minimum": 0,
        },
    },
}

_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "board_id": {
            "type": "string",
            "description": "UUID della lavagna da eliminare definitivamente.",
        },
    },
    "required": ["board_id"],
}

_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "board_id": {
            "type": "string",
            "description": "UUID della lavagna da leggere.",
        },
    },
    "required": ["board_id"],
}


class WhiteboardPlugin(BasePlugin):
    """Plugin per la creazione e gestione di lavagne interattive tldraw."""

    plugin_name: str = "whiteboard"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Crea e gestisce lavagne interattive tldraw. "
        "Usa per diagrammi, flowchart, mindmap, schemi architetturali e note visive."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    def _registry(self) -> ArtifactRegistry:
        registry = getattr(self.ctx, "artifact_registry", None)
        if registry is None:
            raise RuntimeError("Artifact registry non inizializzato.")
        return cast("ArtifactRegistry", registry)

    async def initialize(self, ctx: "AppContext") -> None:
        await super().initialize(ctx)
        if not ctx.config.whiteboard.enabled:
            self.logger.info("Plugin whiteboard disabilitato dalla configurazione.")
            return
        self.logger.info("WhiteboardPlugin inizializzato (registry-backed)")

    async def cleanup(self) -> None:
        await super().cleanup()

    def get_tools(self) -> list[ToolDefinition]:
        if self._ctx is None or not self._ctx.config.whiteboard.enabled:
            return []
        return [
            ToolDefinition(
                name="create",
                description=(
                    "Crea una nuova lavagna tldraw. Fornisci shapes per popolarla "
                    "subito (flowchart, mindmap, schemi). REGOLE DIAGRAMMI: "
                    "1) OGNI shape geo/note/text DEVE avere 'text' non vuoto — shape senza testo vengono scartate. "
                    "2) Testo breve: 2-5 parole per nodo, NO elenchi lunghi dentro una shape. "
                    "3) Usa coordinate (x,y) assolute con ~250px di spacing tra nodi collegati. "
                    "4) Dimensiona w/h in base al testo: min 120x60 per 2 parole, 200x80 per 3-5 parole. "
                    "5) NON creare shape decorative vuote — ogni shape deve comunicare informazione. "
                    "6) Max ~25 shape per lavagna per mantenere leggibilità."
                ),
                parameters=_CREATE_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=30_000,
            ),
            ToolDefinition(
                name="get",
                description=(
                    "Recupera il contenuto completo di una lavagna: titolo, descrizione, "
                    "lista di tutte le shape (tipo, posizione, testo, colore, connessioni). "
                    "Usa per ispezionare cosa contiene una lavagna prima di modificarla."
                ),
                parameters=_GET_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="add_shapes",
                description=(
                    "Aggiunge nuove shape a una lavagna esistente senza rimpiazzare "
                    "il contenuto corrente. REGOLE: ogni shape geo/note/text DEVE "
                    "avere 'text' non vuoto — shape senza testo vengono scartate."
                ),
                parameters=_ADD_SHAPES_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="update",
                description=(
                    "Sostituisce TUTTO il contenuto di una lavagna con le nuove shapes "
                    "fornite. Usa add_shapes se vuoi solo aggiungere. "
                    "REGOLE: ogni shape geo/note/text DEVE avere 'text' non vuoto. "
                    "Shape senza testo vengono scartate. Max ~25 shape."
                ),
                parameters=_UPDATE_SCHEMA,
                risk_level="medium",
                requires_confirmation=False,
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="list",
                description=(
                    "Elenca le lavagne della conversazione corrente (default). "
                    "Passa conversation_id per filtrare per una conversazione specifica. "
                    "Restituisce board_id, title, description, conversation_id e date."
                ),
                parameters=_LIST_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="delete",
                description=(
                    "Elimina definitivamente una lavagna dal disco. L'operazione è irreversibile."
                ),
                parameters=_DELETE_SCHEMA,
                risk_level="dangerous",
                requires_confirmation=True,
                timeout_ms=5_000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        if not self.ctx.config.whiteboard.enabled:
            return ToolResult.error("Plugin whiteboard non abilitato.")

        try:
            self._registry()
        except RuntimeError as exc:
            return ToolResult.error(str(exc))

        handlers = {
            "create": self._create,
            "get": self._get,
            "add_shapes": self._add_shapes,
            "update": self._update,
            "list": self._list,
            "delete": self._delete,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Tool sconosciuto: {tool_name}")
        return await handler(args, context)

    # -- Tool handlers ------------------------------------------------------

    async def _create(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Crea una nuova lavagna, opzionalmente pre-popolata."""
        title = (args.get("title") or "").strip()
        if not title:
            return ToolResult.error("Missing required parameter: title")

        cfg = self.ctx.config.whiteboard
        registry = self._registry()
        count = await registry.count_artifacts(kind=ArtifactKind.WHITEBOARD)
        if count >= cfg.max_boards:
            return ToolResult.error(
                f"Limite massimo di lavagne raggiunto ({cfg.max_boards}). "
                "Usa `whiteboard_delete` per eliminare lavagne non più necessarie."
            )

        aid = uuid4()
        now = datetime.now(timezone.utc)

        raw_shapes = args.get("shapes", [])
        shapes = [SimpleShape(**s) for s in raw_shapes] if raw_shapes else []
        snapshot = build_snapshot(shapes)

        conversation_id = _parse_artifact_id(
            args.get("conversation_id") or context.conversation_id or "",
        )

        spec = WhiteboardSpec(
            board_id=str(aid),
            title=title,
            description=args.get("description", ""),
            conversation_id=str(conversation_id) if conversation_id else None,
            snapshot=snapshot,
            created_at=now,
            updated_at=now,
        )
        await registry.create_json_artifact(
            kind=ArtifactKind.WHITEBOARD,
            title=title,
            content=spec.model_dump(mode="json"),
            conversation_id=conversation_id,
            metadata={"description": spec.description},
            artifact_id=aid,
        )
        self.logger.info(
            f"Whiteboard '{title}' creata (id={aid}, shapes={len(shapes)})"
        )

        payload = WhiteboardPayload(
            board_id=str(aid),
            title=title,
            board_url=f"/api/artifacts/{aid}/content",
            conversation_id=str(conversation_id) if conversation_id else None,
            created_at=now,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _get(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Recupera il contenuto completo di una lavagna in formato leggibile."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        result = await self._registry().read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, content = result

        snapshot = content.get("snapshot") or {}
        shapes_info = _extract_shapes_summary(
            snapshot if isinstance(snapshot, dict) else {},
        )
        out = {
            "board_id": str(artifact.id),
            "title": artifact.title,
            "description": content.get("description", ""),
            "conversation_id": (
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
            "shapes": shapes_info,
            "shape_count": len(shapes_info),
        }
        return ToolResult.ok(
            json.dumps(out, ensure_ascii=False, default=str),
            content_type="application/json",
        )

    async def _add_shapes(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Aggiunge shapes a una lavagna esistente senza rimpiazzare."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        result = await registry.read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, content = result

        raw_shapes = args.get("shapes")
        if not raw_shapes or not isinstance(raw_shapes, list):
            return ToolResult.error("Missing required parameter: shapes")
        new_shapes = [SimpleShape(**s) for s in raw_shapes]

        snapshot = content.get("snapshot")
        # A malformed blob degrades to a schema-less merge ({} snapshot) — acceptable edge.
        merged = merge_shapes_into_snapshot(
            snapshot if isinstance(snapshot, dict) else {}, new_shapes,
        )
        await registry.update_json_artifact(aid, content_patch={"snapshot": merged})
        self.logger.info(
            f"Whiteboard '{artifact.title}' aggiornata: +{len(new_shapes)} shapes"
        )

        payload = WhiteboardPayload(
            board_id=str(artifact.id),
            title=artifact.title,
            board_url=f"/api/artifacts/{artifact.id}/content",
            conversation_id=(
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            created_at=artifact.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _update(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Sovrascrive completamente il contenuto di una lavagna."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        result = await registry.read_json_content(aid)
        if result is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        artifact, _content = result

        raw_shapes = args.get("shapes")
        if not raw_shapes or not isinstance(raw_shapes, list):
            return ToolResult.error("Missing required parameter: shapes")
        shapes = [SimpleShape(**s) for s in raw_shapes]

        patch: dict[str, Any] = {"snapshot": build_snapshot(shapes)}
        new_title = args.get("title") if "title" in args else None
        if new_title is not None:
            patch["title"] = new_title
        updated = await registry.update_json_artifact(
            aid, content_patch=patch, title=new_title,
        )
        if updated is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        self.logger.info(f"Whiteboard '{updated.title}' sovrascritta (id={aid})")

        payload = WhiteboardPayload(
            board_id=str(updated.id),
            title=updated.title,
            board_url=f"/api/artifacts/{updated.id}/content",
            conversation_id=(
                str(updated.conversation_id)
                if updated.conversation_id else None
            ),
            created_at=artifact.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _list(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Elenca le lavagne con paginazione, scope default = conversazione corrente."""
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        # Default to current conversation to prevent cross-conversation leakage.
        conversation_id = _parse_artifact_id(
            args.get("conversation_id", context.conversation_id) or "",
        )

        registry = self._registry()
        items, total = await registry.list_artifacts(
            kind=ArtifactKind.WHITEBOARD,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
        boards = [
            {
                "board_id": str(a.id),
                "title": a.title,
                "description": str(a.artifact_metadata.get("description") or ""),
                "conversation_id": (
                    str(a.conversation_id) if a.conversation_id else None
                ),
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "shape_count": int(a.artifact_metadata.get("shape_count") or 0),
            }
            for a in items
        ]
        payload = {
            "boards": boards,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult.ok(json.dumps(payload, ensure_ascii=False, default=str))

    async def _delete(
        self, args: dict[str, Any], _context: ExecutionContext,
    ) -> ToolResult:
        """Elimina una lavagna (riga + blob)."""
        board_id = (args.get("board_id") or "").strip()
        aid = _parse_artifact_id(board_id)
        if aid is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        registry = self._registry()
        artifact = await registry.get_artifact(aid)
        if artifact is None or artifact.kind is not ArtifactKind.WHITEBOARD:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        deleted = await registry.delete_artifact(aid, delete_file=True)
        if not deleted:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        return ToolResult.ok(f"Lavagna eliminata: {board_id}")
