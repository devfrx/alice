<script setup lang="ts">
/**
 * CalendarPageView — Full-page calendar with CRUD.
 */
import CalendarView from '../components/plugins/CalendarView.vue'
</script>

<template>
  <div class="calendar-page" aria-label="Calendario">
    <div class="calendar-page__frame">
      <CalendarView />
    </div>
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
  box-sizing: border-box;
  padding: var(--space-2-5);
  background: var(--surface-0);
  color: var(--text-primary);
}

/* Floating panel: detached from the window edges, rounded, bordered —
   mirrors the EmailPageView recipe. The inner CalendarView fills it. */
.calendar-page__frame {
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--surface-1);
}
</style>
