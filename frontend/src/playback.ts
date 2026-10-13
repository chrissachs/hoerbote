// Play order across a whole issue: page by page, segment by segment,
// skipping pages without narration. Works off issue.json's segment counts
// alone, so it never needs a page's JSON loaded ahead of time.

import type { Article, Issue } from './api'

export interface Position {
  page: number
  segment: number
}

export function nextPosition(issue: Issue, pos: Position): Position | null {
  const i = issue.pages.findIndex((p) => p.page === pos.page)
  if (pos.segment + 1 < (issue.pages[i]?.segment_count ?? 0)) return { page: pos.page, segment: pos.segment + 1 }
  const next = issue.pages.slice(i + 1).find((p) => p.segment_count > 0)
  return next ? { page: next.page, segment: 0 } : null
}

export function previousPosition(issue: Issue, pos: Position): Position | null {
  if (pos.segment > 0) return { page: pos.page, segment: pos.segment - 1 }
  const i = issue.pages.findIndex((p) => p.page === pos.page)
  const prev = issue.pages.slice(0, i).findLast((p) => p.segment_count > 0)
  return prev ? { page: prev.page, segment: prev.segment_count - 1 } : null
}

/** The article to play when the page is clicked at (x, y), as page
 * fractions: the smallest narrated box containing the point. Boxes are
 * rectangles around possibly L-shaped articles, so they overlap -- the
 * smallest one is almost always the one the user meant. */
export function articleAt(articles: Article[], x: number, y: number): Article | null {
  const area = ([x0, y0, x1, y1]: Article['bbox']) => (x1 - x0) * (y1 - y0)
  const hits = articles.filter(
    (a) => a.segments.length > 0 && a.bbox[0] <= x && x <= a.bbox[2] && a.bbox[1] <= y && y <= a.bbox[3],
  )
  return hits.sort((a, b) => area(a.bbox) - area(b.bbox))[0] ?? null
}
