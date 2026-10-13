// Inline SVG controls -- the media-control characters (⏪ ⏩) render as
// colored emoji on most systems, clashing with the rest.

const icon = (d: string) => () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d={d} /></svg>
)

export const Play = icon('M8 5v14l11-7z')
export const Pause = icon('M6 5h4v14H6zM14 5h4v14h-4z')
export const PreviousSegment = icon('M11 6v12l-8.5-6zM21 6v12l-8.5-6z')
export const NextSegment = icon('M13 6v12l8.5-6zM3 6v12l8.5-6z')
export const PreviousPage = icon('M6 6h2v12H6zM9.5 12l8.5 6V6z')
export const NextPage = icon('M16 6h2v12h-2zM6 18l8.5-6L6 6z')
export const ZoomIn = icon('M10 4a6 6 0 1 0 3.9 10.6l4.8 4.8 1.4-1.4-4.8-4.8A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM9 7v2H7v2h2v2h2v-2h2V9h-2V7z')
export const ZoomOut = icon('M10 4a6 6 0 1 0 3.9 10.6l4.8 4.8 1.4-1.4-4.8-4.8A6 6 0 0 0 10 4zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM7 9v2h6V9z')
export const FitPage = icon('M4 4h6v2H6v4H4zm10 0h6v6h-2V6h-4zM4 14h2v4h4v2H4zm14 0h2v6h-6v-2h4z')
export const Follow = icon('M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm-1-6h2v3h-2zm0 17h2v3h-2zM2 11h3v2H2zm17 0h3v2h-3z')
export const Pages = icon('M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z')
export const Back = icon('M15.4 6.4 14 5l-7 7 7 7 1.4-1.4L9.8 12z')
