"""ShapeBuilder — converte SimpleShape LLM-friendly in TLStoreSnapshot tldraw."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .models import SimpleShape

# Mapping colori AL\CE → colori tldraw più vicini
_COLOR_MAP: dict[str, str] = {
    "cream": "white",
    "sage": "light-green",
    "amber": "yellow",
    "steel": "light-blue",
    "coral": "orange",
    "lavender": "violet",
    "teal": "light-blue",
}

# Record ID statico per la pagina e la camera di default
_DEFAULT_PAGE_ID = "page:page"
_DEFAULT_CAMERA_ID = "camera:page:page"
_DEFAULT_DOCUMENT_ID = "document:document"
_DEFAULT_POINTER_ID = "pointer:pointer"


def _make_shape_id(shape_id: str | None) -> str:
    """Genera un ID shape tldraw nel formato shape:{uuid}."""
    raw = shape_id or str(uuid4())
    if not raw.startswith("shape:"):
        raw = f"shape:{raw}"
    return raw


def _build_geo_shape(
    shape: SimpleShape, shape_id: str
) -> dict[str, Any]:
    """Costruisce un record TLShape di tipo 'geo'."""
    return {
        "typeName": "shape",
        "id": shape_id,
        "type": "geo",
        "x": shape.x,
        "y": shape.y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": _DEFAULT_PAGE_ID,
        "index": "a1",
        "props": {
            "geo": shape.geo,
            "w": shape.w,
            "h": shape.h,
            "text": shape.text,
            "color": _COLOR_MAP.get(shape.color, "white"),
            "labelColor": "black",
            "fill": "solid",
            "dash": "draw",
            "size": "m",
            "font": "draw",
            "align": "middle",
            "verticalAlign": "middle",
            "growY": 0,
            "url": "",
            "scale": 1,
        },
    }


def _build_note_shape(
    shape: SimpleShape, shape_id: str
) -> dict[str, Any]:
    """Costruisce un record TLShape di tipo 'note' (sticky note)."""
    return {
        "typeName": "shape",
        "id": shape_id,
        "type": "note",
        "x": shape.x,
        "y": shape.y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": _DEFAULT_PAGE_ID,
        "index": "a1",
        "props": {
            "color": _COLOR_MAP.get(shape.color, "white"),
            "size": "m",
            "text": shape.text,
            "font": "draw",
            "align": "middle",
            "verticalAlign": "middle",
            "growY": 0,
            "url": "",
            "scale": 1,
        },
    }


def _build_text_shape(
    shape: SimpleShape, shape_id: str
) -> dict[str, Any]:
    """Costruisce un record TLShape di tipo 'text'."""
    return {
        "typeName": "shape",
        "id": shape_id,
        "type": "text",
        "x": shape.x,
        "y": shape.y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": _DEFAULT_PAGE_ID,
        "index": "a1",
        "props": {
            "color": _COLOR_MAP.get(shape.color, "white"),
            "size": "m",
            "text": shape.text,
            "font": "draw",
            "textAlign": "start",
            "w": shape.w,
            "autoSize": True,
            "scale": 1,
        },
    }


def _build_arrow_shape(
    shape: SimpleShape, shape_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Costruisce un record TLShape arrow + binding records opzionali.

    Returns:
        Tupla (arrow_record, lista_di_binding_records).
    """
    arrow = {
        "typeName": "shape",
        "id": shape_id,
        "type": "arrow",
        "x": shape.x,
        "y": shape.y,
        "rotation": 0,
        "isLocked": False,
        "opacity": 1,
        "meta": {},
        "parentId": _DEFAULT_PAGE_ID,
        "index": "a1",
        "props": {
            "dash": "draw",
            "size": "m",
            "fill": "none",
            "color": _COLOR_MAP.get(shape.color, "white"),
            "labelColor": "black",
            "bend": 0,
            "start": {"x": 0, "y": 0},
            "end": {"x": shape.w, "y": shape.h},
            "arrowheadStart": "none",
            "arrowheadEnd": "arrow",
            "text": shape.text,
            "labelPosition": 0.5,
            "font": "draw",
            "scale": 1,
        },
    }

    bindings: list[dict[str, Any]] = []

    if shape.from_id:
        from_shape_id = _make_shape_id(shape.from_id)
        binding_id = f"binding:{uuid4()}"
        bindings.append({
            "typeName": "binding",
            "id": binding_id,
            "type": "arrow",
            "fromId": shape_id,
            "toId": from_shape_id,
            "meta": {},
            "props": {
                "terminal": "start",
                "normalizedAnchor": {"x": 0.5, "y": 0.5},
                "isExact": False,
                "isPrecise": False,
            },
        })

    if shape.to_id:
        to_shape_id = _make_shape_id(shape.to_id)
        binding_id = f"binding:{uuid4()}"
        bindings.append({
            "typeName": "binding",
            "id": binding_id,
            "type": "arrow",
            "fromId": shape_id,
            "toId": to_shape_id,
            "meta": {},
            "props": {
                "terminal": "end",
                "normalizedAnchor": {"x": 0.5, "y": 0.5},
                "isExact": False,
                "isPrecise": False,
            },
        })

    return arrow, bindings


def build_snapshot(shapes: list[SimpleShape]) -> dict[str, Any]:
    """Converte una lista di SimpleShape in un TLStoreSnapshot tldraw valido.

    Args:
        shapes: Lista di shape LLM-friendly da convertire.

    Returns:
        Dizionario compatibile con tldraw ``TLStoreSnapshot``.
    """
    store: dict[str, Any] = {}

    # Record fissi: documento, pagina, camera
    store[_DEFAULT_DOCUMENT_ID] = {
        "typeName": "document",
        "id": _DEFAULT_DOCUMENT_ID,
        "name": "",
        "meta": {},
        "gridSize": 10,
    }

    store[_DEFAULT_PAGE_ID] = {
        "typeName": "page",
        "id": _DEFAULT_PAGE_ID,
        "name": "Page 1",
        "index": "a1",
        "meta": {},
    }

    # Filtra shape senza testo (tranne arrow) — sono inutili nel diagramma
    shapes = [
        s for s in shapes
        if s.type == "arrow" or (s.text and s.text.strip())
    ]

    # Indici per ordinamento stabile
    for i, shape in enumerate(shapes):
        shape_id = _make_shape_id(shape.id)
        index = f"a{i + 1}"

        if shape.type == "geo":
            record = _build_geo_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "note":
            record = _build_note_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "text":
            record = _build_text_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "arrow":
            record, bindings = _build_arrow_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record
            for binding in bindings:
                store[binding["id"]] = binding

    return {
        "store": store,
        "schema": {
            "schemaVersion": 2,
            "sequences": {
                "com.tldraw.store": 4,
                "com.tldraw.asset": 1,
                "com.tldraw.camera": 1,
                "com.tldraw.document": 2,
                "com.tldraw.instance": 25,
                "com.tldraw.instance_page_state": 5,
                "com.tldraw.page": 1,
                "com.tldraw.shape": 4,
                "com.tldraw.shape.arrow": 5,
                "com.tldraw.shape.bookmark": 2,
                "com.tldraw.shape.draw": 2,
                "com.tldraw.shape.embed": 4,
                "com.tldraw.shape.frame": 0,
                "com.tldraw.shape.geo": 9,
                "com.tldraw.shape.group": 0,
                "com.tldraw.shape.highlight": 1,
                "com.tldraw.shape.image": 4,
                "com.tldraw.shape.line": 5,
                "com.tldraw.shape.note": 7,
                "com.tldraw.shape.text": 2,
                "com.tldraw.shape.video": 2,
                "com.tldraw.binding": 0,
                "com.tldraw.binding.arrow": 0,
            },
        },
    }


def merge_shapes_into_snapshot(
    existing_snapshot: dict[str, Any], new_shapes: list[SimpleShape]
) -> dict[str, Any]:
    """Aggiunge nuove shapes a uno snapshot esistente senza rimpiazzare.

    Args:
        existing_snapshot: Snapshot tldraw esistente.
        new_shapes: Nuove shapes da aggiungere.

    Returns:
        Snapshot aggiornato con le nuove shapes aggiunte.
    """
    store = dict(existing_snapshot.get("store", {}))

    # Trova l'indice massimo corrente per evitare collisioni
    max_index = 0
    for record in store.values():
        if isinstance(record, dict) and record.get("typeName") == "shape":
            idx = record.get("index", "a0")
            try:
                num = int(idx[1:]) if idx.startswith("a") else 0
                max_index = max(max_index, num)
            except (ValueError, IndexError):
                pass

    # Filtra shape senza testo (tranne arrow)
    new_shapes = [
        s for s in new_shapes
        if s.type == "arrow" or (s.text and s.text.strip())
    ]

    for i, shape in enumerate(new_shapes):
        shape_id = _make_shape_id(shape.id)
        index = f"a{max_index + i + 1}"

        if shape.type == "geo":
            record = _build_geo_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "note":
            record = _build_note_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "text":
            record = _build_text_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record

        elif shape.type == "arrow":
            record, bindings = _build_arrow_shape(shape, shape_id)
            record["index"] = index
            store[shape_id] = record
            for binding in bindings:
                store[binding["id"]] = binding

    result = dict(existing_snapshot)
    result["store"] = store
    return result
