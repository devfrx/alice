<script setup lang="ts">
import { computed } from 'vue'

import UiToggle from '../ui/UiToggle.vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()

/** v-model proxy: true = light theme. */
const isLight = computed({
    get: () => settingsStore.settings.ui.theme === 'light',
    set: (v: boolean) => {
        settingsStore.settings.ui.theme = v ? 'light' : 'dark'
    },
})
</script>

<template>
    <UiToggle v-model="isLight" class="brand-theme-toggle"
        :aria-label="isLight ? 'Tema chiaro attivo' : 'Tema scuro attivo'" />
</template>

<style scoped>
/* Hook for any positioning the parent relied on; visual switch lives in UiToggle. */
.brand-theme-toggle {
    flex-shrink: 0;
}
</style>
