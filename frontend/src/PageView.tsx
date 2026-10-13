import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { TransformComponent, TransformWrapper, type ReactZoomPanPinchContentRef } from 'react-zoom-pan-pinch'
import type { BBox, Page } from './api'
import { FitPage, Follow, ZoomIn, ZoomOut } from './icons'
import { articleAt } from './playback'

interface Props {
  page: Page
  imageSrc: string
  thumbnailSrc: string
  // article_idx being narrated right now, if any.
  activeArticle: number | null
  onArticleClick: (articleIdx: number) => void
}

const MAX_SCALE = 8
const ANIMATION_MS = 400
// Scale added per unit of a wheel event's deltaY (the library multiplies):
// a mouse wheel notch (deltaY ~100) zooms by ~0.2, a trackpad smoothly.
const WHEEL_STEP = 0.002
// Zoom buttons: the library's step is exponential, ~1.35x per click.
const BUTTON_STEP = 0.3
// Matches .page-view's padding in index.css.
const VIEW_PADDING_PX = 8
// A pointer moving further than this between down and up is a drag (pan),
// not a click on an article.
const CLICK_SLOP_PX = 6

/** The page image with the narrated article highlighted, zoomable (buttons,
 * wheel, pinch) and pannable. In follow mode it zooms to the narrated
 * article; zooming or panning by hand turns follow mode off. Boxes are page
 * fractions, so they're positioned in % and scale with the image. The
 * narrated article is lit by one highlight that glides from article to
 * article and dims the rest of the page. */
export function PageView({ page, imageSrc, thumbnailSrc, activeArticle, onArticleClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const size = useFitSize(containerRef, page.aspect_ratio)
  const zoom = useRef<ReactZoomPanPinchContentRef>(null)
  const [follow, setFollow] = useState(true)
  const pointerDown = useRef<{ x: number; y: number } | null>(null)
  const pageRef = useRef<HTMLDivElement>(null)

  const active = page.articles.find((a) => a.article_idx === activeArticle)
  // Where the highlight is: the narrated article's box, kept while nothing
  // is narrated so the highlight fades out in place instead of jumping.
  const [spotBox, setSpotBox] = useState(active?.bbox ?? null)
  if (active && active.bbox !== spotBox) setSpotBox(active.bbox)

  // Follow mode: fit the narrated article into view (whichever of width or
  // height is tighter), centered; the whole page when nothing is narrated.
  useEffect(() => {
    const z = zoom.current
    const view = containerRef.current
    if (!follow || !z || !view || !size) return
    if (!active) {
      void z.centerView(1, ANIMATION_MS)
      return
    }
    const [x0, y0, x1, y1] = active.bbox
    const box = { x: x0 * size.w, y: y0 * size.h, w: (x1 - x0) * size.w, h: (y1 - y0) * size.h }
    // The zoom area: the view minus its padding.
    const vw = view.clientWidth - 2 * VIEW_PADDING_PX
    const vh = view.clientHeight - 2 * VIEW_PADDING_PX
    const scale = Math.min(Math.max(Math.min((0.92 * vw) / box.w, (0.92 * vh) / box.h), 1), MAX_SCALE)
    // Article centered, but the page kept in view: centered where it's
    // smaller than the view, its edges at the view's edges otherwise.
    const place = (center: number, length: number, view: number) =>
      length <= view ? (view - length) / 2 : Math.min(0, Math.max(view - length, view / 2 - center))
    const x = place((box.x + box.w / 2) * scale, size.w * scale, vw)
    const y = place((box.y + box.h / 2) * scale, size.h * scale, vh)
    void z.setTransform(x, y, scale, ANIMATION_MS)
  }, [active, follow, size])

  function click(e: MouseEvent<HTMLDivElement>) {
    const start = pointerDown.current
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > CLICK_SLOP_PX) return
    const rect = e.currentTarget.getBoundingClientRect()
    const hit = articleAt(page.articles, (e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height)
    if (hit) onArticleClick(hit.article_idx)
  }

  const byHand = () => setFollow(false)

  return (
    <div className="page-view" ref={containerRef}>
      {size && (
        <TransformWrapper ref={zoom} minScale={1} maxScale={MAX_SCALE} centerOnInit centerZoomedOut
                          doubleClick={{ disabled: true }} wheel={{ step: WHEEL_STEP }}
                          onPanning={byHand} onWheelStart={byHand} onPinchStart={byHand}
                          // The zoom for CSS, so outlines keep their on-screen width
                          // (set directly: no re-render per animation frame).
                          onTransform={(_, { scale }) => pageRef.current?.style.setProperty('--zoom', String(scale))}>
          <TransformComponent wrapperStyle={{ width: '100%', height: '100%' }}>
            <div className="page" ref={pageRef} style={{ width: size.w, height: size.h, backgroundImage: `url(${thumbnailSrc})` }}
                 onPointerDown={(e: PointerEvent) => { pointerDown.current = { x: e.clientX, y: e.clientY } }}
                 onClick={click}>
              <img src={imageSrc} alt={`Seite ${page.page}`} draggable={false} />
              {page.articles.filter((a) => a.segments.length > 0 && a !== active).map((a) => (
                <div key={a.article_idx} className="box" style={boxStyle(a.bbox)} />
              ))}
              {spotBox && <div className={active ? 'spot' : 'spot hidden'} style={boxStyle(spotBox)} />}
            </div>
          </TransformComponent>
        </TransformWrapper>
      )}
      <div className="zoom-controls">
        <button onClick={() => { byHand(); zoom.current?.zoomIn(BUTTON_STEP) }} aria-label="Vergrößern"><ZoomIn /></button>
        <button onClick={() => { byHand(); zoom.current?.zoomOut(BUTTON_STEP) }} aria-label="Verkleinern"><ZoomOut /></button>
        <button onClick={() => { byHand(); void zoom.current?.centerView(1, ANIMATION_MS) }} aria-label="Ganze Seite">
          <FitPage />
        </button>
        <button className={follow ? 'on' : ''} onClick={() => setFollow(!follow)} aria-pressed={follow}
                aria-label="Mitlesen" title="Mitlesen: zoomt zum vorgelesenen Beitrag"><Follow /></button>
      </div>
    </div>
  )
}

const boxStyle = ([x0, y0, x1, y1]: BBox) => ({
  left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
})

/** The largest size with the page's aspect ratio that fits the element,
 * kept up to date as it resizes. */
function useFitSize(ref: React.RefObject<HTMLDivElement | null>, aspectRatio: number) {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const w = Math.min(el.clientWidth - 2 * VIEW_PADDING_PX, (el.clientHeight - 2 * VIEW_PADDING_PX) * aspectRatio)
      setSize((s) => (s && Math.abs(s.w - w) < 1 ? s : { w, h: w / aspectRatio }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref, aspectRatio])
  return size
}
