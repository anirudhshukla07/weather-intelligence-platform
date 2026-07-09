import { useEffect, useState } from "react";

function ChevronToggle() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 15l6-6 6 6" />
    </svg>
  );
}

export default function InfoPanel({
  selectedLayer,
  renderedLayer,
  pointData,
  stats,
  error,
}) {
  const [open, setOpen] = useState(false);

  // Pop the panel open whenever the user inspects a new point.
  useEffect(() => {
    if (pointData) setOpen(true);
  }, [pointData]);

  const layerName = renderedLayer?.label || selectedLayer || "WRF Weather Map";
  const isNA = pointData?.is_na;
  const isVector =
    pointData?.layer === "wind" || pointData?.layer === "currents";

  return (
    <div className={`inspector ${open ? "open" : "collapsed"}`}>
      <button
        className="inspector-head"
        onClick={() => setOpen(!open)}
        title={open ? "Collapse panel" : "Expand panel"}
        aria-label={open ? "Collapse panel" : "Expand panel"}
      >
        <span className="ins-dot" />
        <span className="ins-titles">
          <span className="ins-eyebrow">Inspector</span>
          <strong>{layerName}</strong>
        </span>
        <span className="ins-chevron">
          <ChevronToggle />
        </span>
      </button>

      {open && (
        <div className="inspector-body">
          {renderedLayer && (
            <>
              <div className="info-row">
                <span>Source</span>
                <strong>{renderedLayer.source_variable}</strong>
              </div>

              <div className="info-row">
                <span>Meaning</span>
                <strong>{renderedLayer.legend_description}</strong>
              </div>

              <div className="info-row">
                <span>Range</span>
                <strong>
                  {renderedLayer.vmin?.toFixed?.(2)}
                  {" - "}
                  {renderedLayer.vmax?.toFixed?.(2)}
                  {" "}
                  {renderedLayer.unit}
                </strong>
              </div>
            </>
          )}

          {pointData &&
            (isNA ? (
              <div className="stats-box is-na">
                <h4>Clicked Point</h4>
                <span className="na-badge">No data here</span>
                <p>
                  {pointData.reason ||
                    "This point is outside the WRF dataset domain."}
                </p>
                {pointData.requested_lat != null && (
                  <p className="muted-fine">
                    {pointData.requested_lat.toFixed(4)},{" "}
                    {pointData.requested_lon.toFixed(4)}
                  </p>
                )}
              </div>
            ) : (
              <div className="stats-box">
                <h4>Clicked Point</h4>

                <p className="point-value">
                  <strong>{pointData.display_text}</strong>
                </p>

                <p>
                  Nearest: {pointData.nearest_lat?.toFixed?.(4)},{" "}
                  {pointData.nearest_lon?.toFixed?.(4)} · Grid {pointData.grid_x},{" "}
                  {pointData.grid_y}
                </p>

                {isVector && (
                  <p>
                    U {pointData.u_component?.toFixed?.(2)} · V{" "}
                    {pointData.v_component?.toFixed?.(2)} m/s ·{" "}
                    {pointData.wind_direction_deg?.toFixed?.(0)}°{" "}
                    ({pointData.wind_direction_label})
                  </p>
                )}

                {pointData.layer === "temperature" && (
                  <p>
                    {pointData.temperature_k?.toFixed?.(2)} K ·{" "}
                    {pointData.temperature_c?.toFixed?.(2)} °C
                  </p>
                )}
              </div>
            ))}

          {stats && (
            <div className="stats-box">
              <h4>Layer Statistics</h4>
              <div className="stat-grid">
                <span>Min<strong>{stats.min?.toFixed?.(3)}</strong></span>
                <span>Max<strong>{stats.max?.toFixed?.(3)}</strong></span>
                <span>Mean<strong>{stats.mean?.toFixed?.(3)}</strong></span>
                <span>Std<strong>{stats.std?.toFixed?.(3)}</strong></span>
              </div>
            </div>
          )}

          {error && <div className="error-box">{error}</div>}

          <p className="ins-hint">
            Click the map to inspect the nearest WRF grid point.
          </p>
        </div>
      )}
    </div>
  );
}
