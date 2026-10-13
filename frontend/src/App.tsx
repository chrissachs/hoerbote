import { useEffect, useRef, useState } from 'react'
import {
  audioUrl, getAudioState, getIssue, getPage, getSession, imageUrl, listIssues, login, logout, requestAudio,
  thumbnailUrl, Unauthorized, type AudioState, type Issue, type IssueSummary, type Page,
} from './api'
import { issueDate, issueDateLines, issueEdition } from './format'
import { Back, NextPage, NextSegment, Pages, Pause, Play, PreviousPage, PreviousSegment } from './icons'
import { ImportForm } from './ImportForm'
import { Imprint, SiteLinks } from './Imprint'
import { IssueList } from './IssueList'
import { Login } from './Login'
import { BarWordmark, Masthead, NAME, SHORT_NAME } from './Masthead'
import { PageList } from './PageList'
import { PageView } from './PageView'
import { nextPosition, previousPosition, type Position } from './playback'
import { IMPRINT, LOGIN, parseRoute, routeHash, type Route } from './route'

// While the audio job runs (~3 min), how often to ask whether it's done.
const AUDIO_POLL_MS = 10_000

/** `#key=<password>` share links: the fragment never reaches a server.
 * Strip it from the address bar first, then log in with it. */
async function loginFromFragment(): Promise<void> {
  const key = new URLSearchParams(location.hash.slice(1)).get('key')
  if (!key) return
  history.replaceState(null, '', location.pathname + location.search)
  await login(key)
}

export default function App() {
  // null while the session check runs.
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null)
  const [issues, setIssues] = useState<IssueSummary[] | null>(null)
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash))

  useEffect(() => {
    const onHash = () => setRoute(parseRoute(location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    loginFromFragment()
      .then(getSession)
      .then((s) => setLoggedIn(s.logged_in))
      .catch(console.error)
  }, [])

  // The issue list depends on the login: without one, open issues only.
  useEffect(() => {
    if (loggedIn === null) return
    listIssues().then(setIssues).catch(console.error)
  }, [loggedIn])

  function onLogout() {
    logout().then(() => setLoggedIn(false)).catch(console.error)
  }

  // Public, like the login page.
  if (route.runId === IMPRINT) return <Imprint />
  if (route.runId === LOGIN) {
    return <Login onSuccess={() => { setLoggedIn(true); location.hash = routeHash(null) }} />
  }
  // While the list loads, the masthead already stands.
  if (loggedIn === null || issues === null) {
    return <div className="app"><main className="scroll"><Masthead /></main></div>
  }
  const summary = issues.find((i) => i.run_id === route.runId)
  if (!route.runId || !summary) {
    return (
      <div className="app">
        <main className="scroll">
          <Masthead note={issues.length === 1 ? '1 Ausgabe' : `${issues.length} Ausgaben`} />
          <IssueList issues={issues} />
          {loggedIn && (
            <ImportForm onUnauthorized={() => setLoggedIn(false)}
                        onImported={() => listIssues().then(setIssues).catch(console.error)} />
          )}
          <SiteLinks loggedIn={loggedIn} onLogout={onLogout} />
        </main>
      </div>
    )
  }
  return (
    <Reader key={route.runId} summary={summary} initialPage={route.page} loggedIn={loggedIn}
            onUnauthorized={() => setLoggedIn(false)} />
  )
}

interface ReaderProps {
  summary: IssueSummary
  initialPage: number | null
  loggedIn: boolean
  onUnauthorized: () => void
}

/** One issue: page view, narration text and playback controls. */
function Reader({ summary, initialPage, loggedIn, onUnauthorized }: ReaderProps) {
  const runId = summary.run_id
  const [issue, setIssue] = useState<Issue | null>(null)
  const [pos, setPos] = useState<Position | null>(null)
  const [page, setPage] = useState<Page | null>(null)
  // What the user wants -- the <audio> element is made to follow it.
  const [playing, setPlaying] = useState(false)
  const [loadingAudio, setLoadingAudio] = useState(false)
  // How far the current segment has played, 0-1.
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [showPages, setShowPages] = useState(false)
  const [audioState, setAudioState] = useState<AudioState | null>(null)

  const audioRef = useRef<HTMLAudioElement>(null)
  const srcRef = useRef<string | null>(null)
  const pageCache = useRef(new Map<string, Page>())
  const preloaded = useRef(new Set<string>())

  function handle(e: unknown) {
    if (e instanceof Unauthorized) onUnauthorized()
    else setError(String(e))
  }

  // Issue index; start at the page from the URL, else the first.
  useEffect(() => {
    getIssue(runId)
      .then((i) => {
        setIssue(i)
        const start = i.pages.find((p) => p.page === initialPage) ?? i.pages[0]
        if (start) setPos({ page: start.page, segment: 0 })
      })
      .catch(handle)
    // Only once per issue (the Reader is keyed by it): initialPage changing
    // later is our own URL update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  // A page changed in the URL by hand (or via back/forward). Our own URL
  // updates below use replaceState, which fires no hashchange, so this
  // only reacts to outside changes.
  useEffect(() => {
    if (!issue || initialPage === null) return
    if (issue.pages.some((p) => p.page === initialPage)) setPos({ page: initialPage, segment: 0 })
  }, [issue, initialPage])

  // Whether there's audio; while it's being rendered, ask again until it
  // is (or the job fails).
  useEffect(() => {
    const status = audioState?.status
    if (status !== undefined && status !== 'requested' && status !== 'rendering') return
    const timer = setTimeout(
      () => getAudioState(runId).then(setAudioState).catch(handle),
      status === undefined ? 0 : AUDIO_POLL_MS,
    )
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, audioState])

  function prepareAudio() {
    requestAudio(runId).then(setAudioState).catch(handle)
  }

  // Tab title: which issue this is.
  useEffect(() => {
    document.title = `${summary.paper_title}, ${issueDateLines(summary)[0]} – ${SHORT_NAME}`
    return () => { document.title = NAME }
  }, [summary])

  // The URL follows the page, without a history entry per page turn.
  const currentPage = pos?.page
  useEffect(() => {
    if (currentPage !== undefined) history.replaceState(null, '', routeHash(runId, currentPage))
  }, [runId, currentPage])

  // The current page's JSON.
  useEffect(() => {
    if (currentPage === undefined) return
    const key = `${runId}/${currentPage}`
    let stale = false
    const cached = pageCache.current.get(key)
    ;(cached ? Promise.resolve(cached) : getPage(runId, currentPage))
      .then((p) => {
        pageCache.current.set(key, p)
        if (!stale) setPage(p)
      })
      .catch(handle)
    return () => { stale = true }
  }, [runId, currentPage])

  const audioReady = audioState?.status === 'ready'
  const pageReady = page !== null && pos !== null && page.page === pos.page
  const segment = pageReady ? page.segments[pos.segment] : undefined
  const article = segment && page?.articles.find((a) => a.article_idx === segment.article_idx)

  // Point <audio> at the current segment and make it follow `playing`.
  // preload="none": browsing pages while paused doesn't trigger renders.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !pos || !pageReady) return
    // Nothing narrated on this page, or no audio yet; onPause syncs `playing`.
    if (!segment || !audioReady) return audio.pause()
    const url = audioUrl(runId, pos.page, pos.segment)
    if (srcRef.current !== url) {
      srcRef.current = url
      audio.src = url
      setProgress(0)
    }
    if (playing && audio.paused) {
      setError(null)
      audio.play().catch((e: DOMException) => {
        // AbortError: src changed mid-start, the next play() takes over.
        if (e.name !== 'AbortError') setPlaying(false)
      })
    } else if (!playing && !audio.paused) {
      audio.pause()
    }
  }, [runId, pos, pageReady, segment, audioReady, playing])

  // While a segment plays, load the next one into the browser cache, so
  // the switch has no gap.
  function preloadNext() {
    const next = issue && pos && nextPosition(issue, pos)
    if (!next) return
    const url = audioUrl(runId, next.page, next.segment)
    if (preloaded.current.has(url)) return
    preloaded.current.add(url)
    fetch(url).catch(() => preloaded.current.delete(url))
  }

  function step(to: Position | null) {
    if (to) setPos(to)
    else setPlaying(false)
  }

  function goToPage(n: number) {
    setPos({ page: n, segment: 0 })
    setShowPages(false)
  }

  function playArticle(articleIdx: number) {
    const a = page?.articles.find((x) => x.article_idx === articleIdx)
    if (!pos || !a?.segments.length) return
    setPos({ page: pos.page, segment: a.segments[0] })
    setPlaying(true)
  }

  // Lock screen / headphone controls. Handlers read the latest closures
  // via a ref, so they're registered once.
  const controls = useRef({ play: () => {}, pause: () => {}, next: () => {}, previous: () => {} })
  useEffect(() => {
    controls.current = {
      play: () => setPlaying(true),
      pause: () => setPlaying(false),
      next: () => issue && pos && step(nextPosition(issue, pos)),
      previous: () => issue && pos && step(previousPosition(issue, pos)),
    }
  })
  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    navigator.mediaSession.setActionHandler('play', () => controls.current.play())
    navigator.mediaSession.setActionHandler('pause', () => controls.current.pause())
    navigator.mediaSession.setActionHandler('nexttrack', () => controls.current.next())
    navigator.mediaSession.setActionHandler('previoustrack', () => controls.current.previous())
  }, [])
  useEffect(() => {
    if (!('mediaSession' in navigator) || !article || !pos) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: article.headline, artist: `Seite ${pos.page}`, album: `${summary.paper_title}, ${issueDate(summary)}`,
    })
  }, [article, pos, summary])

  const pageIndex = issue && pos ? issue.pages.findIndex((p) => p.page === pos.page) : -1
  const issuePage = issue?.pages[pageIndex]
  // "Beitrag 2 von 5": the narrated articles of the page, in play order.
  const narrated = pageReady ? page.articles.filter((a) => a.segments.length > 0) : []
  narrated.sort((a, b) => a.segments[0] - b.segments[0])
  const articleNumber = article ? narrated.indexOf(article) + 1 : 0

  return (
    <div className="app">
      <header className="bar">
        <div className="bar-side">
          <a className="icon-button" href={routeHash(null)} aria-label="Alle Ausgaben"><Back /></a>
          <div className="title">
            <span className="paper">{summary.paper_title}</span>
            <span className="muted">{issueDate(summary)}{issueEdition(summary) ? `, ${issueEdition(summary)}` : ''}</span>
          </div>
        </div>
        <BarWordmark />
        <div className="bar-side right">
          {issue && pos && (
            <>
              <span className="page-count">Seite {pos.page} / {issue.pages.length}</span>
              <button className="pages-button" onClick={() => setShowPages(true)} aria-label="Seitenübersicht">
                <Pages /> {pos.page} / {issue.pages.length}
              </button>
            </>
          )}
        </div>
      </header>

      <div className="reader-body">
        {issue && pos && (
          <aside className="sidebar"><PageList issue={issue} current={pos.page} onSelect={goToPage} /></aside>
        )}
        <main>
          {pos && (
            pageReady ? (
              <PageView page={page} imageSrc={imageUrl(runId, pos.page)} thumbnailSrc={thumbnailUrl(runId, pos.page)}
                        activeArticle={segment?.article_idx ?? null} onArticleClick={playArticle} />
            ) : (
              <div className="page-view placeholder" style={{ aspectRatio: issuePage?.aspect_ratio ?? 0.7 }} />
            )
          )}
        </main>
      </div>

      {showPages && issue && pos && (
        <div className="pages-overlay">
          <div className="pages-overlay-header">
            <span>Seiten</span>
            <button className="icon-button" onClick={() => setShowPages(false)} aria-label="Schließen">✕</button>
          </div>
          <PageList issue={issue} current={pos.page} onSelect={goToPage} />
        </div>
      )}

      <footer>
        <div className="progress" aria-hidden="true"><span style={{ width: `${progress * 100}%` }} /></div>
        <div className="caption">
          {error && <p className="error">{error}</p>}
          {audioState && !audioReady && <AudioNotice state={audioState} loggedIn={loggedIn} onPrepare={prepareAudio} />}
          {pageReady && !segment && <p className="muted">Auf dieser Seite gibt es nichts zu hören.</p>}
          {article && pos && (
            <p className="kicker">Seite {pos.page} · Beitrag {articleNumber} von {narrated.length}</p>
          )}
          {article && <p className="headline">{article.headline}</p>}
          {segment && <p className="text">{segment.sentences.join(' ')}</p>}
        </div>
        <div className="controls">
          <button className="page-step" onClick={() => issue && goToPage(issue.pages[pageIndex - 1].page)}
                  disabled={pageIndex <= 0} aria-label="Vorige Seite"><PreviousPage /></button>
          <button onClick={() => issue && pos && step(previousPosition(issue, pos))}
                  disabled={!issue || !pos || !previousPosition(issue, pos)} aria-label="Voriger Beitrag"><PreviousSegment /></button>
          <button className="play" onClick={() => setPlaying(!playing)} disabled={!segment || !audioReady}
                  aria-label={playing ? 'Pause' : 'Abspielen'}>
            {playing ? <Pause /> : <Play />}
            {playing && loadingAudio && <LoadingRing />}
          </button>
          <button onClick={() => issue && pos && step(nextPosition(issue, pos))}
                  disabled={!issue || !pos || !nextPosition(issue, pos)} aria-label="Nächster Beitrag"><NextSegment /></button>
          <button className="page-step" onClick={() => issue && goToPage(issue.pages[pageIndex + 1].page)}
                  disabled={!issue || pageIndex >= issue.pages.length - 1} aria-label="Nächste Seite"><NextPage /></button>
        </div>
      </footer>

      <audio
        ref={audioRef}
        preload="none"
        onLoadStart={() => setLoadingAudio(true)}
        onWaiting={() => setLoadingAudio(true)}
        onTimeUpdate={(e) => {
          const { currentTime, duration } = e.currentTarget
          if (duration) setProgress(currentTime / duration)
        }}
        onPlaying={() => {
          setLoadingAudio(false)
          preloadNext()
        }}
        // Keep `playing` in sync when the browser/OS pauses or resumes on
        // its own (headphones unplugged, lock screen). A finished segment
        // also fires "pause" -- with .ended set, so it's ignored here.
        onPause={(e) => { if (!e.currentTarget.ended) setPlaying(false) }}
        onPlay={() => setPlaying(true)}
        onEnded={() => issue && pos && step(nextPosition(issue, pos))}
        onError={() => {
          if (!srcRef.current) return
          setLoadingAudio(false)
          setPlaying(false)
          srcRef.current = null
          setError('Audio konnte nicht geladen werden.')
          // Maybe the audio went stale (narration re-run) -- check.
          getAudioState(runId).then(setAudioState).catch(handle)
        }}
      />
    </div>
  )
}

interface AudioNoticeProps {
  state: AudioState
  loggedIn: boolean
  onPrepare: () => void
}

/** In place of playback while the issue has no audio: rendering it costs
 * money, so it happens only when someone logged in asks for it. */
function AudioNotice({ state, loggedIn, onPrepare }: AudioNoticeProps) {
  if (state.status === 'requested' || state.status === 'rendering') {
    return <p className="audio-notice">Die Ausgabe wird vertont, das dauert etwa drei Minuten …</p>
  }
  if (!loggedIn) {
    return <p className="audio-notice muted">Für diese Ausgabe gibt es noch keine Audiofassung.</p>
  }
  const failed = state.status === 'failed'
  return (
    <p className="audio-notice">
      {failed ? 'Die Vertonung ist fehlgeschlagen. ' : 'Diese Ausgabe ist noch nicht vertont. '}
      <button onClick={onPrepare}>{failed ? 'Nochmal versuchen' : 'Jetzt vertonen'}</button>
      <span className="muted"> Dauert etwa drei Minuten.</span>
    </p>
  )
}

/** Turns around the play button while audio loads. The arc spins inside
 * a fixed-size SVG: rotating the element itself would make its bounding box
 * grow and shrink (a square turning), briefly overflowing the footer and
 * making the page jump. */
function LoadingRing() {
  return (
    <svg className="loading-ring" viewBox="0 0 66 66" aria-hidden="true">
      <circle cx="33" cy="33" r="31" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="48 147" />
    </svg>
  )
}
