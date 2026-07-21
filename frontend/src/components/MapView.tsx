import { useEffect, useMemo, useRef, useState } from 'react'
import { ArcLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import type { PickingInfo, MapViewState } from '@deck.gl/core'
import Map, { type MapRef } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'

import DeckOverlay from './DeckOverlay'
import type { NetworkPayload, NetworkNode, Flow } from '../lib/api'
import { corridorRgb, corridorLabel, num } from '../lib/format'
import { useElementSize } from '../lib/useElementSize'

const INITIAL_VIEW: MapViewState = {
  longitude: 62,
  latitude: 17,
  zoom: 3.1,
  pitch: 32,
  bearing: 0,
}

// CARTO dark-matter needs no API key. If the network is down at demo time the
// basemap silently falls back to the flat ocean fill below and the data layers
// still render -- the demo must never depend on a tile server.
const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

const FALLBACK_STYLE = {
  version: 8 as const,
  sources: {},
  layers: [
    { id: 'bg', type: 'background' as const, paint: { 'background-color': '#080d14' } },
  ],
}

interface Props {
  network: NetworkPayload | null
  selectedCorridor: string | null
  onSelectCorridor: (c: string | null) => void
}

type Hover = { x: number; y: number; title: string; lines: string[] } | null

export default function MapView({ network, selectedCorridor, onSelectCorridor }: Props) {
  const [hover, setHover] = useState<Hover>(null)
  const [styleFailed, setStyleFailed] = useState(false)
  const { ref: hostRef, width, height } = useElementSize<HTMLDivElement>()
  const mapRef = useRef<MapRef>(null)

  // MapboxOverlay sizes deck's canvas from MapLibre's `resize` event. Driving
  // it from our own measurement keeps the basemap and the deck overlay in step
  // when the map host changes size (panels opening, window resize) rather than
  // relying solely on MapLibre's internal ResizeObserver.
  useEffect(() => {
    if (!width || !height) return
    mapRef.current?.getMap()?.resize()
  }, [width, height])

  const nodesByKind = useMemo(() => {
    const g: Record<string, NetworkNode[]> = {}
    for (const n of network?.nodes ?? []) (g[n.kind] ??= []).push(n)
    return g
  }, [network])

  const dimmed = (corridor: string) =>
    selectedCorridor !== null && selectedCorridor !== corridor

  const layers = useMemo(() => {
    if (!network) return []

    const flowAlpha = (f: Flow) => (dimmed(f.corridor) ? 34 : 190)

    return [
      // --- corridor spines -------------------------------------------
      new PathLayer<(typeof network.corridor_paths)[number]>({
        id: 'corridors',
        data: network.corridor_paths,
        getPath: (d) => d.path,
        getColor: (d) => {
          const [r, g, b] = corridorRgb(d.corridor)
          return [r, g, b, dimmed(d.corridor) ? 30 : 120]
        },
        getWidth: (d) => (selectedCorridor === d.corridor ? 4 : 2),
        widthUnits: 'pixels',
        widthMinPixels: 1.5,
        capRounded: true,
        jointRounded: true,
        pickable: true,
        onClick: (info: PickingInfo) => {
          const d = info.object as { corridor: string } | undefined
          if (d) onSelectCorridor(selectedCorridor === d.corridor ? null : d.corridor)
        },
        onHover: (info: PickingInfo) => {
          const d = info.object as (typeof network.corridor_paths)[number] | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: corridorLabel(d.corridor),
                  lines: [
                    `${num(d.baseline_kb_week / 7)} kbd baseline flow`,
                    'click to isolate this corridor',
                  ],
                }
              : null,
          )
        },
        updateTriggers: { getColor: selectedCorridor, getWidth: selectedCorridor },
      }),

      // --- baseline import arcs (supplier origin -> discharge port) ----
      new ArcLayer<Flow>({
        id: 'flows',
        data: network.flows,
        getSourcePosition: (d) => d.from,
        getTargetPosition: (d) => d.to,
        getSourceColor: (d) => {
          const [r, g, b] = corridorRgb(d.corridor)
          return [r, g, b, flowAlpha(d)]
        },
        getTargetColor: (d) => {
          const [r, g, b] = corridorRgb(d.corridor)
          return [r, g, b, Math.round(flowAlpha(d) * 0.45)]
        },
        getWidth: (d) => Math.max(1, Math.sqrt(d.kb_week) / 9),
        getHeight: 0.32,
        greatCircle: true,
        widthMinPixels: 1,
        pickable: true,
        onHover: (info: PickingInfo) => {
          const d = info.object as Flow | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: `${d.grade} — ${d.country}`,
                  lines: [
                    `${num(d.kb_week / 7)} kbd  (${d.share_pct.toFixed(1)}% of imports)`,
                    `via ${corridorLabel(d.corridor)}`,
                  ],
                }
              : null,
          )
        },
        updateTriggers: { getSourceColor: selectedCorridor, getTargetColor: selectedCorridor },
      }),

      // --- chokepoints -------------------------------------------------
      new ScatterplotLayer<NetworkNode>({
        id: 'chokepoints',
        data: nodesByKind.chokepoint ?? [],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 3200 * Math.sqrt((d.global_oil_transit_mbd as number) ?? 1),
        radiusMinPixels: 5,
        radiusMaxPixels: 20,
        stroked: true,
        filled: true,
        getFillColor: [239, 108, 68, 40],
        getLineColor: [239, 108, 68, 210],
        lineWidthMinPixels: 1.4,
        pickable: true,
        onHover: (info: PickingInfo) => {
          const d = info.object as NetworkNode | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: d.label,
                  lines: [
                    `${d.global_oil_transit_mbd} mb/d global transit`,
                    (d.bypass_capacity_mbd as number) > 0
                      ? `${d.bypass_capacity_mbd} mb/d bypass capacity`
                      : 'no pipeline bypass',
                  ],
                }
              : null,
          )
        },
      }),

      // --- supplier origins -------------------------------------------
      new ScatterplotLayer<NetworkNode>({
        id: 'suppliers',
        data: nodesByKind.supplier ?? [],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 900 * Math.sqrt(((d.baseline_kb_week as number) ?? 100) / 7),
        radiusMinPixels: 2.5,
        radiusMaxPixels: 14,
        filled: true,
        stroked: false,
        getFillColor: (d) => {
          const [r, g, b] = corridorRgb(d.corridor as string)
          return [r, g, b, dimmed(d.corridor as string) ? 50 : 205]
        },
        pickable: true,
        onHover: (info: PickingInfo) => {
          const d = info.object as NetworkNode | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: d.label,
                  lines: [
                    `${d.country} · ${d.load_port}`,
                    `API ${d.api_gravity}°  S ${d.sulfur_pct}%`,
                    `${num(((d.baseline_kb_week as number) ?? 0) / 7)} kbd`,
                  ],
                }
              : null,
          )
        },
        updateTriggers: { getFillColor: selectedCorridor },
      }),

      // --- refineries --------------------------------------------------
      new ScatterplotLayer<NetworkNode>({
        id: 'refineries',
        data: nodesByKind.refinery ?? [],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 260 * Math.sqrt((d.capacity_kbd as number) ?? 100),
        radiusMinPixels: 4,
        radiusMaxPixels: 26,
        stroked: true,
        filled: true,
        getFillColor: [245, 158, 11, 55],
        getLineColor: [245, 158, 11, 235],
        lineWidthMinPixels: 1.6,
        pickable: true,
        onHover: (info: PickingInfo) => {
          const d = info.object as NetworkNode | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: d.label,
                  lines: [
                    `${d.operator}`,
                    `${num(d.capacity_kbd as number)} kbd nameplate`,
                    `crude diet: API ${d.api_min}–${d.api_max}°, S ≤ ${d.sulfur_max_pct}%`,
                    `Nelson complexity ${d.nelson_complexity}`,
                  ],
                }
              : null,
          )
        },
      }),

      // --- strategic reserve -------------------------------------------
      new ScatterplotLayer<NetworkNode>({
        id: 'spr',
        data: nodesByKind.spr ?? [],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 9000 * Math.sqrt((d.capacity_mmbbl as number) ?? 1),
        radiusMinPixels: 6,
        radiusMaxPixels: 30,
        stroked: true,
        filled: true,
        getFillColor: [56, 189, 248, 42],
        getLineColor: [56, 189, 248, 225],
        lineWidthMinPixels: 1.8,
        pickable: true,
        onHover: (info: PickingInfo) => {
          const d = info.object as NetworkNode | undefined
          setHover(
            d
              ? {
                  x: info.x,
                  y: info.y,
                  title: `SPR — ${d.label}`,
                  lines: [
                    `${d.capacity_mmbbl} mmbbl capacity`,
                    `${Math.round(((d.fill_pct as number) ?? 0) * 100)}% filled`,
                    `max drawdown ${num(d.max_drawdown_kbd as number)} kbd`,
                  ],
                }
              : null,
          )
        },
      }),

      // --- refinery labels ---------------------------------------------
      new TextLayer<NetworkNode>({
        id: 'refinery-labels',
        data: (nodesByKind.refinery ?? []).filter(
          (d) => ((d.capacity_kbd as number) ?? 0) >= 240,
        ),
        getPosition: (d) => [d.lon, d.lat],
        getText: (d) => d.label.split(' ')[0],
        getSize: 10,
        getColor: [232, 239, 247, 165],
        getPixelOffset: [0, -16],
        fontFamily: 'ui-monospace, monospace',
        characterSet: 'auto',
        billboard: true,
      }),
    ]
  }, [network, nodesByKind, selectedCorridor, onSelectCorridor])

  return (
    <div className="map-host" ref={hostRef}>
      <Map
        ref={mapRef}
        initialViewState={INITIAL_VIEW}
        mapStyle={styleFailed ? FALLBACK_STYLE : BASEMAP}
        onError={() => setStyleFailed(true)}
        attributionControl={{ compact: true }}
        style={{ width: '100%', height: '100%' }}
        onLoad={(e) => {
          // Dev-only handle so the map can be driven from the console when
          // debugging projection / picking. Never present in a production build.
          if (import.meta.env.DEV) {
            ;(window as unknown as { __map?: unknown }).__map = e.target
          }
        }}
      >
        <DeckOverlay
          layers={layers}
          // Overlaid, not interleaved: deck draws on its own canvas above the
          // basemap. Interleaved would inject the layers into MapLibre's style,
          // which means a slow or unreachable tile server takes the data layers
          // down with it. Overlaid keeps the network visible even with no
          // basemap at all -- the demo must never depend on a tile server.
          interleaved={false}
          getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'grab')}
          onClick={(info) => {
            if (!info.object) onSelectCorridor(null)
          }}
        />
      </Map>

      {hover && (
        <div
          className="tooltip"
          style={{ left: hover.x + 14, top: hover.y + 14 }}
        >
          <div className="tooltip-title">{hover.title}</div>
          {hover.lines.map((l, i) => (
            <div className="tooltip-line" key={i}>
              {l}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
