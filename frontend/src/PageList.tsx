import { useEffect, useRef } from 'react'
import { thumbnailUrl, type Issue } from './api'

interface Props {
  issue: Issue
  current: number
  onSelect: (page: number) => void
}

/** Every page of the issue as a thumbnail, one under the other (pages
 * without narration dimmed), like a PDF reader's sidebar. The current page
 * is highlighted and kept in view. */
export function PageList({ issue, current, onSelect }: Props) {
  const currentRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    currentRef.current?.scrollIntoView({ block: 'center' })
  }, [current])

  return (
    <nav className="page-list" aria-label="Seiten">
      {issue.pages.map((p) => (
        <button key={p.page} ref={p.page === current ? currentRef : undefined}
                className={p.page === current ? 'current' : ''} onClick={() => onSelect(p.page)}
                aria-label={`Seite ${p.page}`} aria-current={p.page === current ? 'page' : undefined}>
          <img src={thumbnailUrl(issue.run_id, p.page)} alt="" loading="lazy"
               style={{ aspectRatio: p.aspect_ratio, opacity: p.segment_count ? 1 : 0.45 }} />
          <span>{p.page}{p.segment_count ? '' : ' · ohne Ton'}</span>
        </button>
      ))}
      {issue.attribution && <p className="attribution">{issue.attribution}</p>}
    </nav>
  )
}
