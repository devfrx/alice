<template>
    <div class="ec">
        <!-- Header: name + type + actions -->
        <div class="ec__header">
            <div class="ec__identity">
                <span class="ec__name">{{ entity.name }}</span>
                <span class="ec__type">{{ entity.entityType }}</span>
            </div>
            <div class="ec__actions">
                <button class="ec__action-btn ec__action-btn--add" title="Aggiungi osservazione"
                    aria-label="Aggiungi osservazione" @click="$emit('addObservation', entity.name)">+</button>
                <button class="ec__action-btn ec__action-btn--delete" title="Elimina entità" aria-label="Elimina entità"
                    @click="$emit('delete', entity.name)">✕</button>
            </div>
        </div>

        <!-- Observations -->
        <div v-if="entity.observations.length > 0" class="ec__observations">
            <div v-for="(obs, idx) in entity.observations" :key="idx" class="ec__obs">
                <span class="ec__obs-text">{{ obs }}</span>
                <button class="ec__obs-delete" title="Rimuovi osservazione" aria-label="Rimuovi osservazione"
                    @click="$emit('deleteObservation', entity.name, obs)">✕</button>
            </div>
        </div>
        <div v-else class="ec__no-obs">Nessuna osservazione</div>

        <!-- Relations -->
        <div v-if="relations.length > 0" class="ec__relations">
            <div v-for="rel in relations" :key="`${rel.from}-${rel.relationType}-${rel.to}`" class="ec__rel">
                <span class="ec__rel-label">
                    <template v-if="rel.from === entity.name">
                        → <em>{{ rel.relationType }}</em> → {{ rel.to }}
                    </template>
                    <template v-else>
                        {{ rel.from }} → <em>{{ rel.relationType }}</em> →
                    </template>
                </span>
                <button class="ec__rel-delete" title="Elimina relazione" aria-label="Elimina relazione"
                    @click="$emit('deleteRelation', rel)">✕</button>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import type { KGEntity, KGRelation } from '../../types/mcpMemory'

defineProps<{
    entity: KGEntity
    relations: KGRelation[]
}>()

defineEmits<{
    delete: [name: string]
    addObservation: [entityName: string]
    deleteObservation: [entityName: string, observation: string]
    deleteRelation: [relation: KGRelation]
}>()
</script>

<style scoped>
.ec {
    padding: var(--space-3, 12px);
    background: var(--bg-secondary, #13161c);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    transition: border-color 0.2s;
}

.ec:hover {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

/* ── Header ────────────────────────────────────────── */
.ec__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2, 8px);
}

.ec__identity {
    display: flex;
    align-items: center;
    gap: var(--space-2, 8px);
}

.ec__name {
    font-size: var(--text-sm, 0.8125rem);
    font-weight: 600;
    color: var(--text-primary, #e8e4de);
}

.ec__type {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 9999px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    background: rgba(100, 160, 220, 0.12);
    color: rgba(100, 160, 220, 0.9);
}

.ec__actions {
    display: flex;
    gap: var(--space-1, 4px);
}

.ec__action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm, 4px);
    border: none;
    background: transparent;
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.2s, color 0.2s;
}

.ec__action-btn--add {
    color: var(--accent, #c9a84c);
    font-size: 0.9rem;
    font-weight: 700;
}

.ec__action-btn--add:hover {
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
}

.ec__action-btn--delete {
    color: var(--text-muted, #5c584f);
}

.ec__action-btn--delete:hover {
    background: rgba(220, 80, 80, 0.12);
    color: rgba(220, 80, 80, 0.9);
}

/* ── Observations ──────────────────────────────────── */
.ec__observations {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: var(--space-2, 8px);
}

.ec__obs {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1, 4px);
    padding: 2px 0;
}

.ec__obs-text {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #8a8578);
    line-height: 1.4;
    flex: 1;
    word-break: break-word;
}

.ec__obs-text::before {
    content: "• ";
    color: var(--accent-dim, rgba(201, 168, 76, 0.3));
}

.ec__obs-delete {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 2px;
    border: none;
    background: transparent;
    color: var(--text-muted, #5c584f);
    font-size: 0.6rem;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s, background 0.2s, color 0.2s;
    flex-shrink: 0;
    margin-top: 1px;
}

.ec__obs:hover .ec__obs-delete {
    opacity: 1;
}

.ec__obs-delete:hover {
    background: rgba(220, 80, 80, 0.12);
    color: rgba(220, 80, 80, 0.9);
}

.ec__no-obs {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-muted, #5c584f);
    font-style: italic;
    margin-bottom: var(--space-2, 8px);
}

/* ── Relations ─────────────────────────────────────── */
.ec__relations {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1, 4px);
    padding-top: var(--space-1, 4px);
    border-top: 1px solid var(--border, rgba(255, 255, 255, 0.04));
}

.ec__rel {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 1px 8px;
    border-radius: 9999px;
    background: rgba(201, 168, 76, 0.06);
    border: 1px solid rgba(201, 168, 76, 0.12);
    font-size: 0.65rem;
    color: var(--text-secondary, #8a8578);
}

.ec__rel em {
    color: var(--accent, #c9a84c);
    font-style: normal;
    font-weight: 500;
}

.ec__rel-label {
    white-space: nowrap;
}

.ec__rel-delete {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--text-muted, #5c584f);
    font-size: 0.55rem;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s, background 0.2s, color 0.2s;
}

.ec__rel:hover .ec__rel-delete {
    opacity: 1;
}

.ec__rel-delete:hover {
    background: rgba(220, 80, 80, 0.15);
    color: rgba(220, 80, 80, 0.9);
}
</style>
