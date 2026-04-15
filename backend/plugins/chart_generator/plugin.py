"""Plugin chart_generator — genera, aggiorna e gestisce grafici ECharts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from backend.core.config import PROJECT_ROOT
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult

from .chart_store import ChartStore
from .models import ChartPayload, ChartSpec

if TYPE_CHECKING:
    from backend.core.context import AppContext

_GENERATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Titolo del grafico (max 255 caratteri).",
            "maxLength": 255,
        },
        "chart_type": {
            "type": "string",
            "description": (
                "Tipo principale del grafico. Esempi: bar, line, pie, scatter, "
                "radar, heatmap, sankey, candlestick, treemap, funnel."
            ),
        },
        "echarts_option": {
            "type": "object",
            "description": (
                "Configurazione Apache ECharts completa (option object). "
                "Deve includere almeno: series. NON includere 'title' in "
                "echarts_option: il titolo è già mostrato nell'header del viewer. "
                "REGOLA CRITICA per grafici cartesiani (bar/line): se hai N "
                "categorie sull'asse X, usa UNA SOLA series con N valori nel "
                "campo data. Esempio corretto per 3 metriche: "
                "xAxis.data=['CPU','RAM','Disco'], series=[{type:'bar', "
                "data:[11,83,75]}]. NON creare N series ognuna con 1 solo "
                "valore — ECharts le sovrappone tutte sulla prima categoria. "
                "Usa series multiple SOLO per confrontare dataset diversi "
                "sulle stesse categorie (es. 'Usato' vs 'Libero'). "
                "Il formato è identico alla documentazione ufficiale ECharts."
            ),
            "additionalProperties": True,
        },
        "description": {
            "type": "string",
            "description": "Breve descrizione della fonte dati e dello scopo del grafico.",
            "maxLength": 500,
        },
    },
    "required": ["title", "chart_type", "echarts_option"],
}

_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da aggiornare.",
        },
        "echarts_option": {
            "type": "object",
            "description": "Nuova configurazione ECharts completa che sostituisce la precedente. "
                "STRUTTURA: le chiavi top-level (xAxis, yAxis, series, tooltip, legend, grid, ecc.) "
                "devono essere chiavi dell'oggetto radice. "
                "legend NON va messa dentro series — è una chiave top-level separata. "
                "series contiene SOLO oggetti con type in: 'bar','line','pie','scatter','gauge','radar'. "
                "Esempio: {\"xAxis\":{\"data\":[...]}, \"yAxis\":{\"type\":\"value\"}, "
                "\"series\":[{\"type\":\"bar\",\"data\":[...]}], "
                "\"legend\":{\"data\":[\"serie1\"]}, \"tooltip\":{\"trigger\":\"axis\"}}",
            "additionalProperties": True,
        },
        "title": {
            "type": "string",
            "description": "Nuovo titolo (opzionale — omettere per mantenere il titolo corrente).",
            "maxLength": 255,
        },
    },
    "required": ["chart_id", "echarts_option"],
}

_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da recuperare.",
        },
    },
    "required": ["chart_id"],
}

_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "Numero massimo di grafici da restituire (default 20, max 100).",
            "default": 20,
            "minimum": 1,
            "maximum": 100,
        },
        "offset": {
            "type": "integer",
            "description": "Numero di grafici da saltare per paginazione (default 0).",
            "default": 0,
            "minimum": 0,
        },
    },
}

_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_id": {
            "type": "string",
            "description": "UUID del grafico da eliminare definitivamente.",
        },
    },
    "required": ["chart_id"],
}


class ChartGeneratorPlugin(BasePlugin):
    """Plugin per la generazione di grafici interattivi Apache ECharts."""

    plugin_name: str = "chart_generator"
    plugin_version: str = "1.0.0"
    plugin_description: str = "Genera grafici interattivi ECharts da qualsiasi fonte dati."
    plugin_dependencies: list[str] = []
    plugin_priority: int = 25

    def __init__(self) -> None:
        super().__init__()
        self._store: ChartStore | None = None

    @property
    def store(self) -> ChartStore | None:
        """Public access to the chart store."""
        return self._store

    async def initialize(self, ctx: "AppContext") -> None:
        await super().initialize(ctx)
        cfg = ctx.config.chart
        if not cfg.enabled:
            self.logger.info("Plugin chart_generator disabilitato dalla configurazione.")
            return
        chart_dir = PROJECT_ROOT / cfg.chart_output_dir
        self._store = ChartStore(chart_dir)
        self.logger.info(f"ChartGeneratorPlugin inizializzato (dir={chart_dir})")

    async def cleanup(self) -> None:
        self._store = None
        await super().cleanup()

    def get_tools(self) -> list[ToolDefinition]:
        if self._ctx is None or not self._ctx.config.chart.enabled:
            return []
        return [
            ToolDefinition(
                name="generate_chart",
                description=(
                    "Genera un grafico interattivo Apache ECharts e lo persiste su disco. "
                    "L'output viene visualizzato nella chat come viewer interattivo. "
                    "FLUSSO CORRETTO: (1) esegui web_search o recall per raccogliere i dati, "
                    "(2) costruisci l'echarts_option JSON direttamente in questo tool — "
                    "NON scrivere codice Python/pseudocodice: non esiste un interprete, "
                    "tutto il processing avviene dentro echarts_option. "
                    "REGOLE echarts_option: (1) series[].data deve avere la stessa lunghezza di xAxis/yAxis.data; "
                    "(2) non mischiare unità diverse nella stessa serie; "
                    "(3) NON includere 'title' — il titolo è già nell'header del viewer; "
                    "(4) pie chart: series[0].type='pie' con data=[{name,value}], no xAxis/yAxis."
                ),
                parameters=_GENERATE_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=30_000,
            ),
            ToolDefinition(
                name="update_chart",
                description=(
                    "Aggiorna la configurazione ECharts di un grafico esistente. "
                    "Usa il chart_id restituito da generate_chart o list_charts. "
                    "L'intera echarts_option viene sostituita con la nuova versione."
                ),
                parameters=_UPDATE_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15_000,
            ),
            ToolDefinition(
                name="get_chart",
                description=(
                    "Recupera i metadati e la echarts_option di un grafico salvato. "
                    "Utile per leggere un grafico esistente prima di aggiornarlo."
                ),
                parameters=_GET_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="list_charts",
                description=(
                    "Elenca i grafici persistiti nel vault, ordinati dal più recente. "
                    "Restituisce chart_id, title, chart_type, description e date."
                ),
                parameters=_LIST_SCHEMA,
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5_000,
            ),
            ToolDefinition(
                name="delete_chart",
                description=(
                    "Elimina definitivamente un grafico dal disco. L'operazione è irreversibile."
                ),
                parameters=_DELETE_SCHEMA,
                risk_level="medium",
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
        if not self.ctx.config.chart.enabled:
            return ToolResult.error("Plugin chart_generator non abilitato.")

        if self._store is None:
            return ToolResult.error("Chart store not initialized.")

        handlers = {
            "generate_chart": self._generate_chart,
            "update_chart": self._update_chart,
            "get_chart": self._get_chart,
            "list_charts": self._list_charts,
            "delete_chart": self._delete_chart,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(f"Tool sconosciuto: {tool_name}")
        return await handler(args)

    async def _generate_chart(self, args: dict[str, Any]) -> ToolResult:
        title = (args.get("title") or "").strip()
        if not title:
            return ToolResult.error("Missing required parameter: title")
        chart_type = (args.get("chart_type") or "").strip()
        if not chart_type:
            return ToolResult.error("Missing required parameter: chart_type")
        option = args.get("echarts_option")
        if not isinstance(option, dict):
            return ToolResult.error("Missing required parameter: echarts_option")

        cfg = self.ctx.config.chart
        count = await self._store.count()
        if count >= cfg.max_charts:
            return ToolResult.error(
                f"Limite massimo di grafici raggiunto ({cfg.max_charts}). "
                "Usa `delete_chart` per eliminare grafici non più necessari."
            )

        option_str = json.dumps(option, ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult.error(
                f"La echarts_option supera il limite di {cfg.max_option_chars} caratteri "
                f"(attuale: {len(option_str)}). Aggrega o riduci i dati prima di richiamare il tool."
            )

        chart_id = str(uuid4())
        now = datetime.now(timezone.utc)
        spec = ChartSpec(
            chart_id=chart_id,
            title=title,
            chart_type=chart_type,
            description=args.get("description", ""),
            echarts_option=option,
            created_at=now,
            updated_at=now,
        )
        await self._store.save(spec)
        self.logger.info(f"Grafico '{spec.title}' generato (id={chart_id}, type={spec.chart_type})")

        payload = ChartPayload(
            chart_id=chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            chart_url=f"/api/charts/{chart_id}",
            created_at=now,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.chart+json",
        )

    async def _update_chart(self, args: dict[str, Any]) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        if not chart_id:
            return ToolResult.error("Missing required parameter: chart_id")
        option = args.get("echarts_option")
        if not isinstance(option, dict):
            return ToolResult.error("Missing required parameter: echarts_option")
        existing = await self._store.load(chart_id)
        if existing is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")

        cfg = self.ctx.config.chart
        option_str = json.dumps(option, ensure_ascii=False)
        if len(option_str) > cfg.max_option_chars:
            return ToolResult.error(
                f"echarts_option supera il limite di {cfg.max_option_chars} caratteri."
            )

        existing.echarts_option = option
        existing.updated_at = datetime.now(timezone.utc)
        if "title" in args:
            existing.title = args["title"]

        await self._store.update(chart_id, existing)
        self.logger.info(f"Grafico aggiornato: {chart_id}")

        payload = ChartPayload(
            chart_id=chart_id,
            title=existing.title,
            chart_type=existing.chart_type,
            chart_url=f"/api/charts/{chart_id}",
            created_at=existing.created_at,
        )
        return ToolResult.ok(
            payload.model_dump_json(),
            content_type="application/vnd.alice.chart+json",
        )

    async def _get_chart(self, args: dict[str, Any]) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        if not chart_id:
            return ToolResult.error("Missing required parameter: chart_id")
        spec = await self._store.load(chart_id)
        if spec is None:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        return ToolResult.ok(spec.model_dump_json())

    async def _list_charts(self, args: dict[str, Any]) -> ToolResult:
        limit = min(int(args.get("limit", 20)), 100)
        offset = max(int(args.get("offset", 0)), 0)
        items = await self._store.list(limit=limit, offset=offset)
        total = await self._store.count()
        payload = {
            "charts": [item.model_dump(mode="json") for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
        return ToolResult.ok(
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    async def _delete_chart(self, args: dict[str, Any]) -> ToolResult:
        chart_id = (args.get("chart_id") or "").strip()
        if not chart_id:
            return ToolResult.error("Missing required parameter: chart_id")
        deleted = await self._store.delete(chart_id)
        if not deleted:
            return ToolResult.error(f"Grafico non trovato: {chart_id}")
        return ToolResult.ok(f"Grafico eliminato: {chart_id}")
