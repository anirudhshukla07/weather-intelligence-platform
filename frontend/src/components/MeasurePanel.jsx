function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"
      strokeWidth="2.6" strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function KindToggle({ kind, setKind }) {
  return (
    <div className="measure-kind" role="group" aria-label="Measure mode">
      <button className={kind === "air" ? "on" : ""} onClick={() => setKind("air")}>
        Air
      </button>
      <button className={kind === "sea" ? "on" : ""} onClick={() => setKind("sea")}>
        Sea
      </button>
    </div>
  );
}

export default function MeasurePanel({
  measureMode,
  onStart,
  onFinish,
  onCancel,
  onClear,
  pointCount,
  distanceText,
  warning,
  kind,
  setKind,
  busy,
  hasResult,
  disabled
}) {
  return (
    <>
      {!measureMode && !hasResult && (
        <button
          className="measure-fab"
          onClick={onStart}
          disabled={disabled}
          title="Measure distance"
          aria-label="Measure distance"
        >
          <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 17 17 3l4 4L7 21z" />
            <path d="M7 9l2 2M10 6l2 2M13 9l2 2M16 6l2 2" />
          </svg>
        </button>
      )}

      {measureMode && (
        <div className="area-hint measure-hint">
          <KindToggle kind={kind} setKind={setKind} />
          <span>
            Click to add points · double-click to finish
            {pointCount >= 2 ? ` · ${distanceText}` : ""}
          </span>
          <div className="area-hint-actions">
            <button className="area-btn primary" onClick={onFinish} disabled={pointCount < 2}>
              Finish
            </button>
            <button className="area-btn" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {hasResult && !measureMode && (
        <div className="area-card">
          <div className="area-card-head">
            <span>Distance</span>
            <button className="area-card-close" onClick={onClear} title="Clear">
              <CloseIcon />
            </button>
          </div>

          <KindToggle kind={kind} setKind={setKind} />

          <p className="area-card-value">{busy ? "Calculating…" : distanceText}</p>

          {warning && <p className="area-card-warn">{warning}</p>}

          <p className="area-card-foot">
            {pointCount} points · {kind === "sea" ? "sea route" : "straight-line (great circle)"}
          </p>
        </div>
      )}
    </>
  );
}
