// Types mirror shared/published.py (the publish job's JSON, served as-is by the
// backend minus the backend-only image path).

export type BBox = [x0: number, y0: number, x1: number, y1: number]

export interface Article {
  article_idx: number
  headline: string
  category: string | null
  // Fractions of the page (0-1).
  bbox: BBox
  // Segment indices about this article, in play order; empty = not narrated.
  segments: number[]
}

export interface Segment {
  index: number
  article_idx: number
  sentences: string[]
}

export interface Page {
  page: number
  aspect_ratio: number
  tone: string | null
  articles: Article[]
  segments: Segment[]
}

export interface IssuePage {
  page: number
  aspect_ratio: number
  segment_count: number
}

/** One line of the issue list. */
export interface IssueSummary {
  run_id: string
  paper: string
  paper_title: string
  edition: string
  date: string // YYYY-MM-DD
}

export interface Issue extends IssueSummary {
  attribution: string
  pages: IssuePage[]
}

/** Whether the issue's audio is there (backend/audio_state.py). */
export interface AudioState {
  status: 'none' | 'requested' | 'rendering' | 'ready' | 'failed'
  rendered: number
  total: number
}

/** An issue import asked for and not done yet (backend/import_state.py).
 * A done one is gone from the list: its issue is published. */
export interface ImportState {
  paper: string
  date: string // YYYY-MM-DD
  status: 'requested' | 'running' | 'failed'
  run_id: string | null
  step: string | null // while running: the job at work
  error: string | null
}

/** A paper in the import form (config/papers.toml). */
export interface PaperOption {
  slug: string
  title: string
  default_date: string // YYYY-MM-DD, e.g. 100 years ago today
}

export interface Imports {
  papers: PaperOption[]
  imports: ImportState[]
}

/** Thrown on a 401: the session ran out (or the password changed). */
export class Unauthorized extends Error {}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (r.status === 401) throw new Unauthorized()
  if (!r.ok) throw new Error(`${url}: ${r.status}`)
  return r.json()
}

export const getSession = () => getJson<{ logged_in: boolean }>('/api/session')
/** Without a login: the openly licensed issues only. */
export const listIssues = () => getJson<IssueSummary[]>('/api/issues')
export const getIssue = (runId: string) => getJson<Issue>(`/api/issues/${runId}`)
export const getPage = (runId: string, page: number) => getJson<Page>(`/api/issues/${runId}/pages/${page}`)

export const imageUrl = (runId: string, page: number) => `/api/issues/${runId}/pages/${page}/image`
export const thumbnailUrl = (runId: string, page: number) => `/api/issues/${runId}/pages/${page}/thumbnail`
export const audioUrl = (runId: string, page: number, segment: number) =>
  `/api/issues/${runId}/pages/${page}/segments/${segment}/audio`

export const getAudioState = (runId: string) => getJson<AudioState>(`/api/issues/${runId}/audio`)

/** Asks for the issue's audio (logged in only); ~3 min until it's ready. */
export async function requestAudio(runId: string): Promise<AudioState> {
  const r = await fetch(`/api/issues/${runId}/audio`, { method: 'POST' })
  if (r.status === 401) throw new Unauthorized()
  if (!r.ok) throw new Error(`requestAudio: ${r.status}`)
  return r.json()
}

/** Logged in only, like everything about imports. */
export const getImports = () => getJson<Imports>('/api/imports')

/** Asks for an issue; ~10 min until it's in the list. */
export async function requestImport(paper: string, date: string): Promise<ImportState> {
  const r = await fetch('/api/imports', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper, date }),
  })
  if (r.status === 401) throw new Unauthorized()
  if (!r.ok) throw new Error(`requestImport: ${r.status}`)
  return r.json()
}

/** Forgets a failed import. */
export async function dismissImport(paper: string, date: string): Promise<void> {
  const r = await fetch(`/api/imports/${encodeURIComponent(paper)}/${date}`, { method: 'DELETE' })
  if (r.status === 401) throw new Unauthorized()
  if (!r.ok) throw new Error(`dismissImport: ${r.status}`)
}

export async function logout(): Promise<void> {
  await fetch('/api/logout', { method: 'POST' })
}

/** Returns false on a wrong password. */
export async function login(password: string): Promise<boolean> {
  const r = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
  if (r.status === 401) return false
  if (!r.ok) throw new Error(`login: ${r.status}`)
  return true
}
