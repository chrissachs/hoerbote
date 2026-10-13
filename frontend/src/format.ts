import type { IssueSummary } from './api'

// Edition slugs from config/papers.toml that are worth naming;
// a paper's only edition ("daily") isn't.
const EDITIONS: Record<string, string> = { morning: 'Morgen-Ausgabe', evening: 'Abend-Ausgabe' }

function parseIsoDate(iso: string): Date | null {
  const date = new Date(`${iso}T12:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

const LONG_DATE: Intl.DateTimeFormatOptions = { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }

/** "Dienstag, 12. Oktober 1926" from "1926-10-12" (as given if it isn't a date). */
export function longDate(iso: string): string {
  return parseIsoDate(iso)?.toLocaleDateString('de-DE', LONG_DATE) ?? iso
}

/** "Dienstag, 12. Oktober 1926". */
export const issueDate = (issue: IssueSummary) => longDate(issue.date)

/** ["12. Oktober 1926", "Dienstag"] for a card's two lines. */
export function issueDateLines(issue: IssueSummary): [string, string] {
  const date = new Date(`${issue.date}T12:00:00`)
  return [
    date.toLocaleDateString('de-DE', { day: 'numeric', month: 'long', year: 'numeric' }),
    date.toLocaleDateString('de-DE', { weekday: 'long' }),
  ]
}

export const issueEdition = (issue: IssueSummary): string | null => EDITIONS[issue.edition] ?? null
