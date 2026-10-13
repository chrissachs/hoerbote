// The app's place in the URL fragment: `#/` is the issue list,
// `#/<run_id>/<page>` a page of an issue, `#/impressum` the imprint and
// `#/anmelden` the login (no run_id looks like those: they end in a
// date). A reload or a shared link lands in the same place.

export const IMPRINT = 'impressum'
export const IMPRINT_HASH = `#/${IMPRINT}`
export const LOGIN = 'anmelden'
export const LOGIN_HASH = `#/${LOGIN}`

export interface Route {
  runId: string | null
  page: number | null
}

export function parseRoute(hash: string): Route {
  const [runId, page] = hash.replace(/^#\/?/, '').split('/')
  return { runId: runId || null, page: page ? Number(page) || null : null }
}

export function routeHash(runId: string | null, page?: number | null): string {
  if (!runId) return '#/'
  return page ? `#/${runId}/${page}` : `#/${runId}`
}
