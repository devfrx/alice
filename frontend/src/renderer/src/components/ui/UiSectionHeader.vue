<script setup lang="ts">
/**
 * UiSectionHeader — Section title row: title + optional description on the
 * left, actions slot on the right. Standardizes the header pattern used
 * across settings panels and managers.
 */
export interface UiSectionHeaderProps {
  title: string
  description?: string
  size?: 'sm' | 'md'
  /** Heading level for a11y/document outline (rendered tag). */
  level?: 2 | 3 | 4
}

withDefaults(defineProps<UiSectionHeaderProps>(), {
  description: '',
  size: 'md',
  level: 3
})
</script>

<template>
  <div class="ui-section-header" :class="`ui-section-header--${size}`">
    <div class="ui-section-header__text">
      <component :is="`h${level}`" class="ui-section-header__title">{{ title }}</component>
      <p v-if="description" class="ui-section-header__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="ui-section-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.ui-section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
}

.ui-section-header__text {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.ui-section-header__title {
  margin: 0;
  font-family: var(--font-display);
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}

.ui-section-header--md .ui-section-header__title {
  font-size: var(--text-md);
}

.ui-section-header--sm .ui-section-header__title {
  font-size: var(--text-sm);
}

.ui-section-header__description {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--leading-relaxed);
}

.ui-section-header__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>
