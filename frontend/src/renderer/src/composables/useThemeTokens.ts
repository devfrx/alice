/**
 * useThemeTokens — Legge CSS custom property a runtime per i consumer JS
 * (ECharts, xterm) che non possono usare var(--…) direttamente.
 * Si aggiorna quando cambia `data-theme` su <html>.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue'

export function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function readTokens<K extends string>(names: readonly K[]): Record<K, string> {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(names.map((n) => [n, style.getPropertyValue(n).trim()])) as Record<
    K,
    string
  >
}

/**
 * Ritorna una mappa reattiva token→valore che si rilegge al cambio tema.
 * Usare i valori dentro un watch per ricostruire la config della libreria.
 */
export function useThemeTokens<K extends string>(names: readonly K[]): Ref<Record<K, string>> {
  const tokens = ref(readTokens(names)) as Ref<Record<K, string>>
  const observer = new MutationObserver(() => {
    tokens.value = readTokens(names)
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  onBeforeUnmount(() => observer.disconnect())
  return tokens
}
