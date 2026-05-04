/**
 * TldrawApp — React component that wraps the tldraw editor.
 *
 * This is a "React island" rendered inside Vue via createRoot.
 * It receives the initial snapshot and a save callback,
 * and notifies the host whenever the document changes.
 */
import React, { useCallback, useEffect, useRef } from 'react'
import { Tldraw, type Editor, type TLStoreSnapshot } from 'tldraw'
import 'tldraw/tldraw.css'

export interface TldrawAppProps {
  /** Initial snapshot to load into the editor. Empty object = blank canvas. */
  snapshot?: TLStoreSnapshot | null
  /** Called when the document changes (debounced by the parent Vue wrapper). */
  onDocumentChange?: (snapshot: TLStoreSnapshot) => void
}

type LegacyShapeProps = Record<string, unknown> & {
  align?: string
  fontSizeAdjustment?: number
  labelColor?: string
  scale?: number
  textAlign?: string
}

/**
 * Debounce helper — fires callback after `delay` ms of inactivity.
 */
function useDebouncedCallback<A extends unknown[]>(
  callback: (...args: A) => void,
  delay: number
): (...args: A) => void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latestCb = useRef(callback)
  latestCb.current = callback

  return useCallback(
    (...args: A) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => latestCb.current(...args), delay)
    },
    [delay]
  )
}

export default function TldrawApp({
  snapshot,
  onDocumentChange
}: TldrawAppProps): React.JSX.Element {
  const editorRef = useRef<Editor | null>(null)

  const debouncedSave = useDebouncedCallback(
    (snap: TLStoreSnapshot) => onDocumentChange?.(snap),
    1500
  )

  const handleMount = useCallback(
    (editor: Editor) => {
      editorRef.current = editor

      /* Listen for store changes → debounced save */
      editor.store.listen(
        () => {
          const snap = editor.store.getStoreSnapshot()
          debouncedSave(snap as unknown as TLStoreSnapshot)
        },
        { scope: 'document', source: 'user' }
      )
    },
    [debouncedSave]
  )

  /* Cleanup on unmount */
  useEffect(() => {
    return () => {
      editorRef.current = null
    }
  }, [])

  /* Patch old snapshots missing required fields (e.g. gridSize on document) */
  const initialSnapshot = React.useMemo(() => {
    if (!snapshot || Object.keys(snapshot).length === 0) return undefined
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const patched = JSON.parse(JSON.stringify(snapshot)) as any
    const store = patched.store as Record<string, Record<string, unknown>> | undefined
    if (store?.['document:document'] && store['document:document'].gridSize == null) {
      store['document:document'].gridSize = 10
    }
    // Patch shapes missing required props (tldraw v3.15+)
    if (store) {
      for (const record of Object.values(store)) {
        if (record.typeName === 'shape' && record.props) {
          const props = record.props as LegacyShapeProps
          if (props.scale == null) props.scale = 1
          // text shapes: 'align' was renamed to 'textAlign'
          if (record.type === 'text' && props.textAlign == null) {
            props.textAlign = props.align ?? 'start'
          }
          // note shapes: fontSizeAdjustment + labelColor required since tldraw v3.9
          if (record.type === 'note') {
            if (props.fontSizeAdjustment == null) props.fontSizeAdjustment = 0
            if (props.labelColor == null) props.labelColor = 'black'
          }
        }
      }
    }
    return patched as unknown as TLStoreSnapshot
  }, [snapshot])

  return (
    <div className="alice-tldraw-wrapper" style={{ width: '100%', height: '100%' }}>
      <Tldraw
        snapshot={initialSnapshot}
        onMount={handleMount}
        inferDarkMode
        options={{ maxPages: 1 }}
      />
    </div>
  )
}
