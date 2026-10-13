import { Masthead } from './Masthead'
import { IMPRINT_HASH, LOGIN_HASH, routeHash } from './route'

const OPERATOR = ['Chris Sachs', 'Alt-Stralau 6A', '10245 Berlin']
const WEBSITE_URL = 'https://chris-sachs.info/'

/** The imprint, reachable without logging in. */
export function Imprint() {
  return (
    <div className="app">
      <main className="scroll">
        <Masthead />
        <article className="imprint">
          <a className="back-link" href={routeHash(null)}>Zur Startseite</a>
          <p className="kicker">Impressum</p>
          <h2>Eine Demo, keine Zeitung</h2>
          <p>
            Der Allgemeine Hörbote ist eine private Demo-Seite: ein Versuch, Zeitungsausgaben automatisch vorlesen zu
            lassen. Kein Verlag und kein kommerzielles Angebot.
          </p>
          <p>
            Texterkennung, Zusammenfassung und Stimme sind automatisch erzeugt. Fehler sind möglich, maßgeblich ist das
            Original. Quelle und Rechte stehen bei jeder Ausgabe in der Seitenübersicht.
          </p>
          <h3>Angaben gemäß § 5 DDG</h3>
          <address>{OPERATOR.map((line) => <span key={line}>{line}</span>)}</address>
          <h3>Kontakt</h3>
          <p><a href={WEBSITE_URL}>chris-sachs.info</a></p>
        </article>
      </main>
    </div>
  )
}

interface SiteLinksProps {
  // Omitted on the login page itself.
  loggedIn?: boolean
  onLogout?: () => void
}

/** The links at the foot of the landing and login pages. Logging in is
 * tucked away here: it only unlocks the issues that can't be shown
 * publicly. */
export function SiteLinks({ loggedIn, onLogout }: SiteLinksProps) {
  return (
    <nav className="site-links" aria-label="Rechtliches">
      <a href={IMPRINT_HASH}>Impressum</a>
      {loggedIn === false && <a href={LOGIN_HASH}>Anmelden</a>}
      {loggedIn && <button onClick={onLogout}>Abmelden</button>}
    </nav>
  )
}
