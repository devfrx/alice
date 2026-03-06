<template>
  <div class="home-view">
    <h1>O.M.N.I.A.</h1>
    <p class="subtitle">Orchestrated Modular Network for Intelligent Automation</p>
    <router-link to="/chat" class="start-btn">Avvia Chat</router-link>
  </div>
</template>

<script setup lang="ts">
// HomeView — landing page placeholder
</script>

<style scoped>
.home-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-primary);
}

h1 {
  font-size: var(--text-3xl);
  letter-spacing: var(--tracking-widest);
  font-weight: var(--weight-light);
  text-shadow: var(--accent-text-glow);
}

.subtitle {
  font-size: var(--text-md);
  color: var(--text-secondary);
  opacity: var(--opacity-soft);
  margin-top: var(--space-2);
}

.start-btn {
  margin-top: var(--space-8);
  padding: var(--space-3) var(--space-8);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  text-decoration: none;
  transition: all var(--transition-normal);
}

.start-btn:hover {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}
</style>
