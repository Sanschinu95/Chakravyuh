export const num = (v: number, d = 0) =>
  v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

export const kbd = (v: number) => `${num(v)} kbd`

export const pct = (v: number, d = 1) => `${v.toFixed(d)}%`

/** Indian-market convention: crore for INR, plain for USD mn. */
export const crore = (usdMn: number) => `₹${num(usdMn * 8.65, 0)} cr`

export const usdMn = (v: number) => `$${num(v, v < 10 ? 1 : 0)}M`

export const days = (v: number) => `${v.toFixed(1)}d`

export const CORRIDOR_LABEL: Record<string, string> = {
  Hormuz: 'Strait of Hormuz',
  RedSea_Suez: 'Red Sea / Suez',
  Cape: 'Cape of Good Hope',
  Malacca: 'Strait of Malacca',
}

export const corridorLabel = (c: string) => CORRIDOR_LABEL[c] ?? c

/** Corridor accent colours -- distinct from provenance colours on purpose. */
export const CORRIDOR_RGB: Record<string, [number, number, number]> = {
  Hormuz: [239, 108, 68],
  RedSea_Suez: [232, 196, 74],
  Cape: [86, 176, 222],
  Malacca: [154, 122, 232],
}

export const corridorRgb = (c: string): [number, number, number] =>
  CORRIDOR_RGB[c] ?? [140, 160, 180]

export const corridorCss = (c: string) => {
  const [r, g, b] = corridorRgb(c)
  return `rgb(${r},${g},${b})`
}
