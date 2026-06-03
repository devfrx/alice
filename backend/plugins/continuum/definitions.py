"""AL\\CE — Continuum plugin tool definitions.

JSON-schema tool definitions exposed to the LLM. Kept in a dedicated
module so :mod:`backend.plugins.continuum.plugin` stays focused on
lifecycle and dispatch. Tool names are unqualified here; the tool
registry namespaces them as ``continuum_<name>`` at registration time.

Note CRUD lives in the sibling :mod:`backend.plugins.continuum.note_tools`
module (it routes through the knowledge backend rather than this plugin's
client). This module covers the structured surfaces: folders, kinds,
databases and the graph.
"""

from __future__ import annotations

from backend.core.plugin_models import ToolDefinition


def build_tool_definitions() -> list[ToolDefinition]:
    """Return the Continuum plugin's tool definitions."""
    return [
        ToolDefinition(
            name="list_folders",
            description=(
                "List the Continuum folder tree (forest of folders with note "
                "counts). Use to discover where notes can be organised before "
                "creating or moving them."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="create_folder",
            description=(
                "Create a Continuum folder. Optionally nest it under an "
                "existing parent folder by id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Folder display name.",
                        "maxLength": 120,
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Parent folder UUID, or omit for root.",
                    },
                },
                "required": ["name"],
            },
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="list_kinds",
            description=(
                "List Continuum note kinds (types). Each kind defines a slug "
                "and a property schema notes of that type inherit."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="list_databases",
            description=(
                "List Continuum databases (Notion-like tabular collections "
                "of notes)."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="get_database",
            description=(
                "Fetch one Continuum datasource bundle: database metadata "
                "plus its property schema. Use before creating rows, setting "
                "cell values, or constructing filters/sorts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "Target datasource/database UUID.",
                    },
                },
                "required": ["database_id"],
            },
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="query_database",
            description=(
                "Query a Continuum datasource for row snapshots. Accepts "
                "the same DatabaseQueryRequest shape used by the web app: "
                "optional config.filter/config.sort/config.group/etc. plus "
                "optional pagination. Returns materialised rows with note "
                "metadata and property values."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "Target database UUID.",
                    },
                    "config": {
                        "type": "object",
                        "description": (
                            "Optional partial DatabaseViewConfig. Supports "
                            "filter (FilterNode tree), sort, group, "
                            "visibleProperties, hiddenProperties, "
                            "conditionalColors and layout."
                        ),
                        "additionalProperties": True,
                    },
                    "pagination": {
                        "type": "object",
                        "description": (
                            "Optional pagination object: {offset, limit}."
                        ),
                        "properties": {
                            "offset": {"type": "integer", "minimum": 0},
                            "limit": {"type": "integer", "minimum": 1},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["database_id"],
            },
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="graph_query",
            description=(
                "Run a structured query over the Continuum knowledge graph "
                "using the same filter tree and edge-source contract as the "
                "2D graph Data tab. Use for relationship questions and for "
                "checking graph filters before applying them live."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "object",
                        "description": (
                            "FilterNode tree. Omit for an empty root group "
                            "that matches all graph nodes."
                        ),
                        "additionalProperties": True,
                    },
                    "edge_sources": {
                        "type": "object",
                        "description": (
                            "GraphEdgeSourceSelection: includeLinks, "
                            "allRelationProperties, relationPropertyKeys."
                        ),
                        "additionalProperties": True,
                    },
                    "include_properties": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Property keys to materialise on each node."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max nodes to return (1-200).",
                        "minimum": 1,
                        "maximum": 200,
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include per-node degree metrics.",
                    },
                },
            },
            requires_confirmation=False,
        ),
        ToolDefinition(
            name="note_backlinks",
            description=(
                "List the notes that link to a given Continuum note "
                "(incoming wikilinks / relations)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "Target note UUID.",
                    },
                },
                "required": ["note_id"],
            },
            requires_confirmation=False,
        ),
    ]


# ---------------------------------------------------------------------------
# Live-editor block tools (client-executed)
# ---------------------------------------------------------------------------
#
# These operate on the *currently open* Continuum note in the user's editor,
# not on the server. They are flagged ``client_execution=True`` so the chat
# WebSocket delegates them to the connected web client, which runs them
# against the live ProseMirror/TipTap document via the editor's block API.
# Blocks are addressed by their 0-based ``index`` within the ordered list of
# top-level blocks (see ``list_blocks``), which is stable and universal across
# every block type — unlike per-node ids, which only some node types carry.

# Shared enum of every insertable / convertible block type. Kept in lockstep
# with the editor's registered nodes (StarterKit + custom Continuum blocks).
_BLOCK_TYPES: list[str] = [
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "taskList",
    "blockquote",
    "codeBlock",
    "horizontalRule",
    "table",
    "image",
    "callout",
    "details",
    "syncedBlock",
    "toggleHeading",
    "columns",
    "tabs",
    "chart",
    "database",
    "breadcrumbBlock",
    "mediaBlock",
    "pageBlock",
    "buttonBlock",
    "equation",
]


def build_block_tool_definitions() -> list[ToolDefinition]:
    """Return the client-executed live-editor block tools.

    Every tool here carries ``client_execution=True``: it is never run on the
    server. The chat WebSocket forwards the call to the connected client,
    which mutates the open note's document and returns the result. The
    autosave already in place persists the new ``content``/``contentJson``,
    so no server-side write is required.
    """
    block_type_enum = {
        "type": "string",
        "enum": _BLOCK_TYPES,
        "description": (
            "Block type. One of the registered Continuum block types: "
            "paragraph, heading, bulletList, orderedList, taskList, "
            "blockquote, codeBlock, horizontalRule, table, image, callout, "
            "details, syncedBlock, toggleHeading, columns, tabs, chart, "
            "database, breadcrumbBlock, mediaBlock, pageBlock, buttonBlock, "
            "equation."
        ),
    }
    index_prop = {
        "type": "integer",
        "minimum": 0,
        "description": (
            "0-based position of the block within the ordered list of "
            "top-level blocks, as returned by list_blocks. Required for "
            "single-block and section-scoped edits."
        ),
    }
    attrs_prop = {
        "type": "object",
        "description": (
            "Optional block attributes to set (block-type specific). "
            "Examples: heading -> {\"level\": 2}; callout -> {\"icon\": "
            "\"\\ud83d\\udca1\"}; equation -> {\"latex\": \"E=mc^2\"}; "
            "codeBlock -> {\"language\": \"python\"}. Inspect a block with "
            "list_blocks first to see its current attributes."
        ),
        "additionalProperties": True,
    }

    return [
        ToolDefinition(
            name="list_blocks",
            description=(
                "List, in order, every top-level block of the note currently "
                "open in the Continuum editor. Returns each block's index, "
                "type, a short text preview and its attributes. Always call "
                "this first to understand the document before editing, and "
                "again after edits to confirm the new layout. Requires a note "
                "to be open in the editor."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="list_block_types",
            description=(
                "List every block type that can be inserted or converted to "
                "in the Continuum editor, with a label, description and the "
                "attributes each type supports. Use to discover the full "
                "block catalogue before inserting or converting blocks."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="list_block_commands",
            description=(
                "List the same block insertion commands exposed by the "
                "Continuum slash menu UI. Returns stable command_id values "
                "such as heading-2, table, database-table-view, "
                "database-board-view, video-block, tabs-block, etc. Prefer "
                "these commands for structural blocks because run_block_command "
                "executes the editor's real command descriptor instead of "
                "reconstructing a block from a simplified type."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="insert_block",
            description=(
                "Insert a new block into the open note. By default the block "
                "is appended at the end; pass 'index' to insert it at a "
                "specific position (the new block takes that index, shifting "
                "later blocks down). Provide 'text' for textual blocks and "
                "'attrs' for type-specific attributes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "type": block_type_enum,
                    "text": {
                        "type": "string",
                        "description": (
                            "Initial text content for textual blocks "
                            "(paragraph, heading, blockquote, list items, "
                            "codeBlock, callout, etc.). Ignored by atom "
                            "blocks that have no text."
                        ),
                    },
                    "attrs": attrs_prop,
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Optional 0-based insert position. Omit to "
                            "append at the end of the document."
                        ),
                    },
                },
                "required": ["type"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="run_block_command",
            description=(
                "Run one of the shared Continuum editor block commands in "
                "the open note, using the exact command descriptor that the "
                "slash menu UI uses. Call list_block_commands first, then pass "
                "the returned command_id. This is the preferred way to insert "
                "full-featured structural blocks and variants (database table, "
                "board, calendar, charts, media, tabs, columns, toggle "
                "headings, table, etc.). By default the command appends at "
                "the end; pass index to run it before an existing top-level "
                "block."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command_id": {
                        "type": "string",
                        "description": (
                            "Stable command id returned by list_block_commands "
                            "(for example database-table-view, tabs-block, "
                            "heading-2, table, video-block)."
                        ),
                    },
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Optional 0-based insert position. Omit to append "
                            "at the end of the document."
                        ),
                    },
                },
                "required": ["command_id"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="update_block",
            description=(
                "Update an existing block: replace its text content and/or "
                "set type-specific attributes. Identify the block by its "
                "index from list_blocks. To change a block's *type*, use "
                "turn_block_into instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "index": index_prop,
                    "text": {
                        "type": "string",
                        "description": (
                            "New text content for the block. Replaces the "
                            "block's current text."
                        ),
                    },
                    "attrs": attrs_prop,
                },
                "required": ["index"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="delete_block",
            description=(
                "Delete a block from the open note, identified by its index "
                "from list_blocks. Subsequent blocks shift up by one index."
            ),
            parameters={
                "type": "object",
                "properties": {"index": index_prop},
                "required": ["index"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="move_block",
            description=(
                "Move/reorder a block within the open note: take the block at "
                "'index' and place it at 'to_index'. Use this to reorganise "
                "and tidy the page layout."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "index": index_prop,
                    "to_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "0-based destination position for the block."
                        ),
                    },
                },
                "required": ["index", "to_index"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="turn_block_into",
            description=(
                "Convert blocks through the shared Continuum Turn into "
                "pipeline. With scope='block' (default), convert the single "
                "block at index to the target type (paragraph, heading, "
                "toggleHeading, lists, details, callout, quote, codeBlock). "
                "With type='toggleHeading' and scope='section', convert the "
                "heading at index plus its following section content into a "
                "real nested toggleHeading. With type='toggleHeading' and "
                "scope='document', convert all heading sections in the open "
                "note bottom-up. Use this one tool for Turn into operations; "
                "do not compose delete/insert/move steps manually."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "index": index_prop,
                    "type": block_type_enum,
                    "attrs": attrs_prop,
                    "scope": {
                        "type": "string",
                        "enum": ["block", "section", "document"],
                        "description": (
                            "Turn into scope. Omit or pass 'block' for one "
                            "block at index. Pass 'section' to wrap the "
                            "heading at index and its section content. Pass "
                            "'document' to apply the section transform to "
                            "all headings; index is ignored. Section and "
                            "document scopes currently require type "
                            "'toggleHeading'."
                        ),
                    },
                },
                "required": ["type"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="duplicate_block",
            description=(
                "Duplicate a block in place: a copy is inserted immediately "
                "after the original. Identify the block by its index from "
                "list_blocks."
            ),
            parameters={
                "type": "object",
                "properties": {"index": index_prop},
                "required": ["index"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
    ]


def build_database_block_tool_definitions() -> list[ToolDefinition]:
    """Return client-executed tools for live database blocks.

    Database blocks are host-rendered Vue NodeViews. Their saved views,
    datasource schema, row queries and automations already flow through the
    Continuum web API, so Alice edits them by delegating to the connected web
    client instead of re-implementing database logic in Python.
    """
    database_actions = [
        "list_datasources",
        "get_datasource",
        "create_datasource",
        "update_datasource",
        "create_property",
        "reorder_properties",
        "create_row",
        "reorder_rows",
        "set_cell",
        "clear_cell",
        "query",
        "list_views",
        "add_view",
        "select_view",
        "update_view",
        "reorder_views",
        "list_automations",
        "create_automation",
        "update_automation",
        "run_automation",
        "list_automation_runs",
    ]
    destructive_actions = [
        "delete_datasource",
        "remove_row",
        "delete_view",
        "delete_automation",
    ]
    payload_schema = {
        "type": "object",
        "description": (
            "Action-specific payload. Uses the same route shapes as the "
            "Continuum web API. Common keys: database_id, block_index, "
            "block_id, view_id, row_id, property_id, note_id, config, "
            "pagination, ids, value, automation, patch."
        ),
        "additionalProperties": True,
    }
    return [
        ToolDefinition(
            name="list_database_blocks",
            description=(
                "Inspect every database block in the currently open note. "
                "Returns block indexes, blockIds, activeViewId, saved views, "
                "available datasources and per-datasource schema bundles. "
                "Call this before manipulating database views or rows from "
                "the live editor."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="run_database_action",
            description=(
                "Run one non-destructive or additive database action through "
                "the live Continuum web client and its real API routes. Use "
                "for datasource metadata, schema, rows, cells, block views, "
                "saved view config/filter/sort/group/layout, and datasource "
                "automations. For a database block target, prefer "
                "block_index from list_database_blocks so the editor attrs "
                "(for example activeViewId) stay in sync."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": database_actions,
                        "description": "Database action to run.",
                    },
                    "payload": payload_schema,
                },
                "required": ["action"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="run_database_destructive_action",
            description=(
                "Run a destructive database action through the live Continuum "
                "web client. Requires confirmation because it can delete "
                "datasources, saved block views, rows or automations. Use "
                "only after resolving exact ids with list_database_blocks, "
                "get_database or query_database."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": destructive_actions,
                        "description": "Destructive database action to run.",
                    },
                    "payload": payload_schema,
                },
                "required": ["action"],
            },
            risk_level="medium",
            requires_confirmation=True,
            client_execution=True,
        ),
    ]


def build_graph_tool_definitions() -> list[ToolDefinition]:
    """Return client-executed tools for the live 2D graph view."""
    return [
        ToolDefinition(
            name="graph_get_state",
            description=(
                "Read the currently open Graph view state: 2D/3D mode, "
                "layout, display filters, search, hidden kinds, highlighted "
                "nodes, data FilterNode tree, edge sources, visual encodings "
                "and current graph stats. Requires the Graph view to be open."
            ),
            parameters={"type": "object", "properties": {}},
            requires_confirmation=False,
            client_execution=True,
        ),
        ToolDefinition(
            name="run_graph_action",
            description=(
                "Apply one live Graph view action using the same state as the "
                "2D Filtri panel and Data/Stile tabs. Use set_data_filter "
                "for node title/name/property conditions; set_display_filters "
                "is only for physics/appearance toggles. Actions include "
                "set_view_mode, set_layout, set_display_filters, "
                "reset_display_filters, set_search, set_hidden_kinds, "
                "show_all_kinds, set_data_filter, reset_data_filter, "
                "set_edge_sources, set_encoding, set_encodings, "
                "reset_encodings, set_highlights, focus_node and reload."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "set_view_mode",
                            "set_layout",
                            "set_display_filters",
                            "reset_display_filters",
                            "set_search",
                            "set_hidden_kinds",
                            "show_all_kinds",
                            "set_data_filter",
                            "reset_data_filter",
                            "set_edge_sources",
                            "set_encoding",
                            "set_encodings",
                            "reset_encodings",
                            "set_highlights",
                            "focus_node",
                            "reload",
                        ],
                    },
                    "payload": {
                        "type": "object",
                        "description": (
                            "Action-specific payload. Examples: "
                            "{filters:{hideOrphans:true}} for display only, "
                            "{field:'note.title',operator:'startsWith',value:'b'} "
                            "or {filter:{type:'group',...}} for data filters, "
                            "{edge_sources:{includeLinks:true,...}}, "
                            "{slot:'color', field:{kind:'property',key:'status'}}, "
                            "{mode:'replace', kind_ids:['project']}."
                        ),
                        "additionalProperties": True,
                    },
                },
                "required": ["action"],
            },
            requires_confirmation=False,
            client_execution=True,
        ),
    ]


def build_client_tool_definitions() -> list[ToolDefinition]:
    """Return all client-executed Continuum tools."""
    return (
        build_block_tool_definitions()
        + build_database_block_tool_definitions()
        + build_graph_tool_definitions()
    )
