import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  dismissImport, getImports, requestImport, Unauthorized, type Imports, type ImportState, type PaperOption,
} from './api'
import { longDate } from './format'

// While an import runs (~10 min), how often to ask whether it's done.
const IMPORT_POLL_MS = 10_000

const STEPS: Record<string, string> = {
  fetch: 'Herunterladen', layout: 'Seitenaufteilung', articles: 'Artikel', narration: 'Zusammenfassung',
  publish: 'Veröffentlichen',
}

const key = (i: ImportState) => `${i.paper}_${i.date}`

interface ImportFormProps {
  // An import finished: the issue list has a new issue.
  onImported: () => void
  onUnauthorized: () => void
}

/** Below the issue list, logged in only: fetching an issue costs money (layout
 * on a GPU, the narration), so it only happens when someone asks. */
export function ImportForm({ onImported, onUnauthorized }: ImportFormProps) {
  const [state, setState] = useState<Imports | null>(null)
  // Until picked: the first paper, on its default date.
  const [paper, setPaper] = useState<PaperOption | null>(null)
  const [date, setDate] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(new Set<string>())

  function handle(e: unknown) {
    if (e instanceof Unauthorized) onUnauthorized()
    else setError(String(e))
  }

  function refresh() {
    getImports().then(setState).catch(handle)
  }

  // Ask again while anything is on its way; one gone means it's published.
  useEffect(() => {
    if (!state) return refresh()
    const listed = new Set(state.imports.map(key))
    if ([...pending.current].some((k) => !listed.has(k))) onImported()
    const now = new Set(state.imports.filter((i) => i.status !== 'failed').map(key))
    pending.current = now
    if (now.size === 0) return
    const timer = setTimeout(refresh, IMPORT_POLL_MS)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])

  if (!state || state.papers.length === 0) return null
  const title = (slug: string) => state.papers.find((p) => p.slug === slug)?.title ?? slug
  const selected = paper ?? state.papers[0]
  const selectedDate = date ?? selected.default_date

  function pick(slug: string) {
    setPaper(state?.papers.find((p) => p.slug === slug) ?? null)
    setDate(null)
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    requestImport(selected.slug, selectedDate).then(refresh).catch(handle)
  }

  function dismiss(i: ImportState) {
    dismissImport(i.paper, i.date).then(refresh).catch(handle)
  }

  return (
    <section className="imports">
      <h2>Ausgabe holen</h2>
      <p className="sub">Lädt die Ausgabe herunter und bereitet sie auf, das dauert etwa zehn Minuten.</p>
      <form onSubmit={submit}>
        <label>
          Zeitung
          <select value={selected.slug} onChange={(e) => pick(e.target.value)}>
            {state.papers.map((p) => <option key={p.slug} value={p.slug}>{p.title}</option>)}
          </select>
        </label>
        <label>
          Datum
          <input type="date" required value={selectedDate} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button type="submit" disabled={!selectedDate}>Holen</button>
      </form>
      {error && <p className="error">{error}</p>}
      {state.imports.length > 0 && (
        <ul>
          {state.imports.map((i) => (
            <li key={key(i)}>
              <span><strong>{title(i.paper)}</strong>, {longDate(i.date)}</span>
              {i.status === 'requested' && <span className="muted">wartet auf den Start …</span>}
              {i.status === 'running' && (
                <span className="muted">läuft{i.step ? `: ${STEPS[i.step] ?? i.step}` : ''} …</span>
              )}
              {i.status === 'failed' && (
                <>
                  <span className="error">fehlgeschlagen: {i.error}</span>
                  <span className="actions">
                    <button onClick={() => requestImport(i.paper, i.date).then(refresh).catch(handle)}>Nochmal</button>
                    <button className="quiet" onClick={() => dismiss(i)}>Verwerfen</button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
