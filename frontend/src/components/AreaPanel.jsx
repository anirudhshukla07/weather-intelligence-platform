import { useState } from "react";

function Caret() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 15l6-6 6 6" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"
      strokeWidth="2.6" strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export default function AreaPanel({
  areaMode,
  onStart,
  onFinish,
  onCancel,
  onClear,
  pointCount,
  areaStats,
  areaBusy,
  disabled
}) {
  const [open, setOpen] = useState(true);

  return (
    <>
      {/* Toggle button (hidden while actively drawing) */}
      {!areaMode && (
        <button
          className={`area-fab ${areaStats ? "active" : ""}`}
          onClick={onStart}
          disabled={disabled}
          title="Draw an area to query"
          aria-label="Draw an area to query"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 7l7-3 7 3-2 11-5 2-5-2z" />
          </svg>
        </button>
      )}

      {/* Drawing hint bar */}
      {areaMode && (
        <div className="area-hint">
          <span>
            Click the map to add points · double-click to finish
            {pointCount > 0 ? ` · ${pointCount} point${pointCount > 1 ? "s" : ""}` : ""}
          </span>
          <div className="area-hint-actions">
            <button
              className="area-btn primary"
              onClick={onFinish}
              disabled={pointCount < 3}
            >
              Finish
            </button>
            <button className="area-btn" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Result card */}
      {areaStats && !areaMode && (
        <div className={`area-card ${open ? "" : "collapsed"}`}>
          <div className="area-card-head">
            <span>Area · {areaStats.label}</span>
            <div className="area-card-actions">
              {!areaBusy && !areaStats.is_empty && (
                <button
                  className="area-card-toggle"
                  onClick={() => setOpen(!open)}
                  title={open ? "Collapse" : "Expand"}
                  aria-label={open ? "Collapse" : "Expand"}
                >
                  <Caret />
                </button>
              )}
              <button className="area-card-close" onClick={onClear} title="Clear area">
                <CloseIcon />
              </button>
            </div>
          </div>

          {areaBusy ? (
            <p className="area-card-busy">Calculating…</p>
          ) : areaStats.is_empty ? (
            <p className="area-card-busy">{areaStats.display_text}</p>
          ) : (
            <>
              <p className="area-card-value">{areaStats.display_text}</p>
              {open && (
                <>
                  <div className="area-grid">
                    <span>Min<strong>{areaStats.min?.toFixed?.(2)}</strong></span>
                    <span>Max<strong>{areaStats.max?.toFixed?.(2)}</strong></span>
                    <span>Mean<strong>{areaStats.mean?.toFixed?.(2)}</strong></span>
                    <span>Std<strong>{areaStats.std?.toFixed?.(2)}</strong></span>
                  </div>
                  <p className="area-card-foot">
                    {areaStats.count} grid points · {areaStats.unit || "value"}
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
