import { getIconSvgString } from '../assets/icons'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'

import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import java from 'highlight.js/lib/languages/java'
import csharp from 'highlight.js/lib/languages/csharp'
import cpp from 'highlight.js/lib/languages/cpp'
import c from 'highlight.js/lib/languages/c'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import ruby from 'highlight.js/lib/languages/ruby'
import php from 'highlight.js/lib/languages/php'
import swift from 'highlight.js/lib/languages/swift'
import kotlin from 'highlight.js/lib/languages/kotlin'
import sql from 'highlight.js/lib/languages/sql'
import htmlLang from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import scss from 'highlight.js/lib/languages/scss'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import bash from 'highlight.js/lib/languages/bash'
import shell from 'highlight.js/lib/languages/shell'
import powershell from 'highlight.js/lib/languages/powershell'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('java', java)
hljs.registerLanguage('csharp', csharp)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('c', c)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('ruby', ruby)
hljs.registerLanguage('php', php)
hljs.registerLanguage('swift', swift)
hljs.registerLanguage('kotlin', kotlin)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('html', htmlLang)
hljs.registerLanguage('xml', htmlLang)
hljs.registerLanguage('css', css)
hljs.registerLanguage('scss', scss)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', shell)
hljs.registerLanguage('powershell', powershell)
hljs.registerLanguage('dockerfile', dockerfile)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('plaintext', plaintext)

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function encodeBase64(str: string): string {
  return btoa(unescape(encodeURIComponent(str)))
}

function capitalizeFirst(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/**
 * Wikilink plugin — transforms [[Target]] and [[Target|display]]
 * into <a class="wikilink" data-target="Target">display</a>.
 */
function wikilinkPlugin(mdi: MarkdownIt): void {
  mdi.inline.ruler.push('wikilink', (state, silent) => {
    const src = state.src.slice(state.pos)
    if (!src.startsWith('[[')) return false

    const closeIdx = src.indexOf(']]')
    if (closeIdx < 0) return false

    const inner = src.slice(2, closeIdx)
    if (!inner) return false

    if (!silent) {
      const pipeIdx = inner.indexOf('|')
      const target = (pipeIdx >= 0 ? inner.slice(0, pipeIdx) : inner).trim()
      const display = (pipeIdx >= 0 ? inner.slice(pipeIdx + 1) : inner).trim()

      const tokenOpen = state.push('html_inline', '', 0)
      tokenOpen.content = `<a class="wikilink" data-target="${escapeHtml(target)}">`

      const tokenText = state.push('html_inline', '', 0)
      tokenText.content = escapeHtml(display)

      const tokenClose = state.push('html_inline', '', 0)
      tokenClose.content = '</a>'
    }

    state.pos += closeIdx + 2
    return true
  })
}

const copySvg = getIconSvgString('copy', 16)

/** Module-level singleton — avoids re-creating on every composable call. */
const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight(str: string, lang: string): string {
    let highlighted: string
    const normalizedLang = lang ? lang.toLowerCase().trim() : ''

    if (normalizedLang && hljs.getLanguage(normalizedLang)) {
      highlighted = hljs.highlight(str, { language: normalizedLang }).value
    } else {
      const auto = hljs.highlightAuto(str)
      if (auto.relevance > 0 && auto.language) {
        highlighted = auto.value
      } else {
        highlighted = escapeHtml(str)
      }
    }

    const langLabel = normalizedLang ? escapeHtml(capitalizeFirst(normalizedLang)) : 'Codice'
    const langClass = (normalizedLang || 'plaintext').replace(/[^a-zA-Z0-9_-]/g, '')
    const dataCode = encodeBase64(str)

    return (
      `<div class="code-block-wrapper">` +
      `<div class="code-block-header">` +
      `<span class="code-block-lang">${langLabel}</span>` +
      `<button class="code-block-copy" data-code="${dataCode}" title="Copia codice">` +
      copySvg +
      `<span class="code-block-copy__label">Copia</span>` +
      `</button>` +
      `</div>` +
      `<pre class="code-block"><code class="hljs language-${langClass}">${highlighted}</code></pre>` +
      `</div>`
    )
  }
})

md.use(wikilinkPlugin)

export function renderMarkdown(raw: string): string {
  if (!raw) return ''
  return md.render(raw)
}
