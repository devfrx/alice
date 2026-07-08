"""AL\\CE — Tool offer policy: what is offered.

Pure, stateless offer-shaping functions applied to an already-available
OpenAI-format toolset: capping the count, dropping user-disabled tools,
and reshaping the set to match the active permission tier.

This is SELECT-TIME policy only — deciding what the LLM is offered this
turn. The RUN-TIME permission gate that decides whether a call is
actually allowed to execute is a separate concern, owned by
``backend.services.permission_service.PermissionService.decide``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.core.tools.catalog import ToolCatalog

_logger = logger.bind(component="ToolPolicy")


def limit_tools(
    tools: list[dict[str, Any]],
    max_tools: int,
    *,
    catalog: ToolCatalog,
    priority_plugins: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Cap *tools* to *max_tools*, prioritising certain plugins.

    Tools from *priority_plugins* are always included first. Tools
    whose definition declares ``always_offered`` are treated as
    priority and never cut. Remaining slots are filled in the order
    the other tools appear.

    Args:
        tools: Full list of available tools (OpenAI format).
        max_tools: Maximum number to return.  ``0`` disables limiting.
        catalog: The tool catalog, for plugin/definition lookups.
        priority_plugins: Plugin names whose tools have priority.

    Returns:
        A (possibly shorter) list of tool dicts.
    """
    if max_tools <= 0 or len(tools) <= max_tools:
        return tools

    prio = set(priority_plugins or [])
    priority: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []

    for entry in tools:
        ns_name: str = entry["function"]["name"]
        plugin_name = catalog.plugin_of(ns_name)
        tool_def = catalog.definition(ns_name)
        is_always = tool_def is not None and tool_def.always_offered
        if plugin_name in prio or is_always:
            priority.append(entry)
        else:
            rest.append(entry)

    # Priority tools always included; fill remainder from rest.
    remaining_slots = max(0, max_tools - len(priority))
    limited = priority + rest[:remaining_slots]

    if len(limited) < len(tools):
        _logger.info(
            "Tool limit applied: {} → {} tools (priority plugins: {})",
            len(tools),
            len(limited),
            ", ".join(sorted(prio)) if prio else "none",
        )

    return limited


def exclude_disabled(
    tools: list[dict[str, Any]],
    disabled_names: set[str],
) -> list[dict[str, Any]]:
    """Drop tools whose namespaced name is in *disabled_names*.

    Used to apply the user's per-chat tool selection (opt-out) on
    top of the available toolset. A no-op when *disabled_names* is
    empty so default behaviour is preserved.

    Args:
        tools: OpenAI-format tool dicts (e.g. from
            :meth:`get_available_tools`).
        disabled_names: Namespaced tool names to remove.

    Returns:
        The filtered list (a new list; the input is not mutated).
    """
    if not disabled_names:
        return tools
    return [
        entry
        for entry in tools
        if entry["function"]["name"] not in disabled_names
    ]


def apply_mode_policy(
    tools: list[dict[str, Any]],
    *,
    catalog: ToolCatalog,
    drop_capabilities: frozenset[str] | set[str] = frozenset(),
    priority_plugins: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """Reshape *tools* to match the active permission tier.

    Two capability-/plugin-driven transforms, applied in order:

    * **drop** — remove every tool whose definition declares any capability
      in *drop_capabilities* (e.g. ``fs_write`` / ``process_exec`` in the
      read-only ``plan`` tier).  Withholding the tools the gate would deny
      anyway keeps the model from leading with an action it cannot take.  A
      tool whose definition declares ``always_offered`` is exempt: it
      survives even when its capabilities intersect *drop_capabilities*,
      so the meta-tools can never be withheld.
    * **prioritise** — float tools owned by *priority_plugins* to the front
      (stable within each group) so the model reaches for them first (e.g.
      the planning meta-tools in ``plan`` mode).

    The input list is never mutated; a new list is returned (or the input
    unchanged when both transforms are no-ops).  A tool whose definition
    cannot be resolved is treated as capability-less — never dropped.

    Args:
        tools: OpenAI-format tool dicts (e.g. from the selection branch).
        catalog: The tool catalog, for plugin/definition lookups.
        drop_capabilities: Capability tags whose tools are removed.
        priority_plugins: Owning-plugin names floated to the front.

    Returns:
        The reshaped tool list.
    """
    if not tools:
        return tools

    result = tools
    if drop_capabilities:
        drop = frozenset(drop_capabilities)
        kept: list[dict[str, Any]] = []
        for entry in result:
            ns_name = entry.get("function", {}).get("name", "")
            tool_def = catalog.definition(ns_name)
            if tool_def is not None and tool_def.always_offered:
                kept.append(entry)
                continue
            caps = set(tool_def.capabilities) if tool_def is not None else set()
            if caps & drop:
                continue
            kept.append(entry)
        result = kept

    prio = set(priority_plugins or ())
    if prio:
        front: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for entry in result:
            ns_name = entry.get("function", {}).get("name", "")
            if catalog.plugin_of(ns_name) in prio:
                front.append(entry)
            else:
                rest.append(entry)
        result = front + rest

    return result
