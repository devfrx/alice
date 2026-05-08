<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()

const isLight = computed(() => settingsStore.settings.ui.theme === 'light')

function toggleTheme(): void {
    settingsStore.settings.ui.theme = isLight.value ? 'dark' : 'light'
}
</script>

<template>
    <button class="brand-theme-toggle sv__toggle" :class="{ 'sv__toggle--on': isLight }" type="button" role="switch"
        :aria-label="isLight ? 'Tema chiaro attivo' : 'Tema scuro attivo'" :aria-checked="isLight"
        :title="isLight ? 'Tema chiaro' : 'Tema scuro'" @click="toggleTheme">
        <span class="sv__toggle-thumb" />
    </button>
</template>

<style scoped>
/* Allinea al pattern .sv__toggle usato in SettingsView, EmailSettings, VectorStoreManager. */
.sv__toggle {
    position: relative;
    width: 36px;
    height: 20px;
    border: none;
    border-radius: var(--radius-pill);
    background: var(--surface-3);
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
    transition: background var(--duration-fast) ease;
}

.sv__toggle--on {
    background: var(--accent);
}

.sv__toggle:focus-visible {
    outline: none;
    box-shadow: var(--shadow-focus);
}

.sv__toggle-thumb {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-primary);
    transition:
        transform var(--duration-fast) ease,
        background var(--duration-fast) ease;
}

.sv__toggle--on .sv__toggle-thumb {
    transform: translateX(16px);
}
</style>