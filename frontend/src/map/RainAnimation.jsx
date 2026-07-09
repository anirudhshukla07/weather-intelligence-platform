import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import api from "../services/api";

// Falling-rain particle overlay. Drops only render where the precip RATE is
// above a small threshold, and fall faster/longer the harder it rains.
const PARTICLES = 600;
const RAIN_THRESHOLD = 1.0; // mm/step — only animate meaningful rain

export default function RainAnimation({ active, timestep, dark = true }) {
  const map = useMap();
  const canvasRef = useRef(null);
  const fieldRef = useRef(null);
  const partsRef = useRef([]);
  const rafRef = useRef(null);
  const darkRef = useRef(dark);
  darkRef.current = dark;

  useEffect(() => {
    if (!active) return;

    const canvas = document.createElement("canvas");
    canvas.style.position = "absolute";
    canvas.style.left = "0";
    canvas.style.top = "0";
    canvas.style.pointerEvents = "none";
    canvas.style.zIndex = "460";
    map.getContainer().appendChild(canvas);
    canvasRef.current = canvas;

    const sizeCanvas = () => {
      const s = map.getSize();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = s.x * dpr;
      canvas.height = s.y * dpr;
      canvas.style.width = s.x + "px";
      canvas.style.height = s.y + "px";
      canvas.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const spawn = () => {
      const s = map.getSize();
      return {
        x: Math.random() * s.x,
        y: Math.random() * s.y,
        vx: 0.6 + Math.random() * 0.6, // gentle wind slant
        // Each drop only falls once the local rate clears its own requirement,
        // so heavier rain = more drops visible (density ∝ intensity).
        req: RAIN_THRESHOLD + Math.random() * 8,
        spd: 0,
        len: 0
      };
    };

    sizeCanvas();
    partsRef.current = Array.from({ length: PARTICLES }, spawn);

    const rateAt = (lat, lng) => {
      const f = fieldRef.current;
      if (!f) return 0;
      const ix = Math.round((lng - f.lo1) / f.dx);
      const iy = Math.round((f.la1 - lat) / f.dy);
      if (ix < 0 || iy < 0 || ix >= f.nx || iy >= f.ny) return 0;
      return f.data[iy * f.nx + ix] || 0;
    };

    const frame = () => {
      const c = canvasRef.current;
      if (!c) return;
      const ctx = c.getContext("2d");
      const s = map.getSize();
      ctx.clearRect(0, 0, s.x, s.y);
      // Light drops on dark backgrounds (satellite / dark theme), deeper blue
      // on the light street map, so rain stays visible either way.
      ctx.strokeStyle = darkRef.current ? "#cfe3ff" : "#2b6fc9";
      ctx.lineWidth = 0.7;
      ctx.lineCap = "round";

      for (const p of partsRef.current) {
        const ll = map.containerPointToLatLng([p.x, p.y]);
        const r = rateAt(ll.lat, ll.lng);
        if (r >= p.req) {
          p.spd = 3.5 + Math.min(8, r * 0.55);
          p.len = 4 + Math.min(9, r * 0.5);
          // Per-drop opacity: heavier-requirement drops sit "closer" / brighter.
          ctx.globalAlpha = 0.28 + (p.req / 9) * 0.4;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p.x - p.vx * 1.6, p.y + p.len);
          ctx.stroke();
        }
        p.y += p.spd || 4;
        p.x += p.vx;
        if (p.y > s.y + 12 || p.x > s.x + 12) {
          p.y = -12;
          p.x = Math.random() * s.x;
        }
      }
      ctx.globalAlpha = 1;
      rafRef.current = requestAnimationFrame(frame);
    };

    map.on("resize zoom move", sizeCanvas);
    rafRef.current = requestAnimationFrame(frame);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      map.off("resize zoom move", sizeCanvas);
      canvas.remove();
      canvasRef.current = null;
    };
  }, [active, map]);

  // Fetch the rain-rate field for the active timestep.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    api
      .get("/precip-field", { params: { timestep } })
      .then((res) => {
        if (!cancelled) fieldRef.current = res.data;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [active, timestep]);

  return null;
}
