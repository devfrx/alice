/**
 * icons.ts — Centralized icon registry for AL\CE.
 *
 * Every icon used across the application is defined here as a named entry
 * mapping to a Solar icon ID from the Iconify ecosystem.
 *
 * To swap a single icon, change its `icon` value.
 * To swap the entire icon set, replace the `icon` values with IDs from
 * any other Iconify-compatible set (e.g. 'ph:gear-fill', 'fluent:settings-24-filled').
 *
 * Usage in Vue templates: <AppIcon name="settings" :size="16" />
 * Usage in JS/HTML strings: getIconSvgString('copy', 16)
 *
 * Icon set: Solar Bold (rounded filled) — https://icon-sets.iconify.design/solar/
 */

import { getIconData, iconToSVG } from '@iconify/utils'
import { icons as solarIcons } from '@iconify-json/solar'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IconDef {
  /** Iconify icon ID — format: 'prefix:name', e.g. 'solar:settings-bold'. */
  icon?: string
  /** Raw SVG child elements, used for custom icons that don't come from Iconify. */
  inner?: string
  /** Custom viewBox — defaults to '0 0 24 24'. Only used when `inner` is set. */
  viewBox?: string
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

const _ICONS = {
  // ── Core UI ──────────────────────────────────────────────────────────────

  /** Generic close / remove */
  'x': {
    inner: `<line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    viewBox: '0 0 24 24',
  },

  /** Downward-pointing chevron */
  'chevron-down': { icon: 'solar:alt-arrow-down-bold' },

  /** Upward-pointing chevron */
  'chevron-up': { icon: 'solar:alt-arrow-up-bold' },

  /** Left-pointing chevron */
  'chevron-left': { icon: 'solar:alt-arrow-left-bold' },

  /** Right-pointing chevron */
  'chevron-right': { icon: 'solar:alt-arrow-right-bold' },

  /** Checkmark (confirm, done) */
  'check': { icon: 'solar:check-read-bold' },

  /** Plus / add */
  'plus': {
    inner: `<line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    viewBox: '0 0 24 24',
  },

  /** Minus / indeterminate */
  'minus': {
    inner: `<line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    viewBox: '0 0 24 24',
  },

  /** Magnifying glass (search) */
  'search': { icon: 'solar:magnifer-bold' },

  /** Gear / settings */
  'settings': { icon: 'solar:settings-bold' },

  /** Clockwise refresh arrow */
  'refresh-cw': { icon: 'solar:refresh-bold' },

  /** Counter-clockwise refresh / undo arrow */
  'refresh-ccw': { icon: 'solar:restart-bold' },

  /** Download arrow */
  'download': { icon: 'solar:download-bold' },

  /** Left arrow (back navigation) */
  'arrow-left': { icon: 'solar:arrow-left-bold' },

  /** Hamburger / three-line menu */
  'menu': { icon: 'solar:hamburger-menu-bold' },

  // ── Editing ───────────────────────────────────────────────────────────────

  /** Pen / edit (square edit style) */
  'edit': { icon: 'solar:pen-2-bold' },

  /** Pencil */
  'pencil': { icon: 'solar:pen-bold' },

  /** Trash / delete */
  'trash': { icon: 'solar:trash-bin-trash-bold' },

  /** Pin / thumbtack */
  'pin': { icon: 'solar:pin-bold' },

  /** Copy to clipboard */
  'copy': { icon: 'solar:copy-bold' },

  /** Link / chain */
  'link': { icon: 'solar:link-bold' },

  // ── Messaging ─────────────────────────────────────────────────────────────

  /** Chat bubble */
  'message': { icon: 'solar:chat-round-bold' },

  /** Chat bubble with plus (new chat) */
  'message-plus': { icon: 'solar:pen-new-round-bold' },

  // ── Voice ─────────────────────────────────────────────────────────────────

  /** Microphone */
  'mic': { icon: 'solar:microphone-bold' },

  /** Microphone (alternate style) */
  'mic-alt': { icon: 'solar:microphone-2-bold' },

  /** Speaker / volume high */
  'volume': { icon: 'solar:volume-loud-bold' },

  /** Speaker / volume low */
  'volume-two': { icon: 'solar:volume-small-bold' },

  // ── Input actions ─────────────────────────────────────────────────────────

  /** Paper plane / send */
  'send': { icon: 'solar:plain-2-bold' },

  /** Paperclip / attach */
  'paperclip': { icon: 'solar:paperclip-bold' },

  /** Stop square (outline) */
  'stop': { icon: 'solar:stop-bold' },

  /** Stop square (filled) */
  'stop-fill': { icon: 'solar:stop-bold' },

  // ── Status / loaders ──────────────────────────────────────────────────────

  /** Spinning arc loader */
  'spinner-arc': { icon: 'solar:refresh-circle-bold' },

  /** Radiating rays loader */
  'spinner-rays': { icon: 'solar:sun-2-bold' },

  // ── Brand / AI persona ────────────────────────────────────────────────────

  /** Lightning bolt (processing) */
  'lightning': { icon: 'solar:bolt-bold' },

  /** Lightning bolt with flash (intense) */
  'lightning-flash': { icon: 'solar:bolt-circle-bold' },

  /** Abstract orb (AI idle) */
  'orb': { icon: 'solar:planet-bold' },

  /** Abstract orb filled (AI active) */
  'orb-full': { icon: 'solar:planet-bold' },

  // ── Layout / navigation ───────────────────────────────────────────────────

  /** Home / dashboard landing */
  'home': { icon: 'solar:home-smile-bold' },

  /** Split panel layout */
  'hybrid-panel': { icon: 'solar:sidebar-code-bold' },

  /** Sidebar-only layout */
  'hybrid-sidebar': { icon: 'solar:sidebar-minimalistic-bold' },

  /** Home / full-screen layout */
  'hybrid-home': { icon: 'solar:home-2-bold' },

  /** Modules / panels grid (workspace module launcher) */
  'modules': { icon: 'solar:widget-2-bold' },

  // ── Info / feedback ───────────────────────────────────────────────────────

  /** Eye / visibility */
  'eye': { icon: 'solar:eye-bold' },

  /** Lightbulb simple / idea hint */
  'lightbulb-simple': { icon: 'solar:lightbulb-minimalistic-bold' },

  /** Lightbulb / idea */
  'lightbulb': { icon: 'solar:lightbulb-bold' },

  /** Thinking cap / reasoning mode */
  'thinking-cap': { icon: 'solar:diploma-bold' },

  /** Wrench / tool result */
  'tool': { icon: 'solar:tuning-2-bold' },

  /** Clock / timestamp */
  'clock': { icon: 'solar:clock-circle-bold' },

  /** User / person */
  'user': { icon: 'solar:user-bold' },

  /** Git branch / fork */
  'branch': { icon: 'solar:branching-paths-up-bold' },

  // ── Files ─────────────────────────────────────────────────────────────────

  /** Folder */
  'folder': { icon: 'solar:folder-bold' },

  /** Generic file */
  'file': { icon: 'solar:file-bold' },

  /** File with text lines */
  'file-text': { icon: 'solar:file-text-bold' },

  /** File with multiple lines */
  'file-lines': { icon: 'solar:document-text-bold' },

  /** Draft / new document */
  'draft': { icon: 'solar:document-add-bold' },

  // ── Alerts ────────────────────────────────────────────────────────────────

  /** Alert circle / info */
  'alert-circle': { icon: 'solar:danger-circle-bold' },

  /** Alert triangle / warning */
  'alert-triangle': { icon: 'solar:danger-triangle-bold' },

  /** Circle with X / error */
  'circle-x': { icon: 'solar:close-circle-bold' },

  // ── 3D / Whiteboard ──────────────────────────────────────────────────────

  /** 3D box / model */
  'box-3d': { icon: 'solar:box-minimalistic-bold' },

  /** Wireframe / mesh */
  'wireframe': { icon: 'solar:widget-3-bold' },

  /** Crosshair / target */
  'crosshair': { icon: 'solar:target-bold' },

  /** Auto-rotate / 360 */
  'auto-rotate': { icon: 'solar:camera-rotate-bold' },

  /** Whiteboard card / sticky note */
  'whiteboard-card': { icon: 'solar:notes-bold' },

  /** Whiteboard deleted / removed card */
  'whiteboard-deleted': { icon: 'solar:trash-bin-2-bold' },

  // ── Email / communications ────────────────────────────────────────────────

  /** Envelope / mail */
  'mail': { icon: 'solar:letter-bold' },

  /** Email (alias) */
  'email': { icon: 'solar:letter-bold' },

  /** Email read / opened */
  'email-read': { icon: 'solar:letter-opened-bold' },

  /** Email unread */
  'email-unread': { icon: 'solar:letter-bold' },

  /** Inbox / tray */
  'inbox': { icon: 'solar:inbox-bold' },

  /** Archive */
  'archive': { icon: 'solar:archive-bold' },

  /** Star / favourite */
  'star': { icon: 'solar:star-bold' },

  /** Bookmark */
  'bookmark': { icon: 'solar:bookmark-bold' },

  /** Power on/off */
  'power': { icon: 'solar:power-bold' },

  // ── Calendar ──────────────────────────────────────────────────────────────

  /** Calendar / date */
  'calendar': { icon: 'solar:calendar-bold' },

  // ── Misc ──────────────────────────────────────────────────────────────────

  /** External link / open in new tab */
  'external-link': { icon: 'solar:arrow-right-up-bold' },

  /** Bar chart */
  'bar-chart': { icon: 'solar:chart-2-bold' },

  /** Magnifier zoom-in */
  'search-plus': { icon: 'solar:magnifer-zoom-in-bold' },

  /** Maximize / fit to screen */
  'maximize-fit': { icon: 'solar:maximize-square-2-bold' },

  // ── Settings / infrastructure ─────────────────────────────────────────────

  /** Package / dependency */
  'package': { icon: 'solar:box-bold' },

  /** Sliders / tuning */
  'sliders': { icon: 'solar:tuning-2-bold' },

  /** CPU */
  'cpu': { icon: 'solar:cpu-bolt-bold' },

  /** Server */
  'server': { icon: 'solar:server-square-bold' },

  /** Share / graph topology */
  'share-graph': { icon: 'solar:share-bold' },

  /** Book / documentation */
  'book': { icon: 'solar:book-2-bold' },

  /** Database */
  'database': { icon: 'solar:database-bold' },

  /** Shield / security */
  'shield': { icon: 'solar:shield-bold' },

  /** Chip / hardware */
  'chip': { icon: 'solar:cpu-bold' },

  /** Embedding / vector representation */
  'embedding': { icon: 'solar:programming-bold' },

  /** Model load / download */
  'model-load': { icon: 'solar:download-minimalistic-bold' },

  /** Model unload / upload */
  'model-unload': { icon: 'solar:upload-minimalistic-bold' },

  // ── Status indicators ─────────────────────────────────────────────────────

  /** STT activity indicator */
  'stt-indicator': { icon: 'solar:microphone-3-bold' },

  /** TTS activity indicator */
  'tts-indicator': { icon: 'solar:soundwave-bold' },

  // ── Window chrome ─────────────────────────────────────────────────────────

  /** Window minimize button — original thin horizontal stroke */
  'win-minimize': {
    inner: `<line x1="0" y1="5" x2="10" y2="5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>`,
    viewBox: '0 0 10 10',
  },

  /** Window maximize button — original square outline */
  'win-maximize': {
    inner: `<rect x="0.6" y="0.6" width="8.8" height="8.8" stroke="currentColor" stroke-width="1.2"/>`,
    viewBox: '0 0 10 10',
  },

  /** Window restore button — two overlapping squares */
  'win-restore': {
    inner: `<rect x="2" y="0" width="7.4" height="7.4" stroke="currentColor" stroke-width="1.2"/><rect x="0" y="2" width="7.4" height="7.4" fill="var(--bg-primary, #161616)" stroke="currentColor" stroke-width="1.2"/>`,
    viewBox: '0 0 10 10',
  },

  /** Window close button — original thin X */
  'win-close': {
    inner: `<line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>`,
    viewBox: '0 0 10 10',
  },
}

export type AppIconName = keyof typeof _ICONS

/**
 * Typed icon registry. Use `AppIconName` for autocomplete on icon names.
 */
export const ICONS = _ICONS as Record<AppIconName, IconDef>

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns a complete `<svg>` HTML string for use outside Vue templates.
 * Used by composables (useCodeBlocks, useMarkdown) that inject raw HTML.
 * The `strokeWidth` parameter is kept for API compatibility but is unused
 * since Solar icons are fill-based.
 */
export function getIconSvgString(
  name: AppIconName,
  size: number = 16,
  _strokeWidth?: number,
): string {
  const def = ICONS[name]
  if (def.inner != null) {
    const viewBox = def.viewBox ?? '0 0 24 24'
    return `<svg width="${size}" height="${size}" viewBox="${viewBox}" fill="none" aria-hidden="true">${def.inner}</svg>`
  }
  if (!def.icon) return ''
  const colonIdx = def.icon.indexOf(':')
  const iconName = def.icon.slice(colonIdx + 1)
  const iconData = getIconData(solarIcons, iconName)
  if (!iconData) return ''
  const svg = iconToSVG(iconData, { width: size, height: size })
  const attrs = Object.entries({ ...svg.attributes, 'aria-hidden': 'true' })
    .map(([k, v]) => `${k}="${v}"`)
    .join(' ')
  return `<svg ${attrs}>${svg.body}</svg>`
}
