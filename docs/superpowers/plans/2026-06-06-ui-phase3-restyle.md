# AL\CE — UI Revamp Fase 3 · Piano (restyle superfici rimanenti)

**Data:** 2026-06-06 · **Branch:** `refactor/ui-claude-revamp`
**Metodo:** subagent-driven-development (implementer + review per task)

## Decisioni (validate con l'utente)
- **Restyle standalone**: le viste restano route a pagina intera (nessuna conversione in moduli, nessun cambio architetturale/logico).
- **Settings: restyle completo** (tutti i pannelli).
- **Aderente al linguaggio**: replico fedelmente l'estetica già validata in Fase 1/2. Nessun nuovo elemento visivo/feature.
- `HybridView.vue` è **dead code** (route `/hybrid` reindirizza a Workspace, nessun import) → escluso dal restyle, da eliminare a parte.

## Design Contract (vale per OGNI file toccato)
1. **Colori → solo token** di `assets/styles/theme.css`. Nessun hex/rgb/rgba/hsl letterale. Ombre via `var(--shadow-*)`. Tinte/overlay via token (`--surface-*`, `--accent-soft/dim/glow/border`, `--white-*`, `--black-*`, stati `--success/-light/-glow`, ecc.). Rimuovere i fallback hardcoded in `var(--x, #hex)` → `var(--x)` (verificare che il token esista; se manca, mappare al token corretto esistente — es. `--surface-1`).
2. **Niente glass/semitrasparenza come chrome**: rimuovere `backdrop-filter`/`blur()` di contorno e sfondi rgba semitrasparenti → superfici solide `var(--surface-*)` + ombre morbide. *Eccezione*: effetti artistici del visualizzatore vocale (P3-1) — preservare l'effetto derivando i colori dai token accent/surface. Gli scrim dietro i modali possono restare ma tokenizzati (`var(--black-light)`), senza blur sul pannello.
3. **Heading/titoli → `var(--font-display)`** (serif) per titoli sezione/pannello; corpo `var(--font-sans)`; monospace `var(--font-mono)` (sostituire stack hardcoded).
4. **Bordi minimi**: rimuovere bordi di separazione/marcati; al massimo una hairline `1px solid var(--border)` dove serve; preferire elevazione/superficie. Stato attivo via `--surface-selected`/accent sottile, non bordi colorati pesanti.
5. **Empty state**: usare `components/ui/UiEmptyState.vue` dove il contesto è uno zero-state di pannello/lista; altrimenti riportare l'empty state bespoke allo stile minimale (icona muta ~0.4 opacity, titolo `--text-secondary`/`--text-sm`, sottotitolo `--text-muted`).
6. **Densità compatta**, spaziature via `--space-*`.
7. **Vincoli**: nessun cambio di logica/comportamento/props/store/contratti API-WS. CSS scoped, no `any`. Preservare tutte le funzionalità esistenti (in particolare la logica teleport recente di `ModelSelector`).
8. **Verifica**: `npm run typecheck` pulito; nessuna regressione nei test vitest.

## Task (file disgiunti tra task → parallelizzabili in wave)

### P3-1 — Assistant: visuali immersive (judgment)
`components/assistant/`: AmbientBackground.vue, HybridStateWaveform.vue, AliceOrb.vue, ImmersiveCADCanvas.vue
Tokenizzare i colori-effetto (40+ rgba) su token accent/surface preservando l'effetto; rimuovere blur di chrome (non quello d'effetto).

### P3-2 — Assistant: superficie conversazione
`views/AssistantView.vue`; `components/assistant/`: AssistantResponse.vue, AssistantTranscript.vue, ConversationDrawer.vue, StatusBubbles.vue, ModeSwitcher.vue, StatePreviewControls.vue, AssistantFab.vue
Rimuovere glass/backdrop-filter, ombre rgba→`--shadow-*`, fallback hex→token, titoli serif, bordi minimi.

### P3-3 — Voce
`components/voice/`: MicrophoneButton.vue, TranscriptOverlay.vue, VoiceSettings.vue, VoiceIndicator.vue, AudioPlayback.vue

### P3-4 — Settings: shell + UI modelli
`views/SettingsView.vue`; `components/settings/`: ModelManager.vue, ModelSelector.vue (**preservare teleport/posizionamento C4-c**)
Rimuovere blur glass della nav; tokenizzare; titoli serif.

### P3-5 — Settings: data managers (cleanup fallback)
`components/settings/`: MemoryManager.vue, VectorStoreManager.vue, McpManager.vue, KnowledgeGraphManager.vue, EntityCard.vue, PluginManagement.vue, EmailSettings.vue
Rimuovere ~36 fallback hardcoded nei `var(--x, #hex)`.

### P3-6 — Services
`views/ServicesView.vue`; `components/services/`: ServiceCard.vue, TrellisConfigCard.vue (monospace hardcoded), TrellisSetupGuideModal.vue (ombre/blur hardcoded)

### P3-7 — Calendar · Email · Whiteboard · Board
`components/calendar/`: CalendarWidget.vue, CalendarEventModal.vue
`components/email/`: InboxList.vue, EmailViewer.vue, EmailFoldersSidebar.vue
`components/whiteboard/`: WhiteboardListSidebar.vue, TldrawCanvas.vue (leggero, integrazione tldraw)
`components/board/`: ArtifactCard.vue (backdrop-filter), ArtifactPreview3D.vue, ArtifactBoardFilters.vue
`views/`: CalendarPageView.vue, EmailPageView.vue, WhiteboardPageView.vue, ArtifactBoardView.vue (verifica/rifinitura)

### P3-8 — Plugins · Branding · Home
`components/plugins/`: NetworkProbePanel.vue, SearchResultsPanel.vue (1 rgba), CalendarView.vue, WeatherWidget.vue
`components/branding/`: BrandAsset.vue, BrandWordmark.vue, BrandThemeToggle.vue (verifica)
`views/HomeView.vue` (verifica/rifinitura)

## Esecuzione
Wave parallele di ~3 task (file disgiunti), poi review spec+qualità per task, fix, commit per superficie. Typecheck centrale dopo ogni wave; vitest deve restare verde.
