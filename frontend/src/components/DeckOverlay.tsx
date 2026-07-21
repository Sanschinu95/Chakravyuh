import { MapboxOverlay, type MapboxOverlayProps } from '@deck.gl/mapbox'
import { useControl } from 'react-map-gl/maplibre'

/**
 * deck.gl layers rendered as a MapLibre control.
 *
 * We deliberately let MapLibre own the container, the camera and the resize
 * lifecycle rather than nesting <Map> inside <DeckGL>. With the nested layout
 * deck.gl sizes itself purely from a ResizeObserver, which does not fire in
 * every embedding and leaves the map stuck at the 300x150 canvas default.
 * As an overlay there is exactly one sizing authority, so the map is correct
 * wherever it runs.
 */
export default function DeckOverlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props))
  overlay.setProps(props)
  return null
}
