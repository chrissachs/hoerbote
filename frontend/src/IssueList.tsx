import { useRef } from 'react'
import { thumbnailUrl, type IssueSummary } from './api'
import { issueDateLines, issueEdition } from './format'
import { routeHash } from './route'

/** Start screen below the masthead: an opener filling the first screen
 * (headline, and how it works as a small article next to it), then every
 * published issue as a card with its front page,
 * grouped by paper, latest first (the backend's order). */
export function IssueList({ issues }: { issues: IssueSummary[] }) {
  const listRef = useRef<HTMLDivElement>(null)
  const papers = new Map<string, IssueSummary[]>()
  for (const issue of issues) {
    const title = issue.paper_title
    papers.set(title, [...(papers.get(title) ?? []), issue])
  }

  return (
    <>
      <section className="hero">
        <div className="hero-head">
          <h2>Zeitung <em>hören.</em></h2>
          {/* A button, not an #anchor: the hash holds the route. */}
          <button className="cue" onClick={() => listRef.current?.scrollIntoView({ behavior: 'smooth' })}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="M3 6l5 5 5-5" />
            </svg>
            Ausgabe wählen
          </button>
        </div>

        {/* How it works, set like a short newspaper article. */}
        <article className="notice">
          <p className="kicker">In eigener Sache</p>
          <h3>So funktioniert der Hörbote</h3>
          <p className="standfirst">
            Zeitungsausgaben, Artikel für Artikel vorgelesen und Seite für Seite zusammengefasst. Während du zuhörst,
            zeigt die Seite, wo der Artikel steht.
          </p>
          <ol>
            <li><strong>Ausgabe wählen.</strong> Eine der Ausgaben weiter unten antippen, die Erzählung beginnt auf der
              ersten Seite.</li>
            <li><strong>Zuhören.</strong> Die Erzählung springt von Artikel zu Artikel und von Seite zu Seite, bis die
              Ausgabe zu Ende ist.</li>
            <li><strong>Mitlesen.</strong> Die Seite zoomt zum vorgelesenen Artikel. Ein Klick auf einen anderen
              Artikel spielt diesen.</li>
          </ol>
          <p className="editors-note">
            Anm. d. Red.: Texterkennung, Zusammenfassung und Stimme sind automatisch erzeugt. Fehler sind möglich,
            maßgeblich ist das Original. Quelle und Rechte stehen bei jeder Ausgabe in der Seitenübersicht.
          </p>
        </article>
      </section>

      <div className="landing" ref={listRef}>

        {issues.length === 0 && <p className="empty">Noch keine Ausgabe veröffentlicht.</p>}
        {[...papers].map(([title, list]) => (
          <section key={title} className="paper">
            <h2>{title}</h2>
            <p className="sub">{list.length === 1 ? '1 Ausgabe' : `${list.length} Ausgaben`}</p>
            <ul className="issue-cards">
              {list.map((issue) => (
                <li key={issue.run_id}>
                  <a href={routeHash(issue.run_id)}>
                    <div className="stack">
                      <img src={thumbnailUrl(issue.run_id, 1)} alt="" loading="lazy"
                           onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                    </div>
                    <span className="date">{issueDateLines(issue)[0]}</span>
                    <span className="muted small">
                      {[issueDateLines(issue)[1], issueEdition(issue)].filter(Boolean).join(' · ')}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  )
}
