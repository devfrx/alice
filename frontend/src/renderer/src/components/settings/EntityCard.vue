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
    padding: var(--space-3);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    transition: border-color var(--transition-fast);
}

.ec:hover {
    border-color: var(--border-hover);
}

/* ── Header ────────────────────────────────────────── */
.ec__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2);
}

.ec__identity {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.ec__name {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
}

.ec__type {
    font-size: var(--text-2xs);
    padding: 1px 6px;
    border-radius: var(--radius-pill);
    font-weight: var(--weight-medium);
    text-transform: uppercase;
    letter-spacing: var(--tracking-normal);
    background: var(--accent-dim);
    color: var(--accent);
}

.ec__actions {
    display: flex;
    gap: var(--space-1);
}

.ec__action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
    border: none;
    background: transparent;
    font-size: var(--text-xs);
    cursor: pointer;
    transition: all var(--transition-fast);
}

.ec__action-btn--add {
    color: var(--accent);
    font-size: var(--text-sm);
    font-weight: var(--weight-bold);
}

.ec__action-btn--add:hover {
    background: var(--accent-dim);
}

.ec__action-btn--delete {
    color: var(--text-muted);
}

.ec__action-btn--delete:hover {
    background: var(--danger-light);
    color: var(--danger);
}

/* ── Observations ──────────────────────────────────── */
.ec__observations {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: var(--space-2);
}

.ec__obs {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
    padding: 2px 0;
}

.ec__obs-text {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
    flex: 1;
    word-break: break-word;
}

.ec__obs-text::before {
    content: "• ";
    color: var(--text-muted);
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
    color: var(--text-muted);
    font-size: var(--text-2xs);
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), background var(--transition-fast), color var(--transition-fast);
    flex-shrink: 0;
    margin-top: 1px;
}

.ec__obs:hover .ec__obs-delete {
    opacity: 1;
}

.ec__obs-delete:hover {
    background: var(--danger-light);
    color: var(--danger);
}

.ec__no-obs {
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-style: italic;
    margin-bottom: var(--space-2);
}

/* ── Relations ─────────────────────────────────────── */
.ec__relations {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    padding-top: var(--space-1);
    border-top: 1px solid var(--border);
}

.ec__rel {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 1px 8px;
    border-radius: var(--radius-pill);
    background: var(--accent-faint);
    border: 1px solid var(--accent-subtle);
    font-size: var(--text-2xs);
    color: var(--text-secondary);
}

.ec__rel em {
    color: var(--accent);
    font-style: normal;
    font-weight: var(--weight-medium);
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
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--text-muted);
    font-size: 0.55rem;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--transition-fast), background var(--transition-fast), color var(--transition-fast);
}

.ec__rel:hover .ec__rel-delete {
    opacity: 1;
}

.ec__rel-delete:hover {
    background: var(--danger-light);
    color: var(--danger);
}
</style>
