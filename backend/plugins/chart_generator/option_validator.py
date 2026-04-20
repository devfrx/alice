"""Validazione e auto-fix di un ECharts ``option`` prima del salvataggio.

L'LLM produce spesso JSON sintatticamente valido ma semanticamente
rotto: ``series`` senza ``type``, ``data`` mancante, oppure stringhe
come ``"name":"X`,type:"`` dove i campi sono finiti incollati nel
``name`` per un errore di quoting.  Senza validazione il chart_generator
salva la spec, ECharts la riceve e renderizza un canvas vuoto — l'LLM
non si accorge di nulla perché il tool risponde ``ok``.

Questo modulo:
  * applica un *auto-fix* conservativo (riempire ``series[].type`` dal
    ``chart_type`` top-level quando mancante);
  * rifiuta con messaggio esplicito quando i dati sono assenti,
    incoerenti o sospetti, così che il modello possa rigenerare la
    chiamata correttamente.
"""

from __future__ import annotations

from typing import Any

# Pattern sospetti: il modello ha incollato il campo successivo nel ``name``
# Esempi reali: ``"Valore in Miliardi/Milioni`,type:"`` (backtick + virgola
# + chiave troncata), ``X","type":"bar`` (graffe interne).
_SUSPICIOUS_NAME_FRAGMENTS: tuple[str, ...] = (
    "`,type",
    '",type',
    "`,data",
    '",data',
    "`,name",
)

# Tipi ECharts top-level che NON richiedono asse cartesiano.
_AXISLESS_TYPES: frozenset[str] = frozenset(
    {"pie", "radar", "gauge", "funnel", "treemap", "sunburst", "sankey"},
)

# Tipi ECharts series riconosciuti (lista non esaustiva ma copre i casi
# usati dai prompt del sistema).
_KNOWN_SERIES_TYPES: frozenset[str] = frozenset(
    {
        "bar", "line", "pie", "scatter", "effectScatter", "radar",
        "tree", "treemap", "sunburst", "boxplot", "candlestick",
        "heatmap", "map", "parallel", "lines", "graph", "sankey",
        "funnel", "gauge", "pictorialBar", "themeRiver", "custom",
    },
)


class ChartOptionError(ValueError):
    """Sollevata quando ``echarts_option`` è inutilizzabile.

    Il messaggio è pensato per essere restituito direttamente all'LLM
    come errore di tool, in italiano e con istruzioni concrete.
    """


def validate_and_normalize_option(
    option: dict[str, Any],
    chart_type: str,
) -> dict[str, Any]:
    """Valida e normalizza un ``echarts_option`` LLM-generato.

    Args:
        option: Oggetto ECharts ``option`` come fornito dall'LLM.
        chart_type: Tipo di grafico dichiarato a livello tool
            (``bar``, ``line``, ``pie``, …); usato per riempire
            ``series[].type`` quando mancante.

    Returns:
        Una copia (shallow) di ``option`` con ``series`` normalizzato.
        Le altre chiavi top-level sono lasciate intatte.

    Raises:
        ChartOptionError: Quando ``option`` è strutturalmente
            inutilizzabile (es. ``series`` mancante, ``data`` vuoto).
    """
    if not isinstance(option, dict):
        raise ChartOptionError(
            "echarts_option deve essere un oggetto JSON con chiavi top-level "
            "(series, xAxis, yAxis, ecc.)."
        )

    series_raw = option.get("series")
    if series_raw is None:
        raise ChartOptionError(
            "Manca la chiave 'series'. Aggiungi almeno "
            "series=[{type:'<chart_type>', data:[...]}]."
        )
    if not isinstance(series_raw, list):
        raise ChartOptionError(
            "'series' deve essere una lista di oggetti, non "
            f"{type(series_raw).__name__}."
        )
    if len(series_raw) == 0:
        raise ChartOptionError(
            "'series' è vuoto. Aggiungi almeno una serie con type e data."
        )

    fixed_series: list[dict[str, Any]] = []
    for idx, raw in enumerate(series_raw):
        fixed_series.append(_normalize_series_entry(raw, idx, chart_type))

    cartesian = chart_type not in _AXISLESS_TYPES and not any(
        (s.get("type") in _AXISLESS_TYPES) for s in fixed_series
    )

    normalized = dict(option)
    normalized["series"] = fixed_series

    if cartesian:
        _autofix_cartesian_axes(normalized)
        _check_cartesian_axes(normalized, fixed_series)

    return normalized


def _autofix_cartesian_axes(option: dict[str, Any]) -> None:
    """Aggiunge ``xAxis``/``yAxis`` mancanti per grafici cartesiani.

    ECharts richiede ENTRAMBI gli assi per series cartesiane (bar/line/
    scatter): se l'LLM ne fornisce solo uno, la series rimane orfana
    di ``yAxisIndex=0`` e ECharts solleva ``"yAxis 0 not found"``,
    mostrando un canvas vuoto.

    Auto-fix conservativo:
      * Se manca ``yAxis`` ma c'\u00e8 ``xAxis`` \u2192 aggiunge ``yAxis={type:'value'}``.
      * Se manca ``xAxis`` ma c'\u00e8 ``yAxis`` \u2192 aggiunge ``xAxis={type:'category'}``.
      * Se mancano entrambi \u2192 aggiunge entrambi i default.
    """
    has_x = option.get("xAxis") is not None
    has_y = option.get("yAxis") is not None
    if not has_y:
        option["yAxis"] = {"type": "value"}
    if not has_x:
        option["xAxis"] = {"type": "category"}


def _normalize_series_entry(
    raw: Any,
    idx: int,
    chart_type: str,
) -> dict[str, Any]:
    """Valida e auto-fixa un singolo elemento di ``series``.

    Auto-fix applicati:
      * Se ``type`` manca → riempito con ``chart_type`` top-level.
      * Se ``name`` contiene un frammento sospetto (es. backtick + chiave
        troncata) → svuotato e segnalato come errore esplicito.
    """
    if not isinstance(raw, dict):
        raise ChartOptionError(
            f"series[{idx}] deve essere un oggetto, non "
            f"{type(raw).__name__}."
        )
    entry = dict(raw)

    # Auto-fix: riempi type mancante dal chart_type top-level
    series_type = entry.get("type")
    if not series_type:
        if chart_type not in _KNOWN_SERIES_TYPES:
            raise ChartOptionError(
                f"series[{idx}] non ha 'type' e chart_type='{chart_type}' "
                "non è un tipo ECharts valido. Specifica esplicitamente "
                "series[].type (es. 'bar', 'line', 'pie')."
            )
        entry["type"] = chart_type
        series_type = chart_type
    elif not isinstance(series_type, str):
        raise ChartOptionError(
            f"series[{idx}].type deve essere una stringa."
        )
    else:
        # type esplicito: verifica che non sia stato corrotto da quoting LLM
        # (es. 'bar}]},title:"' osservato in produzione) e che sia noto.
        for ch in '}"],:':
            if ch in series_type:
                raise ChartOptionError(
                    f"series[{idx}].type={series_type!r} contiene caratteri "
                    f"non validi ({ch!r}): probabile errore di quoting nel "
                    "JSON, frammenti di altre chiavi sono finiti dentro il "
                    "valore. Rigenera la chiamata con: "
                    f'"type":"{chart_type}".'
                )
        if series_type not in _KNOWN_SERIES_TYPES:
            known = ", ".join(sorted(_KNOWN_SERIES_TYPES)[:8])
            raise ChartOptionError(
                f"series[{idx}].type={series_type!r} non è un tipo ECharts "
                f"riconosciuto. Tipi validi: {known}, ..."
            )

    # Rilevamento di name corrotto da quoting LLM
    name = entry.get("name")
    if isinstance(name, str):
        for fragment in _SUSPICIOUS_NAME_FRAGMENTS:
            if fragment in name:
                raise ChartOptionError(
                    f"series[{idx}].name contiene un frammento sospetto "
                    f"({fragment!r}): probabile errore di quoting nel JSON, "
                    "il campo successivo è finito dentro il nome. "
                    "Rigenera la chiamata con campi separati: "
                    f'{{"type":"{series_type}","name":"...","data":[...]}}.'
                )

    # Validazione data
    _validate_series_data(entry, idx, series_type)

    return entry


def _validate_series_data(
    entry: dict[str, Any],
    idx: int,
    series_type: str,
) -> None:
    """Verifica che ``series[idx].data`` esista e sia non vuoto.

    Per i tipi che usano una struttura non basata su ``data`` (es.
    ``sankey`` usa ``links``, ``graph`` usa ``nodes``+``links``) la
    validazione è permissiva: accetta presenza di chiavi alternative.
    """
    if series_type in {"sankey", "graph"}:
        if not entry.get("data") and not entry.get("links"):
            raise ChartOptionError(
                f"series[{idx}] di tipo '{series_type}' richiede 'data' "
                "o 'links'."
            )
        return

    data = entry.get("data")
    if data is None:
        raise ChartOptionError(
            f"series[{idx}] non ha 'data'. Aggiungi data=[...] con i "
            "valori da visualizzare."
        )
    if not isinstance(data, list):
        raise ChartOptionError(
            f"series[{idx}].data deve essere una lista, non "
            f"{type(data).__name__}."
        )
    if len(data) == 0:
        raise ChartOptionError(
            f"series[{idx}].data è vuoto. Inserisci almeno un valore."
        )


def _check_cartesian_axes(
    option: dict[str, Any],
    series: list[dict[str, Any]],
) -> None:
    """Verifica congruenza fra ``xAxis.data`` e ``series[0].data`` quando entrambi presenti.

    ECharts accetta xAxis di default (category) anche se non dichiarato,
    quindi non forziamo la presenza di xAxis/yAxis: ci limitiamo al
    controllo di lunghezza, che è l'errore più frequente dei modelli
    locali ("3 categorie ma 2 valori" → barra fantasma).
    """
    x_axis = option.get("xAxis")
    x_data = _extract_axis_data(x_axis)
    if x_data is None:
        return  # nessun asse esplicito o senza categorie: ok

    first = series[0]
    series_data = first.get("data")
    if not isinstance(series_data, list):
        return
    if first.get("type") in _AXISLESS_TYPES:
        return
    if len(series_data) != len(x_data) and len(series_data) > 0:
        raise ChartOptionError(
            f"Mismatch asse/dati: xAxis.data ha {len(x_data)} categorie "
            f"ma series[0].data ha {len(series_data)} valori. Allinea "
            "le due lunghezze (una serie per N categorie = N valori)."
        )


def _extract_axis_data(axis: Any) -> list[Any] | None:
    """Estrae il campo ``data`` da un ``xAxis``/``yAxis`` ECharts.

    L'asse può essere un dict singolo o una lista di dict (multi-asse).
    Restituisce ``None`` quando non c'è una lista di categorie da
    confrontare con i dati delle serie.
    """
    if isinstance(axis, dict):
        data = axis.get("data")
        return data if isinstance(data, list) else None
    if isinstance(axis, list) and axis:
        first = axis[0]
        if isinstance(first, dict):
            data = first.get("data")
            return data if isinstance(data, list) else None
    return None


__all__ = ["ChartOptionError", "validate_and_normalize_option"]
