import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Measures a DOM element and keeps the size in state.
 *
 * deck.gl normally self-sizes via its own ResizeObserver, but that observer
 * does not fire in every embedding (headless capture, some webviews), leaving
 * the WebGL drawing buffer stuck at the 300x150 canvas default while the CSS
 * box is full-bleed -- a map that looks blank or badly scaled. Measuring the
 * container ourselves and handing deck explicit pixel dimensions makes the
 * size deterministic everywhere.
 */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  const measure = useCallback(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    setSize((prev) =>
      Math.abs(prev.width - width) < 0.5 && Math.abs(prev.height - height) < 0.5
        ? prev
        : { width, height },
    )
  }, [])

  useEffect(() => {
    measure()
    // Belt and braces: rAF catches the first paint, RO catches later layout
    // changes, and the window listener covers environments without a working RO.
    const raf = requestAnimationFrame(measure)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    if (ro && ref.current) ro.observe(ref.current)
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(raf)
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [measure])

  return { ref, ...size }
}
