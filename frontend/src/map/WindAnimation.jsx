import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet-velocity";
import api from "../services/api";

// Two palettes so the streamlines stay visible on either background. Warmer
// colours kick in at higher wind speeds (Windy-style).
const WIND_COLORS_DARK = [
  "rgba(255,255,255,0.55)",
  "rgba(255,255,255,0.8)",
  "#cfe8ff",
  "#9bd0ff",
  "#ffe08a",
  "#ff9a3c",
  "#ff5a3c"
];
const WIND_COLORS_LIGHT = [
  "rgba(30,58,98,0.5)",
  "#2b5f9e",
  "#1f86b8",
  "#1aa37a",
  "#d39a1f",
  "#e2622a",
  "#cc2f2f"
];

// Animated wind-particle overlay (leaflet-velocity), shown for the wind layer.
export default function WindAnimation({ active, timestep, dark = true }) {
  const map = useMap();
  const layerRef = useRef(null);
  const layerDarkRef = useRef(dark);

  function removeLayer() {
    if (layerRef.current) {
      try {
        map.removeLayer(layerRef.current);
      } catch {
        /* noop */
      }
      layerRef.current = null;
    }
  }

  useEffect(() => {
    if (!active) {
      removeLayer();
      return;
    }

    let cancelled = false;
    api
      .get("/wind-field", { params: { timestep } })
      .then((res) => {
        if (cancelled) return;
        const data = res.data;
        // Reuse the layer unless the background (palette) changed.
        if (layerRef.current && layerDarkRef.current === dark) {
          layerRef.current.setData(data); // update in place (no flicker)
          return;
        }
        removeLayer();
        layerDarkRef.current = dark;
        const layer = L.velocityLayer({
          displayValues: true,
          displayOptions: {
            velocityType: "Wind",
            position: "bottomright",
            displayPosition: "bottomright",
            displayEmptyString: "Hover the map for wind",
            speedUnit: "m/s",
            angleConvention: "meteoCW"
          },
          data,
          // Color maps to TRUE wind speed on a fixed 0–25 m/s scale, so a given
          // colour means the same speed in every frame.
          minVelocity: 0,
          maxVelocity: 25,
          velocityScale: 0.012,
          particleAge: 90,
          particleMultiplier: 1 / 280,
          lineWidth: 1.3,
          frameRate: 20,
          colorScale: dark ? WIND_COLORS_DARK : WIND_COLORS_LIGHT,
          opacity: 0.95
        });
        layer.addTo(map);
        layerRef.current = layer;
      })
      .catch(() => {
        /* no wind data / not loaded */
      });

    return () => {
      cancelled = true;
    };
  }, [active, timestep, map, dark]);

  // Clean up on unmount.
  useEffect(() => () => removeLayer(), [map]);

  return null;
}
