<script setup lang="ts">
/**
 * CalendarPageView — Full-page calendar with CRUD.
 */
import CalendarView from '../components/plugins/CalendarView.vue'
</script>

<template>
    <div class="calendar-page">
        <CalendarView />
    </div>
</template>

<style scoped>
.calendar-page {
    height: 100%;
    width: 100%;
    min-width: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    align-self: stretch;
    background: var(--surface-0);
    color: var(--text-primary);
}
</style>
