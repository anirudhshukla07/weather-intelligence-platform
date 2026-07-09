import { useMemo, useRef, useState, useLayoutEffect, useEffect } from "react";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const MIN_ZOOM = 1;
const MAX_ZOOM = 16;

// WRF timestamps arrive as "2025-07-01 00:00:00" (underscore already replaced).
function parseWRF(ts) {
  if (!ts) return null;
  const m = String(ts)
    .replace("_", " ")
    .match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);

  if (!m) return null;

  const [, y, mo, d, h, mi] = m.map(Number);
  return new Date(Date.UTC(y, mo - 1, d, h, mi));
}

function dayNumber(dt) {
  if (!dt) return 0;
  return Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate());
}

function fmtTime(dt) {
  if (!dt) return "";
  const h = String(dt.getUTCHours()).padStart(2, "0");
  const m = String(dt.getUTCMinutes()).padStart(2, "0");
  return `${h}:${m} UTC`;
}

function fmtFull(dt) {
  if (!dt) return "—";
  return `${DOW[dt.getUTCDay()]}, ${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()} · ${fmtTime(dt)}`;
}

export default function Timeline({
  timestamps,
  timestep,
  setTimestep,
  setIsPlaying,
  rendering,
  hasDataset,
  alertSeverity = {},
}) {
  const count = timestamps.length;
  const dates = useMemo(() => timestamps.map(parseWRF), [timestamps]);

  const current = dates[timestep] || null;
  const first = dates[0] || null;
  const last = dates[count - 1] || null;

  const dayIndex =
    current && first
      ? Math.round((dayNumber(current) - dayNumber(first)) / 86400000)
      : 0;

  const totalDays =
    first && last
      ? Math.round((dayNumber(last) - dayNumber(first)) / 86400000) + 1
      : 0;

  // One tick per timestep: the date at each new day, the hour otherwise.
  const ticks = useMemo(() => {
    return dates
      .map((dt, i) => {
        if (!dt) return null;
        const prev = dates[i - 1];
        const dayStart = i === 0 || (prev && dayNumber(dt) !== dayNumber(prev));
        const hh = String(dt.getUTCHours()).padStart(2, "0");

        return {
          index: i,
          dayStart,
          label: dayStart
            ? `${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}`
            : `${hh}:00`,
          full: fmtFull(dt),
        };
      })
      .filter(Boolean);
  }, [dates]);

  const disabled = !hasDataset || count === 0;

  // ---- Zoom (expand/contract the time axis) ----
  const [zoom, setZoom] = useState(1);
  const scrollRef = useRef(null);
  const anchorRef = useRef(null);

  function stopPlay() {
    if (typeof setIsPlaying === "function") setIsPlaying(false);
  }

  function go(index) {
    setTimestep(Math.min(count - 1, Math.max(0, index)));
  }

  // Zoom by `factor`, keeping the point at viewport-x `focusX` stationary.
  function applyZoom(factor, focusX) {
    const el = scrollRef.current;
    setZoom((z) => {
      const nz = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * factor));
      if (el && nz !== z) {
        const fx = focusX != null ? focusX : el.clientWidth / 2;
        anchorRef.current = { contentX: el.scrollLeft + fx, ratio: nz / z, fx };
      }
      return nz;
    });
  }

  // Wheel-to-zoom (native non-passive listener so we can preventDefault).
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (disabled) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      applyZoom(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX - rect.left);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled]);

  // Apply the anchored scroll after the new width lays out.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !anchorRef.current) return;
    const { contentX, ratio, fx } = anchorRef.current;
    el.scrollLeft = contentX * ratio - fx;
    anchorRef.current = null;
  }, [zoom]);

  // Keep the active step visible when zoomed in.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || zoom <= 1 || count < 2) return;
    const x = (timestep / (count - 1)) * el.scrollWidth;
    const pad = 48;
    if (x < el.scrollLeft + pad) el.scrollLeft = x - pad;
    else if (x > el.scrollLeft + el.clientWidth - pad)
      el.scrollLeft = x - el.clientWidth + pad;
  }, [timestep, zoom, count]);

  // Track the viewport width + scroll offset so the hover label can be drawn
  // OUTSIDE the clipped scroll area yet still line up with the thumb.
  const [viewW, setViewW] = useState(0);
  const [scrollX, setScrollX] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => setViewW(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---- Click-and-drag panning (replaces the scrollbar) ----
  const panRef = useRef(null);
  const draggedRef = useRef(false);
  const [panning, setPanning] = useState(false);

  function onPointerDown(e) {
    const el = scrollRef.current;
    if (disabled || !el || el.scrollWidth <= el.clientWidth) return;
    // Let the slider keep scrubbing; pan from anywhere else.
    if (e.target.closest && e.target.closest(".tl-range")) return;
    panRef.current = { x: e.clientX, left: el.scrollLeft };
    draggedRef.current = false;
    setPanning(true);
  }

  useEffect(() => {
    function move(e) {
      const p = panRef.current;
      const el = scrollRef.current;
      if (!p || !el) return;
      const dx = e.clientX - p.x;
      if (Math.abs(dx) > 3) draggedRef.current = true;
      el.scrollLeft = p.left - dx;
    }
    function up() {
      if (panRef.current) {
        panRef.current = null;
        setPanning(false);
      }
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);

  const pct = count > 1 ? (timestep / (count - 1)) * 100 : 0;
  const dense = zoom >= 1.8 ? "true" : "false";

  // On-screen x of the current step inside the viewport (accounts for zoom+pan).
  const contentW = viewW * zoom;
  const cursorX =
    count > 1 && viewW ? (timestep / (count - 1)) * contentW - scrollX : 0;
  const showCursor =
    !disabled && current && viewW > 0 && cursorX >= -2 && cursorX <= viewW + 2;

  return (
    <div className={`timeline ${disabled ? "is-disabled" : ""}`}>
      <div className="timeline-main">
        <div className="timeline-toprow">
          <div className="timeline-readout">
            <strong>{fmtFull(current)}</strong>
            <span>
              {disabled
                ? "Load a dataset to scrub the forecast timeline"
                : `Step ${timestep + 1} of ${count}` +
                  (totalDays ? ` · Day ${dayIndex + 1} of ${totalDays}` : "") +
                  (rendering ? " · rendering…" : "")}
            </span>
          </div>

          <div className="tl-zoom">
            <button
              onClick={() => applyZoom(1 / 1.4)}
              disabled={disabled || zoom <= MIN_ZOOM}
              title="Zoom out (or scroll down over the timeline)"
              aria-label="Zoom out"
            >
              −
            </button>
            <span className="tl-zoom-val">{zoom.toFixed(1)}×</span>
            <button
              onClick={() => applyZoom(1.4)}
              disabled={disabled || zoom >= MAX_ZOOM}
              title="Zoom in (or scroll up over the timeline)"
              aria-label="Zoom in"
            >
              +
            </button>
          </div>
        </div>

        <div className="tl-viewport">
          {showCursor && (
            <div className="tl-cursor" style={{ left: `${cursorX}px` }}>
              {`${DOW[current.getUTCDay()]} ${MONTHS[current.getUTCMonth()]} ${current.getUTCDate()} · ${fmtTime(current)}`}
            </div>
          )}

          <div
            className={`tl-scroll ${zoom > 1 ? "can-pan" : ""} ${
              panning ? "panning" : ""
            }`}
            ref={scrollRef}
            onPointerDown={onPointerDown}
            onScroll={(e) => setScrollX(e.currentTarget.scrollLeft)}
          >
          <div
            className="tl-content"
            data-zoomed={dense}
            style={{ width: `${zoom * 100}%` }}
          >
            <div className="timeline-track">
              <div className="tl-fill" style={{ width: `${pct}%` }} />

              <input
                className="tl-range"
                type="range"
                min={0}
                max={Math.max(0, count - 1)}
                step={1}
                value={timestep}
                disabled={disabled}
                onChange={(e) => {
                  stopPlay();
                  go(Number(e.target.value));
                }}
              />
            </div>

            <div className="tl-ticks">
              {ticks.map((t) => (
                <button
                  key={t.index}
                  className={`tl-tick ${t.dayStart ? "day" : "hour"} ${
                    t.index === timestep ? "active" : ""
                  } ${alertSeverity[t.index] ? "alert-" + alertSeverity[t.index] : ""}`}
                  style={{
                    left: count > 1 ? `${(t.index / (count - 1)) * 100}%` : "0%",
                  }}
                  onClick={() => {
                    if (draggedRef.current) {
                      draggedRef.current = false;
                      return;
                    }
                    stopPlay();
                    go(t.index);
                  }}
                  disabled={disabled}
                  title={t.full}
                >
                  <span className="tl-tick-mark" />
                  <span className="tl-tick-label">{t.label}</span>
                </button>
              ))}
            </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
