import { routeHash } from './route'

export const NAME = 'Der Allgemeine Hörbote'
export const SHORT_NAME = 'Hörbote'
export const TAGLINE = 'Für Leser, die lieber zuhören'
// The masthead's date line; the day the page was loaded is close enough.
const TODAY = new Date().toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

/** The full newspaper-style masthead (landing page, login): today's date
 * and an optional note above the wordmark, the tagline below it. */
export function Masthead({ note }: { note?: string }) {
  return (
    <header className="masthead">
      <div className="dateline"><span>{TODAY}</span>{note && <span>{note}</span>}</div>
      <h1 className="wordmark">{NAME}</h1>
      <div className="tagline">{TAGLINE}</div>
    </header>
  )
}

/** The wordmark for the reader's slim bar, linking back to the start;
 * phones get the short name. */
export function BarWordmark() {
  return (
    <a className="wordmark" href={routeHash(null)} aria-label={`${NAME} – alle Ausgaben`}>
      <span className="long">{NAME}</span><span className="short">{SHORT_NAME}</span>
    </a>
  )
}
