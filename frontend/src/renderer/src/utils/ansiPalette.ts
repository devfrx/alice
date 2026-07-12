/**
 * ansiPalette — Shared 16-color ANSI palette for xterm.js terminal
 * instances (TerminalPageView, TerminalModule).
 *
 * This mirrors xterm.js's own built-in default ANSI colors (the "Tango"
 * palette: `DEFAULT_ANSI_COLORS` in `@xterm/xterm`), which is what both
 * terminal consumers have always rendered — neither previously set an
 * explicit `theme.black/red/green/...`, so xterm fell back to these values
 * implicitly. It is extracted here as an explicit, documented constant so
 * the two consumers share one definition and so it survives becoming part
 * of a runtime-built theme object (see useThemeTokens) without changing a
 * single rendered pixel.
 *
 * A categorical ANSI palette legitimately does not map 1:1 onto the AL\CE
 * UI design tokens (there is no `--ansi-*` token family, per the UI/UX
 * rework plan) — it stays a local constant rather than becoming tokens.
 */
export const ANSI_PALETTE = {
  black: '#2e3436',
  red: '#cc0000',
  green: '#4e9a06',
  yellow: '#c4a000',
  blue: '#3465a4',
  magenta: '#75507b',
  cyan: '#06989a',
  white: '#d3d7cf',
  brightBlack: '#555753',
  brightRed: '#ef2929',
  brightGreen: '#8ae234',
  brightYellow: '#fce94f',
  brightBlue: '#729fcf',
  brightMagenta: '#ad7fa8',
  brightCyan: '#34e2e2',
  brightWhite: '#eeeeec'
} as const
