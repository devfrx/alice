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

    const langLabel = normalizedLang ? capitalizeFirst(normalizedLang) : 'Codice'
    const langClass = (normalizedLang || 'plaintext').replace(/[^a-zA-Z0-9_-]/g, '')
    const dataCode = encodeBase64(str)

    return `<div class="code-block-wrapper">` +
      `<div class="code-block-header">` +
        `<span class="code-block-lang">${langLabel}</span>` +
        `<button class="code-block-copy" data-code="${dataCode}" title="Copia codice">` +
          `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>` +
          `<span class="code-block-copy__label">Copia</span>` +
        `</button>` +
      `</div>` +
      `<pre class="code-block"><code class="hljs language-${langClass}">${highlighted}</code></pre>` +
    `</div>`
  }
})

export function renderMarkdown(raw: string): string {
  if (!raw) return ''
  return md.render(raw)
}
