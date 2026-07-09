import { useState } from "react";

const layerTree = {
  Atmosphere: [
    { key: "temperature", label: "Temperature", icon: "T" },
    { key: "wind", label: "Wind", icon: "W" },
    { key: "pressure", label: "Pressure", icon: "P" },
    { key: "humidity", label: "Humidity", icon: "H" },
    { key: "clouds", label: "Clouds", icon: "C" },
    { key: "radiation", label: "Radiation", icon: "R" }
  ],
  Precipitation: [
    { key: "rain", label: "Rain", icon: "R" },
    { key: "snow", label: "Snow", icon: "S" },
    { key: "hail", label: "Hail", icon: "H" }
  ],
  Ocean: [
    { key: "sst", label: "Sea Surface Temperature", icon: "SST" },
    { key: "seaice", label: "Sea Ice", icon: "I" },
    { key: "currents", label: "Currents", icon: "U/V" },
    { key: "waves", label: "Waves", icon: "~" },
    { key: "seastate", label: "Sea State", icon: "SS" }
  ],
  Land: [
    { key: "terrain", label: "Terrain", icon: "H" },
    { key: "vegetation", label: "Vegetation", icon: "V" },
    { key: "soil", label: "Soil", icon: "S" },
    { key: "landuse", label: "Land Use", icon: "L" }
  ]
};

export default function Sidebar({
  selectedLayer,
  activeLayers,
  toggleLayer,
  deselectAll,
  layersInfo,
  open = true,
  setOpen,
  datasetPath,
  setDatasetPath,
  onLoadDataset,
  onUploadZip,
  loading,
  metadata,
  opacity,
  setOpacity
}) {
  const hasActive = (activeLayers?.length || 0) > 0;
  const [loaderOpen, setLoaderOpen] = useState(true);

  return (
    <>
      {!open && (
        <button
          className="sidebar-expand"
          onClick={() => setOpen(true)}
          title="Show layers panel"
          aria-label="Show layers panel"
        >
          <Chevron dir="left" />
        </button>
      )}

      <aside className={`sidebar ${open ? "" : "collapsed"}`}>
        <div className="brand">
          <div className="brand-text">
            <div className="brand-title">Weather</div>
            <div className="brand-subtitle">Layers</div>
          </div>
          <button
            className="sidebar-toggle"
            onClick={() => setOpen(false)}
            title="Collapse layers panel"
            aria-label="Collapse layers panel"
          >
            <Chevron dir="right" />
          </button>
        </div>

        <div className={`data-loader ${loaderOpen ? "open" : "collapsed"}`}>
          <button
            className="loader-head"
            onClick={() => setLoaderOpen(!loaderOpen)}
            aria-expanded={loaderOpen}
            title={loaderOpen ? "Collapse dataset" : "Expand dataset"}
          >
            <span className="loader-label">Dataset</span>
            <Caret />
          </button>

          {loaderOpen && (
            <div className="loader-body">
              <input
                className="loader-input"
                value={datasetPath}
                onChange={(e) => setDatasetPath(e.target.value)}
                placeholder="data/wrf/wrfout_d01_2025-07-01_00_00_00"
              />
              <div className="loader-actions">
                <button
                  className="loader-load"
                  onClick={onLoadDataset}
                  disabled={loading}
                >
                  {loading ? "Loading..." : "Load Path"}
                </button>
                <label className="loader-upload">
                  Upload ZIP
                  <input
                    type="file"
                    accept=".zip"
                    style={{ display: "none" }}
                    onChange={onUploadZip}
                  />
                </label>
              </div>
            </div>
          )}
        </div>

        <div className="sidebar-meta">
          <div className={`sidebar-status ${metadata ? "ready" : ""}`}>
            <span className="status-dot" />
            {metadata ? "Dataset loaded" : "No dataset"}
          </div>

          <div className="sidebar-opacity">
            <label>Opacity {Math.round((opacity ?? 0) * 100)}%</label>
            <input
              type="range"
              min="0.1"
              max="1"
              step="0.05"
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="layers-bar">
          <span className="layers-bar-title">Layers</span>
          <button
            className="deselect-btn"
            onClick={deselectAll}
            disabled={!hasActive}
            title="Turn off all layers"
          >
            Deselect Layer
          </button>
        </div>

      {Object.entries(layerTree).map(([domain, layers]) => (
        <section className="domain" key={domain}>
          <div className="domain-title">{domain}</div>

          {layers.map((layer) => {
            const info = findLayerInfo(layersInfo, layer.key);
            const available = info?.available !== false;
            const active = activeLayers?.includes(layer.key);

            return (
              <button
                key={layer.key}
                className={`layer-btn ${selectedLayer === layer.key ? "selected" : ""} ${active ? "active" : ""} ${!available ? "missing" : ""}`}
                onClick={() => toggleLayer(layer.key)}
                title={formatLayerTitle(info)}
              >
                <span className="layer-icon">{layer.icon}</span>
                <span className="layer-text">
                  <strong>{layer.label}</strong>
                  <small>{available ? formatVariables(info) : "Variables not found"}</small>
                </span>
                <span className="layer-state">{active ? "ON" : "OFF"}</span>
              </button>
            );
          })}
        </section>
      ))}

        <div className="sidebar-note">
          Layers follow the Atmosphere, Precipitation, Ocean, and Land WRF variable taxonomy.
        </div>
      </aside>
    </>
  );
}

function Caret() {
  return (
    <svg
      className="loader-caret"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function Chevron({ dir = "left" }) {
  return (
    <svg
      className="chevron-icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={dir === "left" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"} />
    </svg>
  );
}

function findLayerInfo(info, key) {
  if (!info) return null;

  for (const domain of Object.values(info)) {
    if (domain[key]) return domain[key];
  }

  return null;
}

function formatVariables(info) {
  return info?.variables?.join(", ") || "Combined weather layer";
}

function formatLayerTitle(info) {
  return info?.variables ? `Uses ${info.variables.join(", ")}` : "Render layer";
}
