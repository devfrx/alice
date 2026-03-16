<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { api } from '../../services/api'

interface WeatherData {
  city: string
  temperature: number
  feels_like: number
  humidity: number
  wind_speed: number
  condition: string
  uv_index: number
  timestamp: string
}

const props = defineProps<{ city?: string }>()
const emit = defineEmits<{ forecast: [] }>()

const REFRESH_MS = 10 * 60 * 1000

const weatherIcons: Record<string, string> = {
  clear: '☀️', cloudy: '☁️', partly_cloudy: '⛅',
  rain: '🌧️', snow: '❄️', thunderstorm: '⛈️',
  fog: '🌫️', wind: '💨', default: '🌡️'
}

const weather = ref<WeatherData | null>(null)
const loading = ref(true)
const error = ref(false)
const expanded = ref(false)
const lastUpdated = ref('')
let refreshTimer: ReturnType<typeof setInterval> | null = null

/** Map condition text from Open-Meteo to an emoji icon key. */
function conditionToIcon(condition: string): string {
  const c = condition.toLowerCase()
  if (c.includes('thunder')) return weatherIcons.thunderstorm
  if (c.includes('snow') || c.includes('sleet')) return weatherIcons.snow
  if (c.includes('rain') || c.includes('drizzle') || c.includes('shower')) return weatherIcons.rain
  if (c.includes('fog') || c.includes('mist')) return weatherIcons.fog
  if (c.includes('wind')) return weatherIcons.wind
  if (c.includes('partly') || c.includes('partly cloudy')) return weatherIcons.partly_cloudy
  if (c.includes('overcast') || c.includes('cloudy')) return weatherIcons.cloudy
  if (c.includes('clear') || c.includes('sunny')) return weatherIcons.clear
  return weatherIcons.default
}

const tooltip = computed(() =>
  lastUpdated.value ? `Last updated: ${lastUpdated.value}` : 'Loading…'
)

async function fetchWeather(): Promise<void> {
  try {
    loading.value = !weather.value // only show spinner on first load
    error.value = false
    const res = await api.executePluginTool<WeatherData>(
      'weather', 'get_weather', props.city ? { city: props.city } : {}
    )
    if (res.success) {
      weather.value = res.content
      lastUpdated.value = new Date().toLocaleTimeString()
    } else {
      error.value = true
    }
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchWeather()
  refreshTimer = setInterval(fetchWeather, REFRESH_MS)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="weather" :title="tooltip" @click="expanded = !expanded">
    <!-- Loading -->
    <div v-if="loading" class="weather__compact weather__compact--loading">
      <span class="weather__pulse" />
      <span class="weather__text--secondary">…</span>
    </div>

    <!-- Error -->
    <div v-else-if="error || !weather" class="weather__compact weather__compact--error">
      <span>⚠️</span>
      <span class="weather__text--secondary">N/A</span>
    </div>

    <!-- Compact (default) -->
    <div v-else class="weather__compact">
      <span class="weather__icon">{{ conditionToIcon(weather.condition) }}</span>
      <span class="weather__temp">{{ Math.round(weather.temperature) }}°</span>
      <span class="weather__city">{{ weather.city }}</span>
    </div>

    <!-- Expanded dropdown -->
    <Transition name="weather-drop">
      <div v-if="expanded && weather && !error" class="weather__details">
        <div class="weather__row">
          <span>Feels like</span><span>{{ Math.round(weather.feels_like) }}°C</span>
        </div>
        <div class="weather__row">
          <span>Humidity</span><span>{{ weather.humidity }}%</span>
        </div>
        <div class="weather__row">
          <span>Wind</span><span>{{ weather.wind_speed }} km/h</span>
        </div>
        <div class="weather__row">
          <span>UV Index</span><span>{{ weather.uv_index }}</span>
        </div>
        <button class="weather__forecast-btn" @click.stop="emit('forecast')">
          View forecast →
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.weather {
  position: relative;
  cursor: pointer;
  user-select: none;
  font-family: inherit;
}

.weather__compact {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 8px;
  border-radius: 6px;
  color: var(--text-primary, #eee);
  font-size: 13px;
  transition: background 0.2s;
}

.weather__compact:hover {
  background: rgba(255, 255, 255, 0.06);
}

.weather__icon {
  font-size: 16px;
  line-height: 1;
}

.weather__temp {
  font-weight: 600;
}

.weather__city {
  color: var(--text-secondary, #aaa);
  font-size: 12px;
}

.weather__text--secondary {
  color: var(--text-secondary, #aaa);
}

/* Pulsing loading placeholder */
.weather__pulse {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-secondary, #aaa);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 0.3;
  }

  50% {
    opacity: 1;
  }
}

/* Expanded dropdown */
.weather__details {
  position: absolute;
  top: 36px;
  left: 0;
  min-width: 180px;
  padding: 10px 12px;
  background: var(--bg-secondary, #16213e);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  z-index: var(--z-dropdown);
  font-size: 12px;
  color: var(--text-primary, #eee);
}

.weather__row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.weather__row:last-of-type {
  border-bottom: none;
}

.weather__row span:first-child {
  color: var(--text-secondary, #aaa);
}

.weather__forecast-btn {
  margin-top: 8px;
  width: 100%;
  padding: 5px 0;
  border: none;
  border-radius: 4px;
  background: var(--accent, #e94560);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.weather__forecast-btn:hover {
  opacity: 0.85;
}

/* Transition */
.weather-drop-enter-active,
.weather-drop-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}

.weather-drop-enter-from,
.weather-drop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
