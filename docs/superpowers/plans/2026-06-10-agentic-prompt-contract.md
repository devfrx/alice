# Agentic Prompt Contract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee the agent meta-tools (`ask_user`, `write_plan`, `update_tasks`, `spawn_subagent`) are offered every turn and teach the model when/how to use them via a per-tool guidance fragment composed into a single `[ORCHESTRAZIONE]` system-prompt block.

**Architecture:** Two new declarative fields on `ToolDefinition` (`always_offered`, `usage_guidance`); the registry honours `always_offered` in all three selection paths and exposes `usage_guidance_for(tools)`; a new pure `services/prompt_composer.py` owns the dynamic-context ordering; `_assembly.py` is rewired to it; `permission_mode_policy` is slimmed to tier-only concerns.

**Tech Stack:** Python 3.13 (venv `..\.venv` from `backend/`), pytest, ruff, mypy. Spec: `docs/superpowers/specs/2026-06-10-agentic-prompt-contract-design.md`.

**Environment notes (from `docs/agent-rework/HANDOFF.md`):** run tests from `backend/` with `..\.venv\Scripts\python.exe -m pytest …`. The WS integration tests (`test_websocket`, `test_concurrent`, `test_message_editing`, `test_branch_conversation`, `test_voice_ws`, `test_voice_tool_calling`) and `test_app.py` hang offline — never run them. Pre-existing ruff noise in `services/turn/tool_loop.py` — don't chase.

---

### Task 1: `ToolDefinition.always_offered` + `usage_guidance`

**Files:**
- Modify: `backend/core/plugin_models.py` (dataclass `ToolDefinition`, ~line 84–99)
- Test: `backend/tests/test_plugin_models.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_plugin_models.py`:

```python
class TestToolDefinitionOrchestrationFields:
    """New declarative fields for the agentic prompt contract."""

    def test_defaults(self):
        """Plain tools are neither always-offered nor guidance-bearing."""
        tool = ToolDefinition(name="plain_tool", description="A tool")
        assert tool.always_offered is False
        assert tool.usage_guidance is None

    def test_fields_settable(self):
        tool = ToolDefinition(
            name="meta_tool",
            description="A meta tool",
            always_offered=True,
            usage_guidance="Usalo sempre prima di iniziare.",
        )
        assert tool.always_offered is True
        assert tool.usage_guidance == "Usalo sempre prima di iniziare."

    def test_usage_guidance_not_in_openai_format(self):
        """Guidance is prompt-side only — never serialised into the schema."""
        tool = ToolDefinition(
            name="meta_tool",
            description="A meta tool",
            always_offered=True,
            usage_guidance="Regola vincolante.",
        )
        payload = tool.to_openai_format()
        assert "usage_guidance" not in payload["function"]
        assert "always_offered" not in payload["function"]
        assert payload["function"]["name"] == "meta_tool"
```

(Match the existing import style of the file; `ToolDefinition` is already imported there.)

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_plugin_models.py -v -k Orchestration`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'always_offered'`

- [ ] **Step 3: Implement** — in `backend/core/plugin_models.py`, after the `path_args: tuple[str, ...] = ()` field add:

```python
    always_offered: bool = False
    usage_guidance: str | None = None
```

and extend the class docstring `Attributes:` section with:

```
        always_offered: When ``True`` the tool survives every toolset
            *selection* pass — it is included alongside tool-RAG hits,
            never cut by ``limit_tools`` and exempt from the capability
            drop of ``apply_mode_policy``. It is still subject to
            connection-status filtering and to the user's explicit
            per-chat opt-out (``exclude_disabled``). Meant for the agent
            meta-tools, whose presence is part of the protocol surface
            rather than a relevance question.
        usage_guidance: Optional system-prompt fragment (markdown,
            imperative, a few lines) teaching the model WHEN and HOW to
            use this tool. Collected for the tools actually offered in a
            turn and composed into the ``[ORCHESTRAZIONE]`` block — never
            serialised into the OpenAI schema.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_plugin_models.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Lint + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check core/plugin_models.py tests/test_plugin_models.py
..\.venv\Scripts\python.exe -m mypy core/plugin_models.py
git add core/plugin_models.py tests/test_plugin_models.py
git commit -m "feat(tools): ToolDefinition gains always_offered + usage_guidance"
```

---

### Task 2: Registry honours `always_offered`; `usage_guidance_for()`

**Files:**
- Modify: `backend/core/tool_registry.py` (`limit_tools` ~497, `apply_mode_policy` ~626, `get_relevant_tools` ~784–886; new method near `exclude_disabled`)
- Modify: `backend/core/protocols.py` (`ToolRegistryProtocol`, ~line 324 — `ctx.tool_registry` is typed as this Protocol, so the new method must appear here too)
- Test: `backend/tests/test_tool_registry.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_tool_registry.py`. Note `_make_tool` exists; add a meta-tool helper:

```python
# ---------------------------------------------------------------------------
# always_offered & usage guidance (agentic prompt contract)
# ---------------------------------------------------------------------------


def _make_meta_tool(name: str, guidance: str | None = "Regola.") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="A meta tool",
        always_offered=True,
        usage_guidance=guidance,
        capabilities=("planning",),
    )


class TestAlwaysOffered:

    @pytest.mark.asyncio
    async def test_limit_tools_never_cuts_always_offered(self, make_registry):
        """A 1-slot cap keeps the always-offered tool plus the cap winner."""
        meta = MockPlugin(tools=[_make_meta_tool("ask")], name="agent")
        others = MockPlugin(
            tools=[_make_tool(f"t{i}") for i in range(5)], name="plug",
        )
        registry = make_registry({"agent": meta, "plug": others})
        await registry.refresh()

        all_tools = registry.get_all_tools()
        limited = registry.limit_tools(all_tools, max_tools=2)
        names = {t["function"]["name"] for t in limited}
        assert "agent_ask" in names

    @pytest.mark.asyncio
    async def test_apply_mode_policy_drop_exempts_always_offered(
        self, make_registry,
    ):
        """Capability drop never removes an always-offered tool."""
        meta = ToolDefinition(
            name="ask",
            description="A meta tool",
            always_offered=True,
            capabilities=("fs_write",),  # would normally be dropped
        )
        plugin = MockPlugin(tools=[meta], name="agent")
        registry = make_registry({"agent": plugin})
        await registry.refresh()

        all_tools = registry.get_all_tools()
        kept = registry.apply_mode_policy(
            all_tools, drop_capabilities={"fs_write"},
        )
        assert {t["function"]["name"] for t in kept} == {"agent_ask"}

    @pytest.mark.asyncio
    async def test_exclude_disabled_still_wins(self, make_registry):
        """The user's explicit opt-out removes even always-offered tools."""
        meta = MockPlugin(tools=[_make_meta_tool("ask")], name="agent")
        registry = make_registry({"agent": meta})
        await registry.refresh()

        all_tools = registry.get_all_tools()
        assert registry.exclude_disabled(all_tools, {"agent_ask"}) == []


class TestUsageGuidanceFor:

    @pytest.mark.asyncio
    async def test_collects_in_toolset_order_skipping_blanks(
        self, make_registry,
    ):
        p = MockPlugin(
            tools=[
                _make_meta_tool("a", guidance="Prima regola."),
                _make_tool("plain"),
                _make_meta_tool("b", guidance="  Seconda regola.  "),
                _make_meta_tool("c", guidance="   "),
            ],
            name="agent",
        )
        registry = make_registry({"agent": p})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert registry.usage_guidance_for(tools) == [
            "Prima regola.",
            "Seconda regola.",
        ]

    @pytest.mark.asyncio
    async def test_deduplicates_identical_fragments(self, make_registry):
        p = MockPlugin(
            tools=[
                _make_meta_tool("a", guidance="Stessa regola."),
                _make_meta_tool("b", guidance="Stessa regola."),
            ],
            name="agent",
        )
        registry = make_registry({"agent": p})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert registry.usage_guidance_for(tools) == ["Stessa regola."]

    @pytest.mark.asyncio
    async def test_unknown_tools_ignored(self, make_registry):
        registry = make_registry({})
        await registry.refresh()
        ghost = [{"type": "function", "function": {"name": "ghost", "parameters": {}}}]
        assert registry.usage_guidance_for(ghost) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py -v -k "AlwaysOffered or UsageGuidance"`
Expected: FAIL (`AttributeError: usage_guidance_for`; limit/policy assertions fail).

- [ ] **Step 3: Implement** in `backend/core/tool_registry.py`:

3a. `limit_tools` — replace the partition loop body:

```python
        for entry in tools:
            ns_name: str = entry["function"]["name"]
            plugin_name = self._tool_to_plugin.get(ns_name)
            tool_def = self._tools.get(ns_name)
            is_always = tool_def is not None and tool_def.always_offered
            if plugin_name in prio or is_always:
                priority.append(entry)
            else:
                rest.append(entry)
```

(also mention `always_offered` in the method docstring: "Tools whose definition declares ``always_offered`` are treated as priority and never cut.")

3b. `apply_mode_policy` — in the drop pass, after the `always_allow_tools` exemption:

```python
                tool_def = self._tools.get(ns_name)
                if tool_def is not None and tool_def.always_offered:
                    kept.append(entry)
                    continue
                caps = set(tool_def.capabilities) if tool_def is not None else set()
```

(the existing `tool_def = self._tools.get(ns_name)` line below is replaced by this block — don't resolve twice).

3c. `get_relevant_tools` — extend both passes. In the candidates pass:

```python
        for entry in cache_snapshot:
            ns_name = entry["function"]["name"]
            plugin_name = plugin_map.get(ns_name)
            if plugin_name is None:
                continue
            tool_def = self._tools.get(ns_name)
            is_always = tool_def is not None and tool_def.always_offered
            if ns_name in hit_names or plugin_name in priority_plugins or is_always:
                candidates.add(plugin_name)
```

In the second pass:

```python
            is_hit = ns_name in hit_names
            is_priority = plugin_name in priority_plugins
            tool_def = self._tools.get(ns_name)
            is_always = tool_def is not None and tool_def.always_offered
            if not is_hit and not is_priority and not is_always:
                continue
```

(update the docstring: "Always includes tools from priority plugins and tools declaring ``always_offered``.")

3d. New method after `exclude_disabled`:

```python
    def usage_guidance_for(self, tools: list[dict[str, Any]]) -> list[str]:
        """Collect usage-guidance fragments for an offered toolset.

        Given the FINAL OpenAI-format toolset of a turn (after tool RAG,
        limiting, mode policy and the user's opt-out), return the
        non-empty ``usage_guidance`` fragments of those tools, in toolset
        order, de-duplicated. The prompt composer renders these into the
        ``[ORCHESTRAZIONE]`` system-prompt block — so the prompt only
        ever teaches tools the model can actually call this turn.

        Args:
            tools: OpenAI-format tool dicts offered to the LLM.

        Returns:
            Ordered, de-duplicated guidance fragments (possibly empty).
        """
        fragments: list[str] = []
        seen: set[str] = set()
        for entry in tools:
            ns_name = entry.get("function", {}).get("name", "")
            tool_def = self._tools.get(ns_name)
            if tool_def is None or not tool_def.usage_guidance:
                continue
            text = tool_def.usage_guidance.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            fragments.append(text)
        return fragments
```

3e. `backend/core/protocols.py` — add to `ToolRegistryProtocol` (after `exclude_disabled`):

```python
    def usage_guidance_for(
        self, tools: list[dict[str, Any]],
    ) -> list[str]: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check core/tool_registry.py core/protocols.py tests/test_tool_registry.py
..\.venv\Scripts\python.exe -m mypy core/tool_registry.py core/protocols.py
git add core/tool_registry.py core/protocols.py tests/test_tool_registry.py
git commit -m "feat(tools): registry honours always_offered in all selection paths; usage_guidance_for()"
```

---

### Task 3: Agent meta-tools declare the contract

**Files:**
- Modify: `backend/plugins/agent/plugin.py` (`get_tools`, the four `ToolDefinition`s)
- Test: `backend/tests/test_agent_plugin.py` (append)

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_agent_plugin.py` (reuse its existing fixture style for building the plugin; if it builds `AgentPlugin()` directly, do the same):

```python
class TestOrchestrationContract:
    """The four meta-tools are always offered and carry usage guidance."""

    def test_meta_tools_always_offered_with_guidance(self):
        plugin = AgentPlugin()
        tools = {t.name: t for t in plugin.get_tools()}
        assert set(tools) == {
            "update_tasks", "write_plan", "spawn_subagent", "ask_user",
        }
        for name, tool in tools.items():
            assert tool.always_offered is True, name
            assert tool.usage_guidance, name
            assert f"`{name}`" in tool.usage_guidance, name
```

(`AgentPlugin` with no ctx exposes all four tools — `cfg is None` branches.)

- [ ] **Step 2: Run test to verify it fails**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_agent_plugin.py -v -k Orchestration`
Expected: FAIL on `always_offered is True`.

- [ ] **Step 3: Implement** — in `backend/plugins/agent/plugin.py`, add to each of the four `ToolDefinition(...)` calls (keep existing args; insert after `capabilities=("planning",)`):

`update_tasks`:
```python
                    always_offered=True,
                    usage_guidance=(
                        "Per qualsiasi lavoro non banale (più passi o più "
                        "strumenti), chiama `update_tasks` PRIMA di iniziare "
                        "per creare la checklist, poi richiamalo man mano: un "
                        "passo diventa `in_progress` quando lo inizi e "
                        "`completed` appena finito. La checklist è mostrata "
                        "in un pannello dedicato: non duplicarla come elenco "
                        "nel testo della chat."
                    ),
```

`write_plan`:
```python
                    always_offered=True,
                    usage_guidance=(
                        "Se il lavoro richiede una strategia, o il risultato "
                        "richiesto È un piano/documento/strategia, scrivilo "
                        "con `write_plan` (compare in un pannello dedicato) e "
                        "tienilo aggiornato man mano che procedi. NON "
                        "scaricare il piano come testo in chat: nella "
                        "risposta riporta solo una sintesi di 1-2 frasi."
                    ),
```

`spawn_subagent`:
```python
                    always_offered=True,
                    usage_guidance=(
                        "Usa `spawn_subagent` per delegare una sotto-ricerca "
                        "autocontenuta che ingombrerebbe il contesto "
                        "(esplorazioni, raccolte di informazioni). Fornisci "
                        "un'istruzione completa: il sub-agente non vede la "
                        "conversazione."
                    ),
```

`ask_user`:
```python
                    always_offered=True,
                    usage_guidance=(
                        "Qualsiasi domanda all'utente passa da `ask_user` — "
                        "MAI domande in testo libero nella risposta. Raccogli "
                        "TUTTE le domande in un'unica chiamata (l'utente le "
                        "vede come wizard) e falla subito, prima di iniziare "
                        "il lavoro: massimo un giro di domande. Non chiedere "
                        "ciò che puoi ragionevolmente assumere."
                    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_agent_plugin.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check plugins/agent/plugin.py tests/test_agent_plugin.py
..\.venv\Scripts\python.exe -m mypy plugins/agent/plugin.py
git add plugins/agent/plugin.py tests/test_agent_plugin.py
git commit -m "feat(agent): meta-tools always offered + colocated usage guidance"
```

---

### Task 4: `services/prompt_composer.py` (pure module)

**Files:**
- Create: `backend/services/prompt_composer.py`
- Test: `backend/tests/test_prompt_composer.py` (new)

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_prompt_composer.py`:

```python
"""Tests for the system-prompt dynamic-context composer."""

from __future__ import annotations

from backend.services.prompt_composer import (
    build_orchestration_block,
    compose_dynamic_context,
)


class TestBuildOrchestrationBlock:

    def test_none_when_no_fragments(self):
        assert build_orchestration_block([]) is None

    def test_none_when_only_blank_fragments(self):
        assert build_orchestration_block(["", "   "]) is None

    def test_renders_intro_and_bullets(self):
        block = build_orchestration_block(["Prima regola.", "Seconda regola."])
        assert block is not None
        assert block.startswith("[ORCHESTRAZIONE]\n")
        assert block.endswith("\n[/ORCHESTRAZIONE]")
        assert "- Prima regola.\n- Seconda regola." in block
        # The fixed intro line sits between the tag and the bullets.
        assert block.index("Regole vincolanti") < block.index("- Prima regola.")


class TestComposeDynamicContext:

    def test_none_when_everything_empty(self):
        assert compose_dynamic_context() is None
        assert compose_dynamic_context(permission_block="  ", aux_context="") is None

    def test_declared_order(self):
        out = compose_dynamic_context(
            permission_block="[AMBITO]",
            orchestration_block="[ORCHESTRAZIONE]",
            aux_context="[MEMORIE]",
            plan_document_block="[PIANO]",
            task_steps_block="[TASK]",
        )
        assert out == (
            "[AMBITO]\n\n[ORCHESTRAZIONE]\n\n[MEMORIE]\n\n[PIANO]\n\n[TASK]"
        )

    def test_empty_blocks_skipped(self):
        out = compose_dynamic_context(
            orchestration_block="[ORCHESTRAZIONE]",
            task_steps_block="[TASK]",
        )
        assert out == "[ORCHESTRAZIONE]\n\n[TASK]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_prompt_composer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — create `backend/services/prompt_composer.py`:

```python
"""AL\\CE — System-prompt dynamic-context composer.

Owns the ORDER of the dynamic blocks injected into the system prompt for a
turn, in one pure, dependency-light module (same spirit as
``permission_mode_policy``): scope/tier steering leads, the orchestration
contract follows, auxiliary context (memories / MCP / whiteboards) sits in
the middle, and the in-flight plan document + task checklist close the
prompt — recency keeps the model continuing the work it already planned.

The orchestration block is composed ONLY from the ``usage_guidance``
fragments of tools actually offered this turn (see
``ToolRegistry.usage_guidance_for``), so the prompt never teaches a tool
the model cannot call — the invariant holds by construction, not by
review.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Fixed intro line of the ``[ORCHESTRAZIONE]`` block. Italian to match the
#: rest of Alice's prompt surface.
_ORCHESTRATION_INTRO = (
    "Questi strumenti orchestrano il tuo lavoro e alimentano pannelli "
    "dedicati dell'interfaccia. Regole vincolanti:"
)


def build_orchestration_block(fragments: Sequence[str]) -> str | None:
    """Render the ``[ORCHESTRAZIONE]`` system-prompt block.

    Args:
        fragments: ``usage_guidance`` texts of the tools offered this
            turn, in toolset order.

    Returns:
        The rendered block, or ``None`` when there is nothing to teach.
    """
    items = [f.strip() for f in fragments if f and f.strip()]
    if not items:
        return None
    bullets = "\n".join(f"- {item}" for item in items)
    return (
        "[ORCHESTRAZIONE]\n"
        f"{_ORCHESTRATION_INTRO}\n"
        f"{bullets}\n"
        "[/ORCHESTRAZIONE]"
    )


def compose_dynamic_context(
    *,
    permission_block: str | None = None,
    orchestration_block: str | None = None,
    aux_context: str | None = None,
    plan_document_block: str | None = None,
    task_steps_block: str | None = None,
) -> str | None:
    """Join the dynamic system-prompt blocks in their declared order.

    The order is the module's contract:

    1. ``permission_block`` — workspace scope + tier steering (leads).
    2. ``orchestration_block`` — the meta-tool contract.
    3. ``aux_context`` — memories, MCP servers, whiteboards (pre-merged).
    4. ``plan_document_block`` — the living plan document.
    5. ``task_steps_block`` — the task checklist (closes the prompt).

    Args:
        permission_block: ``[AMBITO DI LAVORO]`` / ``[MODALITÀ OPERATIVA]``.
        orchestration_block: ``[ORCHESTRAZIONE]``.
        aux_context: Auxiliary context already merged by the caller.
        plan_document_block: Rendered plan document, if any.
        task_steps_block: Rendered task checklist, if any.

    Returns:
        The joined context, or ``None`` when every block is empty.
    """
    blocks = (
        permission_block,
        orchestration_block,
        aux_context,
        plan_document_block,
        task_steps_block,
    )
    parts = [b.strip() for b in blocks if b and b.strip()]
    if not parts:
        return None
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\.venv\Scripts\python.exe -m pytest tests/test_prompt_composer.py -v`
Expected: PASS (7/7).

- [ ] **Step 5: Lint + commit**

```powershell
..\.venv\Scripts\python.exe -m ruff check services/prompt_composer.py tests/test_prompt_composer.py
..\.venv\Scripts\python.exe -m mypy services/prompt_composer.py
git add services/prompt_composer.py tests/test_prompt_composer.py
git commit -m "feat(prompt): pure dynamic-context composer with declared block order"
```

---

### Task 5: Rewire `_assembly.py` to the composer

**Files:**
- Modify: `backend/api/routes/chat/_assembly.py` (tool selection ~377–438; context build ~446–527)

No new unit tests (the WS path isn't unit-testable offline); correctness is guarded by the composer/registry tests plus the existing suite staying green.

- [ ] **Step 1: Remove the now-redundant plan-mode merge.** In the tool-selection section, delete ONLY the manual extend (the meta-tools now arrive via `always_offered` on every path); keep `apply_mode_policy`:

```python
            if tools and policy is not None and not continuum_scope:
                tools = ctx.tool_registry.apply_mode_policy(
                    tools,
                    drop_capabilities=policy.blocked_capabilities,
                    always_allow_tools=policy.always_allow_tools,
                    priority_plugins=policy.priority_plugins,
                )
```

(i.e. drop the `if policy.priority_plugins:` block with `have` / `extra` / `tools.extend(...)`; adjust the comment above to say presence is guaranteed by `always_offered`, this call only reshapes/floats.)

- [ ] **Step 2: Rebuild the context assembly around the composer.** Replace the progressive `memory_context` merging (from `# --- retrieve relevant memories (Phase 9) -----------------` through the `# --- inject workspace scope + permission-tier steering ----` block inclusive) with block-local variables and one compose call. Import at top:

```python
from backend.services.prompt_composer import (
    build_orchestration_block,
    compose_dynamic_context,
)
```

New code (same helpers, same guards, new structure):

```python
        # --- retrieve relevant memories (Phase 9) -----------------
        aux_parts: list[str] = []
        if (
            ctx.memory_service
            and ctx.config.memory.inject_in_context
            and memory_ok
        ):
            try:
                relevant = await ctx.memory_service.search(
                    query=user_content,
                    k=ctx.config.memory.top_k,
                    filter={"scope": "long_term"},
                )
                if relevant:
                    aux_parts.append(
                        _format_memory_context(
                            relevant,
                            ctx.config.memory.context_max_chars,
                        )
                    )
            except Exception as exc:
                logger.warning("Memory retrieval failed: {}", exc)

        # --- active MCP server list (Phase 11) + whiteboards -------
        mcp_ctx = _build_mcp_context(ctx)
        if mcp_ctx:
            aux_parts.append(mcp_ctx)
        wb_ctx = await _build_whiteboard_context(ctx, str(conv_id))
        if wb_ctx:
            aux_parts.append(wb_ctx)

        # --- living plan document + persisted task checklist -------
        plan_doc_block: str | None = None
        if ctx.plan_document_service is not None and not continuum_scope:
            plan_doc = await ctx.plan_document_service.get_document(conv_id)
            if plan_doc:
                plan_doc_block = render_plan_document(plan_doc) or None

        task_steps_block: str | None = None
        if ctx.plan_service is not None:
            plan_steps = await ctx.plan_service.get_plan(conv_id)
            if plan_steps:
                task_steps_block = render_task_steps(plan_steps) or None

        # --- workspace scope + permission-tier steering ------------
        perm_block: str | None = None
        if not continuum_scope:
            perm_block = _build_permission_context(
                ctx, str(conv_id), mode, policy,
            )

        # --- orchestration contract (agentic prompt contract) ------
        # Composed ONLY from the usage_guidance of tools actually offered
        # this turn, so the prompt never teaches a tool the model can't
        # call. Continuum tools carry no guidance ⇒ block absent there.
        orchestration_block: str | None = None
        if tools and ctx.tool_registry is not None:
            orchestration_block = build_orchestration_block(
                ctx.tool_registry.usage_guidance_for(tools),
            )

        memory_context = compose_dynamic_context(
            permission_block=perm_block,
            orchestration_block=orchestration_block,
            aux_context="\n\n".join(aux_parts) if aux_parts else None,
            plan_document_block=plan_doc_block,
            task_steps_block=task_steps_block,
        )
```

Notes:
- `memory_context` keeps its name and `str | None` type — every downstream consumer (`get_system_prompt`, `get_scoped_system_prompt`, `TurnInput.memory_context`) is unchanged.
- The continuum-scope guards are preserved exactly (plan doc and perm block skipped; tasks and aux kept — same as today).
- `tools` is still a `list` here (the `if not tools: tools = None` normalisation stays AFTER the selection section, before this; if it runs before this point in the current file, use `tools or []` in the guidance call instead — verify against the file).

- [ ] **Step 3: Typecheck + targeted tests**

```powershell
..\.venv\Scripts\python.exe -m ruff check api/routes/chat/_assembly.py
..\.venv\Scripts\python.exe -m mypy api/routes/chat/_assembly.py
..\.venv\Scripts\python.exe -m pytest tests/test_tool_loop.py tests/test_pipeline.py tests/test_turn_events.py tests/test_ask_user_multi.py tests/test_plan_service.py -v
```
Expected: clean / PASS.

- [ ] **Step 4: Commit**

```powershell
git add api/routes/chat/_assembly.py
git commit -m "feat(chat): assemble dynamic context via prompt composer; drop redundant plan-mode tool merge"
```

---

### Task 6: Slim tier guidance; retire `always_allow_tools`; fix base prompt

**Files:**
- Modify: `backend/services/permission_mode_policy.py`
- Modify: `backend/core/tool_registry.py` (`apply_mode_policy` signature)
- Modify: `backend/core/protocols.py` (`ToolRegistryProtocol.apply_mode_policy` signature)
- Modify: `backend/api/routes/chat/_assembly.py` (call site)
- Modify: `config/system_prompt.md`
- Test: `backend/tests/test_permission_mode_policy.py` (update)

- [ ] **Step 1: Update the policy module.** In `permission_mode_policy.py`:
  - Delete the `_PLANNING_TOOLS` frozenset and the `always_allow_tools` field on `ModePolicy` (and its docstring entry + the module-docstring paragraph about it). Presence of the meta-tools is now definition-driven (`ToolDefinition.always_offered`).
  - `policy_for` no longer passes `always_allow_tools` (both branches).
  - Slim `_GUIDANCE` — the *how to plan* lives in `[ORCHESTRAZIONE]`; tiers keep only permission semantics:

```python
    PermissionMode.PLAN: (
        "Stai operando in modalità **plan** (sola lettura). **Non puoi "
        "scrivere file né eseguire comandi**: questi strumenti non ti sono "
        "stati forniti apposta. Il tuo compito è capire e pianificare: leggi "
        "e ispeziona ciò che ti serve e definisci il piano con gli strumenti "
        "di pianificazione. Quando il piano è pronto, invita l'utente a "
        "passare a una modalità operativa (auto-edits o autopilot) per "
        "eseguirlo."
    ),
    PermissionMode.AUTOPILOT: (
        "Stai operando in modalità **autopilot**. Hai piena autonomia e "
        "**non verrà chiesta alcuna conferma**: procedi end-to-end fino a "
        "completare l'obiettivo, restando sempre dentro l'ambito di lavoro."
    ),
```

(`STRICT` and `AUTO_EDITS` are already permission-only — unchanged.)

- [ ] **Step 2: Remove the parameter.** In `tool_registry.py` `apply_mode_policy`: drop `always_allow_tools` from the signature, docstring and the drop pass (the `always_offered` exemption from Task 2 remains). Mirror the signature change in `core/protocols.py` `ToolRegistryProtocol.apply_mode_policy` (remove the `always_allow_tools: frozenset[str] = ...` line). In `_assembly.py` remove `always_allow_tools=policy.always_allow_tools,` from the call.

- [ ] **Step 3: Fix the base prompt.** In `config/system_prompt.md`, replace:

```
- Chiedi chiarimenti solo se manca un parametro obbligatorio senza cui non puoi procedere.
```

with:

```
- Chiedi chiarimenti solo se manca un parametro obbligatorio senza cui non puoi procedere; se disponi dello strumento `ask_user`, ogni domanda all'utente passa da lì, mai dal testo della risposta.
```

- [ ] **Step 4: Update tests.** In `tests/test_permission_mode_policy.py`: remove/adjust any assertion on `always_allow_tools` or `_PLANNING_TOOLS`; assertions on the plan/autopilot guidance text mentioning `update_tasks` must be updated to the new texts (assert e.g. `"sola lettura"` for plan, and that `"update_tasks"` is NOT in any guidance). Also fix any `apply_mode_policy(..., always_allow_tools=...)` usage in `tests/test_tool_registry.py` if Task 2 added none (it didn't — verify).

- [ ] **Step 5: Run tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_permission_mode_policy.py tests/test_tool_registry.py tests/test_plugin_models.py -v
..\.venv\Scripts\python.exe -m ruff check services/permission_mode_policy.py core/tool_registry.py api/routes/chat/_assembly.py
..\.venv\Scripts\python.exe -m mypy services/permission_mode_policy.py core/tool_registry.py api/routes/chat/_assembly.py
```
Expected: PASS / clean.

- [ ] **Step 6: Commit**

```powershell
git add services/permission_mode_policy.py core/tool_registry.py api/routes/chat/_assembly.py ../config/system_prompt.md tests/test_permission_mode_policy.py
git commit -m "refactor(policy): tiers keep permission semantics only; retire name-based planning-tool allow-list"
```

---

### Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full offline-safe suite.** From `backend/`, run the documented green-bar subset (see `docs/agent-rework/HANDOFF.md` §2–3 — everything except the hanging WS tests and `test_app.py`):

```powershell
..\.venv\Scripts\python.exe -m pytest tests/ -v --ignore=tests/test_websocket.py --ignore=tests/test_concurrent.py --ignore=tests/test_message_editing.py --ignore=tests/test_branch_conversation.py --ignore=tests/test_voice_ws.py --ignore=tests/test_voice_tool_calling.py --ignore=tests/test_app.py
```
Expected: PASS (0 failures; count ≥ the pre-change baseline).

- [ ] **Step 2: Lint/type the touched surface only** (pre-existing baselines elsewhere are not ours to chase):

```powershell
..\.venv\Scripts\python.exe -m ruff check core/plugin_models.py core/tool_registry.py plugins/agent/plugin.py services/prompt_composer.py services/permission_mode_policy.py api/routes/chat/_assembly.py
..\.venv\Scripts\python.exe -m mypy core/plugin_models.py core/tool_registry.py plugins/agent/plugin.py services/prompt_composer.py services/permission_mode_policy.py
```
Expected: clean.

- [ ] **Step 3: Invariant sweep** — confirm no stale references:

```powershell
# from repo root
git grep -n "_PLANNING_TOOLS"        # expected: no hits
git grep -n "always_allow_tools"     # expected: no hits outside docs/
```

- [ ] **Step 4: No commit** (nothing to commit if clean). Report results.
