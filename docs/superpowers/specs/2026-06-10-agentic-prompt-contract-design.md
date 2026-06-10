# Agentic Prompt Contract — Design

**Data:** 2026-06-10
**Stato:** approvato in conversazione (brainstorming svolto in sessione)
**Ambito:** solo backend (`backend/`), più `config/system_prompt.md`.

## 1. Problema

Il modello locale non usa i meta-tool di orchestrazione (`ask_user`, `write_plan`,
`update_tasks`, `spawn_subagent`): scarica i piani come testo in chat, fa domande
in testo libero, e a "scrivi questo piano" va sui tool filesystem MCP invece che
su `write_plan`. Caso riprodotto: conversazione
`6233a6e7-485e-4f61-9139-97ad798585f5`.

Due cause radice:

1. **Disponibilità non garantita.** Con `tool_rag_enabled: true` il toolset del
   turno è il top-K per similarità embedding + i `priority_plugins`
   (`memory`, `system_info` — il plugin `agent` NON c'è). Fuori dal tier `plan`
   i meta-tool competono nel RAG: per molti messaggi il modello letteralmente
   non li ha. La garanzia esiste solo in `plan` mode
   (`permission_mode_policy._PLANNING_TOOLS` + merge manuale in `_assembly.py`).
2. **Nessun contratto di orchestrazione nel prompt.** `config/system_prompt.md`
   non nomina mai i meta-tool (e "Chiedi chiarimenti solo se…" insegna
   implicitamente il testo libero). Solo la guidance del tier `plan` cita
   `update_tasks`; `write_plan` e `ask_user` non sono citati in nessun prompt.
   L'unica documentazione è la description del tool — segnale debole per un
   modello locale, visibile solo se il tool passa il RAG.

## 2. Principi (convenzioni adottate)

- **I meta-tool non passano mai dalla retrieval.** La presenza dei tool di
  orchestrazione è una proprietà del sistema, dichiarata sulla definizione del
  tool, non un esito probabilistico né un hack name-based in un modulo centrale.
- **La guidance vive accanto al tool che governa** (pattern MCP
  `instructions`/skills): chi definisce il tool fornisce il frammento di prompt
  che insegna quando usarlo.
- **Invariante bidirezionale per costruzione**: il blocco di orchestrazione è
  composto SOLO dai frammenti dei tool effettivamente offerti nel turno ⇒ il
  prompt non governa mai tool assenti.
- **Separazione dei concern**: *policy* (cosa è permesso — tier), *capability*
  (cosa è offerto — registry), *guidance* (come comportarsi — frammenti +
  composer). Oggi sono impastati in `ModePolicy`.
- **Ordine del prompt dichiarato in un posto solo** (composer puro, testabile).

## 3. Design

### 3.1 `ToolDefinition` — due campi nuovi (`core/plugin_models.py`)

```python
always_offered: bool = False
usage_guidance: str | None = None
```

- `always_offered=True` ⇒ il tool **sopravvive alla selezione**: incluso
  dall'esito del tool-RAG (`get_relevant_tools`), mai tagliato da `limit_tools`,
  esente dal capability-drop di `apply_mode_policy`. NON esente da: filtro di
  connection-status (plugin giù ⇒ tool non offerto) e opt-out esplicito
  dell'utente (`exclude_disabled` — la scelta esplicita dell'utente vince).
- `usage_guidance` ⇒ frammento markdown (italiano, 2–5 righe) che il composer
  raccoglie nel blocco `[ORCHESTRAZIONE]` quando il tool è offerto.
- `to_openai_format()` invariato: la guidance NON viaggia nello schema.

### 3.2 Registry (`core/tool_registry.py`)

- `get_relevant_tools`: oltre a hit + priority-plugin, include ogni tool con
  `always_offered=True` (stesso filtro di status, stessa dedup).
- `limit_tools`: i tool `always_offered` sono trattati come prioritari (mai
  tagliati dal cap).
- `apply_mode_policy`: il drop per capability esenta i tool `always_offered`
  (oltre all'attuale `always_allow_tools`, che verrà poi rimosso — §3.5).
- Nuovo metodo `usage_guidance_for(tools: list[dict]) -> list[str]`: dato il
  toolset OpenAI-format FINALE del turno, ritorna i frammenti `usage_guidance`
  (ordinati come i tool, dedup, stripped, solo non-vuoti).

### 3.3 Plugin `agent` (`plugins/agent/plugin.py`)

I 4 meta-tool dichiarano `always_offered=True` e portano la propria
`usage_guidance` (testi vincolanti, scritti per modelli locali):

- **ask_user** — qualsiasi domanda all'utente passa da `ask_user`, mai testo
  libero; tutte le domande in UNA chiamata (wizard), subito, prima di iniziare;
  massimo un giro; non chiedere ciò che si può ragionevolmente assumere.
- **write_plan** — se il lavoro è multi-step o il deliverable È un
  piano/strategia/documento: va in `write_plan` (pannello dedicato), NON come
  testo in chat; in chat solo una sintesi di 1–2 frasi; tenerlo aggiornato.
- **update_tasks** — per lavoro non banale creare la checklist PRIMA di
  eseguire; `in_progress` quando un passo inizia, `completed` appena finito;
  visibile in UI, non duplicarla in chat.
- **spawn_subagent** — delegare sotto-ricerche autocontenute che
  ingombrerebbero il contesto; istruzione completa (non vede la conversazione).

I flag config esistenti (`agent.planning/clarification/delegation`) continuano
a gateare l'esposizione: un tool non esposto non è mai "always offered".

Nota: `_subagent._resolve_subagent_tools` esclude già i meta-tool agent ⇒
nessuna ricorsione e nessun impatto sul budget tool dei subagent.

### 3.4 `services/prompt_composer.py` — nuovo modulo puro

Dependency-light (stile `permission_mode_policy.py`), possiede l'ordine del
contesto dinamico del system prompt:

```python
def build_orchestration_block(fragments: Sequence[str]) -> str | None:
    """[ORCHESTRAZIONE] + riga intro fissa + frammenti; None se vuoto."""

def compose_dynamic_context(
    *,
    permission_block: str | None,      # [AMBITO DI LAVORO] + [MODALITÀ OPERATIVA]
    orchestration_block: str | None,   # [ORCHESTRAZIONE]
    aux_context: str | None,           # memorie + MCP + whiteboard (già fusi)
    plan_document_block: str | None,   # [PIANO] (render_plan_document)
    task_steps_block: str | None,      # [TASK] (render_task_steps)
) -> str | None:
    """Join non-vuoti con '\n\n' nell'ordine dichiarato sopra."""
```

Ordine razionale: permessi/scope e contratto in testa (leading attention);
piano e task in coda (recency per il lavoro in corso) — conserva l'ordine
attuale di `_assembly.py` aggiungendo l'orchestrazione nel gruppo di testa.

Riga intro fissa del blocco: gli strumenti elencati orchestrano il lavoro e
alimentano pannelli dedicati dell'interfaccia; le regole sono vincolanti.

### 3.5 Rewiring e pulizia

- `_assembly.py`: il `memory_context` passato a `get_system_prompt` è prodotto
  da `compose_dynamic_context(...)`; i frammenti arrivano da
  `usage_guidance_for(tools)` calcolato sul toolset FINALE (dopo RAG/limiti/
  policy/opt-out). Il merge manuale plan-mode (`get_tools_for_plugins` +
  extend) viene rimosso: ridondante con `always_offered`. Vale per ogni scope
  (per Continuum i tool non hanno guidance ⇒ blocco assente, comportamento
  invariato).
- `permission_mode_policy.py`: rimossi `_PLANNING_TOOLS` e il campo
  `always_allow_tools` (la garanzia è definition-driven); `apply_mode_policy`
  perde il parametro. `priority_plugins=("agent",)` resta per il
  float-in-testa in `plan` mode. I testi `_GUIDANCE` si snelliscono al solo
  concern del tier (permessi): via le menzioni di `update_tasks` da `plan` e
  `autopilot` — il *come* pianificare vive nel contratto.
- `config/system_prompt.md`: la riga sui chiarimenti rimanda ad `ask_user`
  quando disponibile.

## 4. Test

- `test_plugin_models.py`: default dei campi nuovi; guidance non presente in
  `to_openai_format()`.
- `test_tool_registry.py`: always_offered incluso dal fallback/RAG path;
  `limit_tools` non lo taglia; `apply_mode_policy` non lo droppa;
  `usage_guidance_for` (ordine, dedup, vuoti).
- `test_agent_plugin.py`: i 4 tool hanno `always_offered=True` e guidance
  non vuota.
- `test_prompt_composer.py` (nuovo): golden dell'ordine; blocchi None/vuoti
  saltati; orchestrazione None senza frammenti; intro presente con frammenti.
- `test_permission_mode_policy.py`: aggiornato (niente `always_allow_tools`;
  testi tier snelliti).
- Smoke manuale (fuori CI): rigiocare la conversazione di test — attesi
  wizard `ask_user`, documento in `write_plan`, checklist in `update_tasks`,
  chat con sola sintesi.

## 5. Non-obiettivi

- Nessuna modifica al percorso subagent e al toolset voice.
- Nessuna euristica post-hoc "piano scaricato in chat ⇒ reminder" (si valuta
  solo se il contratto non basta).
- Nessun cambio al FE (l'intent "Pianifica un lavoro" resta com'è; eventuale
  hint di turno è follow-up separato).
- Nessuna nuova dipendenza.
