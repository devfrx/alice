"""Plugin whiteboard — crea e gestisce lavagne interattive tldraw."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from backend.core.config import PROJECT_ROOT
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult

from .models import SimpleShape, WhiteboardPayload, WhiteboardSpec
from .shape_builder import build_snapshot, merge_shapes_into_snapshot
from .store import WhiteboardStore

if TYPE_CHECKING:
    from backend.core.context import AppContext


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
            "description": "Testo da mostrare dentro la shape.",
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
            "description": "Filtra per ID conversazione (opzionale).",
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

    def __init__(self) -> None:
        super().__init__()
        self._store: WhiteboardStore | None = None

    @property
    def store(self) -> WhiteboardStore | None:
        """Accesso pubblico al whiteboard store."""
        return self._store

    async def initialize(self, ctx: "AppContext") -> None:
        await super().initialize(ctx)
        cfg = ctx.config.whiteboard
        if not cfg.enabled:
            self.logger.info("Plugin whiteboard disabilitato dalla configurazione.")
            return
        board_dir = PROJECT_ROOT / cfg.whiteboard_output_dir
        self._store = WhiteboardStore(board_dir)
        self.logger.info(f"WhiteboardPlugin inizializzato (dir={board_dir})")

    async def cleanup(self) -> None:
        self._store = None
        await super().cleanup()

    def get_tools(self) -> list[ToolDefinition]:
        if not self.ctx.config.whiteboard.enabled:
            return []
        return [
            ToolDefinition(
                name="create",
                description=(
                    "Crea una nuova lavagna tldraw. Fornisci shapes per popolarla "
                    "subito (flowchart, mindmap, schemi). Le coordinate (x,y) devono "
                    "essere assolute in pixel; usa spacing di ~250px tra nodi collegati."
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
                    "il contenuto corrente."
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
                    "fornite. Usa add_shapes se vuoi solo aggiungere."
                ),
                parameters=_UPDATE_SCHEMA,
                risk_level="medium",
                requires_confirmation=False,
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="list",
                description=(
                    "Elenca le lavagne disponibili, opzionalmente filtrate per conversazione. "
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
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Crea una nuova lavagna, opzionalmente pre-popolata."""
        cfg = self.ctx.config.whiteboard
        count = await self._store.count()
        if count >= cfg.max_boards:
            return ToolResult.error(
                f"Limite massimo di lavagne raggiunto ({cfg.max_boards}). "
                "Usa `whiteboard_delete` per eliminare lavagne non più necessarie."
            )

        board_id = str(uuid4())
        now = datetime.now(timezone.utc)

        # Parsing shapes opzionali
        raw_shapes = args.get("shapes", [])
        shapes = [SimpleShape(**s) for s in raw_shapes] if raw_shapes else []
        snapshot = build_snapshot(shapes) if shapes else build_snapshot([])

        conversation_id = args.get("conversation_id") or context.conversation_id

        spec = WhiteboardSpec(
            board_id=board_id,
            title=args["title"],
            description=args.get("description", ""),
            conversation_id=conversation_id,
            snapshot=snapshot,
            created_at=now,
            updated_at=now,
        )
        await self._store.save(spec)
        self.logger.info(
            f"Whiteboard '{spec.title}' creata (id={board_id}, shapes={len(shapes)})"
        )

        payload = WhiteboardPayload(
            board_id=board_id,
            title=spec.title,
            board_url=f"/api/whiteboards/{board_id}",
            conversation_id=conversation_id,
            created_at=now,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _get(
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Recupera il contenuto completo di una lavagna in formato leggibile."""
        board_id = args["board_id"]
        spec = await self._store.load(board_id)
        if spec is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")

        # Extract shapes from the tldraw snapshot in a readable format
        shapes_info = _extract_shapes_summary(spec.snapshot)

        result = {
            "board_id": spec.board_id,
            "title": spec.title,
            "description": spec.description,
            "conversation_id": spec.conversation_id,
            "created_at": spec.created_at.isoformat() if spec.created_at else None,
            "updated_at": spec.updated_at.isoformat() if spec.updated_at else None,
            "shapes": shapes_info,
            "shape_count": len(shapes_info),
        }
        return ToolResult.ok(
            json.dumps(result, ensure_ascii=False, default=str),
        )

    async def _add_shapes(
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Aggiunge shapes a una lavagna esistente senza rimpiazzare."""
        board_id = args["board_id"]
        existing = await self._store.load(board_id)
        if existing is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")

        raw_shapes = args["shapes"]
        new_shapes = [SimpleShape(**s) for s in raw_shapes]

        existing.snapshot = merge_shapes_into_snapshot(
            existing.snapshot, new_shapes
        )
        existing.updated_at = datetime.now(timezone.utc)
        await self._store.update(board_id, existing)

        self.logger.info(
            f"Whiteboard '{existing.title}' aggiornata: +{len(new_shapes)} shapes"
        )

        payload = WhiteboardPayload(
            board_id=board_id,
            title=existing.title,
            board_url=f"/api/whiteboards/{board_id}",
            conversation_id=existing.conversation_id,
            created_at=existing.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _update(
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Sovrascrive completamente il contenuto di una lavagna."""
        board_id = args["board_id"]
        existing = await self._store.load(board_id)
        if existing is None:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")

        raw_shapes = args["shapes"]
        shapes = [SimpleShape(**s) for s in raw_shapes]
        existing.snapshot = build_snapshot(shapes)
        existing.updated_at = datetime.now(timezone.utc)

        if "title" in args:
            existing.title = args["title"]

        await self._store.update(board_id, existing)
        self.logger.info(f"Whiteboard '{existing.title}' sovrascritta (id={board_id})")

        payload = WhiteboardPayload(
            board_id=board_id,
            title=existing.title,
            board_url=f"/api/whiteboards/{board_id}",
            conversation_id=existing.conversation_id,
            created_at=existing.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.whiteboard+json",
        )

    async def _list(
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Elenca le lavagne con paginazione e filtro opzionale."""
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        conversation_id = args.get("conversation_id")

        items = await self._store.list(
            limit=limit, offset=offset, conversation_id=conversation_id
        )
        total = await self._store.count()

        payload = {
            "boards": [item.model_dump(mode="json") for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult.ok(
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    async def _delete(
        self, args: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Elimina una lavagna dal disco."""
        board_id = args["board_id"]
        deleted = await self._store.delete(board_id)
        if not deleted:
            return ToolResult.error(f"Lavagna non trovata: {board_id}")
        return ToolResult.ok(f"Lavagna eliminata: {board_id}")
