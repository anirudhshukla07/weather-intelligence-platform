import { useEffect, useRef, useState } from "react";

import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Timeline from "../components/Timeline";
import AssistantPanel from "../components/AssistantPanel";
import AreaPanel from "../components/AreaPanel";
import MeasurePanel from "../components/MeasurePanel";
import MapView from "../map/MapView";
import api, { API_BASE } from "../services/api";

// Great-circle distance (metres) along a path of {lat,lng} points.
function measureMeters(points) {
  if (!points || points.length < 2) return 0;
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    let dLng = b.lng - a.lng;
    dLng = ((((dLng + 180) % 360) + 360) % 360) - 180; // shortest way around
    const dLat = b.lat - a.lat;
    const h =
      Math.sin(toRad(dLat) / 2) ** 2 +
      Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(toRad(dLng) / 2) ** 2;
    total += 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  return total;
}

function formatDistance(m) {
  if (m < 1000) return `${m.toFixed(0)} m`;
  if (m < 100000) return `${(m / 1000).toFixed(2)} km`;
  return `${(m / 1000).toFixed(1)} km`;
}

export default function Dashboard() {
  const [selectedLayer, setSelectedLayer] = useState("temperature");
  const [activeLayers, setActiveLayers] = useState(["temperature"]);
  const [renderedLayer, setRenderedLayer] = useState(null);

  const [timestep, setTimestep] = useState(0);
  const [timestamps, setTimestamps] = useState([]);

  const [isPlaying, setIsPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [speed, setSpeed] = useState(1);

  const [sidebarOpen, setSidebarOpen] = useState(true);

  const [opacity, setOpacity] = useState(0.7);
  const [datasetPath, setDatasetPath] = useState(
    "data/wrf/wrfout_d01_2025-07-01_00_00_00"
  );

  const [metadata, setMetadata] = useState(null);
  const [layersInfo, setLayersInfo] = useState(null);
  const [stats, setStats] = useState(null);
  const [pointData, setPointData] = useState(null);
  const [markerPoint, setMarkerPoint] = useState(null);

  const [loading, setLoading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");

  const [theme, setTheme] = useState(
    () => localStorage.getItem("wrf-theme") || "light"
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("wrf-theme", theme);
  }, [theme]);

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  // Map instance (for assistant-driven zoom / pin)
  const mapRef = useRef(null);

  // Polygon area selection
  const [areaMode, setAreaMode] = useState(false);
  const [areaPoints, setAreaPoints] = useState([]);
  const [areaPolygon, setAreaPolygon] = useState(null);
  const [areaStats, setAreaStats] = useState(null);
  const [areaBusy, setAreaBusy] = useState(false);

  // Pin (point) mode
  const [pinMode, setPinMode] = useState(false);

  // Distance measuring
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState([]);
  const [measureKind, setMeasureKind] = useState("air"); // "air" | "sea"
  const [seaRoute, setSeaRoute] = useState(null);
  const [seaInfo, setSeaInfo] = useState(null); // { distance_km, warning } | { error }
  const [seaBusy, setSeaBusy] = useState(false);

  // Per-layer animation overlays (currently: wind particle flow)
  const [animateLayer, setAnimateLayer] = useState(true);

  // Forecast alerts
  const [alerts, setAlerts] = useState([]);
  const [alertSeverity, setAlertSeverity] = useState({});
  const [alertMarker, setAlertMarker] = useState(null);

  // Basemap (street / satellite)
  const [basemap, setBasemap] = useState("street");
  const toggleBasemap = () =>
    setBasemap((b) => (b === "street" ? "satellite" : "street"));

  useEffect(() => {
    api.get("/layers")
      .then((res) => setLayersInfo(res.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!metadata) return;

    if (!selectedLayer) {
      setRenderedLayer(null);
      setStats(null);
      setPointData(null);
      setMarkerPoint(null);
      return;
    }

    renderSelectedLayer(selectedLayer);
    setPointData(null);
    setMarkerPoint(null);
  }, [selectedLayer, timestep]);

  // Self-paced animation: wait until the current frame is rendered, dwell a
  // moment, then advance one step. Re-running on `rendering` keeps playback in
  // lock-step with the backend so frames are never skipped.
  useEffect(() => {
    if (!isPlaying || rendering) return;
    if (timestamps.length < 2) return;

    const dwell = 900 / speed;

    const id = setTimeout(() => {
      setTimestep((ts) => {
        const next = ts + 1;

        if (next >= timestamps.length) {
          if (loop) return 0;
          setIsPlaying(false);
          return ts;
        }

        return next;
      });
    }, dwell);

    return () => clearTimeout(id);
  }, [isPlaying, rendering, timestep, timestamps.length, loop, speed]);

  // Stop playback whenever a fresh dataset is loaded.
  useEffect(() => {
    setIsPlaying(false);
  }, [metadata]);

  // Recenter the map on the default India view.
  function resetView() {
    if (mapRef.current) {
      mapRef.current.flyTo([20, 78], 4, { animate: true });
    }
  }

  // Scan the freshly-loaded forecast for weather alerts.
  useEffect(() => {
    setAlertMarker(null);
    if (!metadata) {
      setAlerts([]);
      setAlertSeverity({});
      return;
    }
    let cancelled = false;
    api
      .get("/alerts")
      .then((res) => {
        if (cancelled) return;
        setAlerts(res.data.alerts || []);
        setAlertSeverity(res.data.by_timestep || {});
      })
      .catch(() => {
        if (cancelled) return;
        setAlerts([]);
        setAlertSeverity({});
      });
    return () => {
      cancelled = true;
    };
  }, [metadata]);

  // Fly the map to a place picked from the search box. Use its bounding box
  // when available (good framing for a city/region), else zoom to the point.
  function flyToPlace(place) {
    if (!place || !mapRef.current) return;
    const map = mapRef.current;
    const { lat, lon, bbox } = place;
    if (bbox) {
      map.flyToBounds(
        [
          [bbox.south, bbox.west],
          [bbox.north, bbox.east]
        ],
        { padding: [40, 40], animate: true, maxZoom: 12 }
      );
    } else if (typeof lat === "number" && typeof lon === "number") {
      map.flyTo([lat, lon], Math.max(map.getZoom(), 9), { animate: true });
    }
  }

  function jumpToAlert(a) {
    if (!a) return;
    setIsPlaying(false);
    const max = Math.max(0, (timestamps.length || 1) - 1);
    setTimestep(Math.min(max, Math.max(0, a.peak_timestep ?? 0)));
    if (typeof a.lat === "number" && typeof a.lon === "number") {
      setAlertMarker(a); // drop a marker pointing at the alert location
      if (mapRef.current) {
        mapRef.current.flyTo([a.lat, a.lon], Math.max(mapRef.current.getZoom(), 6), {
          animate: true
        });
      }
    }
  }

  // Fetch the sea route whenever measuring in "sea" mode with ≥2 points.
  useEffect(() => {
    if (measureKind !== "sea" || measurePoints.length < 2) {
      setSeaRoute(null);
      setSeaInfo(null);
      setSeaBusy(false);
      return;
    }

    let cancelled = false;
    const normLon = (lng) => ((((lng + 180) % 360) + 360) % 360) - 180;
    const pts = measurePoints.map((p) => [p.lat, normLon(p.lng)]);

    setSeaBusy(true);
    api
      .post("/searoute", { points: pts })
      .then((res) => {
        if (cancelled) return;
        const route = res.data.route;
        setSeaRoute(Array.isArray(route) && route.length >= 2 ? route : null);
        setSeaInfo({ distance_km: res.data.distance_km, warning: res.data.warning });
      })
      .catch((err) => {
        if (cancelled) return;
        setSeaRoute(null);
        setSeaInfo({ error: err?.response?.data?.detail || "Sea route failed." });
      })
      .finally(() => {
        if (!cancelled) setSeaBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [measurePoints, measureKind]);

  // Let Leaflet refill tiles after the panel slide finishes resizing the map.
  useEffect(() => {
    const id = setTimeout(
      () => window.dispatchEvent(new Event("resize")),
      260
    );
    return () => clearTimeout(id);
  }, [sidebarOpen]);

  async function refreshLayers() {
    const layers = await api.get("/layers");
    setLayersInfo(layers.data);
  }

  async function onLoadDataset() {
    setLoading(true);
    setError("");

    try {
      const res = await api.post("/load", {
        file_path: datasetPath
      });

      setMetadata(res.data);
      setTimestamps(res.data.timestamps || []);
      setTimestep(0);

      await refreshLayers();
      await renderSelectedLayer(selectedLayer);
    } catch (err) {
      setError(err?.response?.data?.detail || "Dataset load failed.");
    } finally {
      setLoading(false);
    }
  }

  async function onUploadZip(e) {
    const file = e.target.files[0];

    if (!file) return;

    setLoading(true);
    setError("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await api.post("/upload-zip", formData, {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      });

      setMetadata(res.data);
      setTimestamps(res.data.timestamps || []);
      setTimestep(0);
      setDatasetPath(res.data.file);

      await refreshLayers();
      await renderSelectedLayer(selectedLayer);
    } catch (err) {
      setError(err?.response?.data?.detail || "ZIP upload failed.");
    } finally {
      setLoading(false);
    }
  }

  async function renderSelectedLayer(layerKey) {
    setRendering(true);
    setError("");

    try {
      const res = await api.get(`/render/${layerKey}`, {
        params: {
          timestep,
          dark: basemap === "satellite" || theme === "dark",
          // Clouds swap to the white/grey density overlay when animation is on.
          density: layerKey === "clouds" && animateLayer
        }
      });

      setRenderedLayer(res.data);

      const stat = await api.get(`/statistics/${layerKey}`, {
        params: { timestep }
      });

      setStats(stat.data);
    } catch (err) {
      setRenderedLayer(null);
      setStats(null);
      setError(
        err?.response?.data?.detail ||
        "Layer rendering failed. Load dataset first."
      );
    } finally {
      setRendering(false);
    }
  }

  // Re-render clouds when the animation toggle (density vs colormap) or the
  // background (which tints the density overlay) changes.
  useEffect(() => {
    if (selectedLayer === "clouds" && metadata) renderSelectedLayer("clouds");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap, theme, animateLayer]);

  function toggleLayer(layerKey) {
    const isOn = activeLayers.includes(layerKey);
    setActiveLayers(isOn ? [] : [layerKey]);
    setSelectedLayer(isOn ? "" : layerKey);
  }

  function deselectAll() {
    setActiveLayers([]);
    setSelectedLayer("");
  }

  // ---- Polygon area selection ----------------------------------------

  function startArea() {
    // Tools are mutually exclusive — clear the pin and measure tool.
    setPinMode(false);
    setMarkerPoint(null);
    setPointData(null);
    setMeasureMode(false);
    setMeasurePoints([]);

    setAreaStats(null);
    setAreaPolygon(null);
    setAreaPoints([]);
    setAreaMode(true);
  }

  // ---- Distance measuring --------------------------------------------

  function startMeasure() {
    setPinMode(false);
    setMarkerPoint(null);
    setPointData(null);
    clearArea();
    setMeasurePoints([]);
    setMeasureMode(true);
  }

  function finishMeasure() {
    setMeasureMode(false);
  }

  function cancelMeasure() {
    setMeasureMode(false);
    setMeasurePoints([]);
  }

  function clearMeasure() {
    setMeasureMode(false);
    setMeasurePoints([]);
  }

  function togglePinMode() {
    setPinMode((on) => {
      if (!on) {
        // Turning pin mode on — leave the other tools.
        setAreaMode(false);
        setAreaPoints([]);
        setMeasureMode(false);
        setMeasurePoints([]);
      } else {
        // Turning pin mode off — remove the pin from the map.
        setMarkerPoint(null);
        setPointData(null);
      }
      return !on;
    });
  }

  function cancelArea() {
    setAreaMode(false);
    setAreaPoints([]);
  }

  function clearArea() {
    setAreaMode(false);
    setAreaPoints([]);
    setAreaPolygon(null);
    setAreaStats(null);
  }

  function finishArea() {
    if (areaPoints.length < 3) return;
    // Commit the polygon — the effect below computes (and re-computes) the stats.
    setAreaPolygon(areaPoints);
    setAreaMode(false);
  }

  // Recompute area statistics whenever the polygon, layer, or timestep changes.
  useEffect(() => {
    if (!areaPolygon || areaPolygon.length < 3) return;

    if (!selectedLayer) {
      setAreaBusy(false);
      setAreaStats({
        label: "No layer",
        is_empty: true,
        display_text: "Turn on a layer to query the area"
      });
      return;
    }

    let cancelled = false;
    const normLon = (lng) => ((((lng + 180) % 360) + 360) % 360) - 180;
    const polygon = areaPolygon.map((p) => [p.lat, normLon(p.lng)]);

    setAreaBusy(true);
    api
      .post("/area-statistics", { layer: selectedLayer, timestep, polygon })
      .then((res) => {
        if (!cancelled) setAreaStats(res.data);
      })
      .catch((err) => {
        if (!cancelled)
          setAreaStats({
            label: layerLabel(selectedLayer),
            is_empty: true,
            display_text: err?.response?.data?.detail || "Area query failed."
          });
      })
      .finally(() => {
        if (!cancelled) setAreaBusy(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaPolygon, selectedLayer, timestep]);

  function layerLabel(key) {
    if (!layersInfo) return key;
    for (const domain of Object.values(layersInfo)) {
      if (domain[key]) return domain[key].label;
    }
    return key;
  }

  // ---- Assistant -----------------------------------------------------

  async function dropPin(lat, lon) {
    // Tools are mutually exclusive — clear area and measure.
    clearArea();
    setMeasureMode(false);
    setMeasurePoints([]);

    const latlng = { lat, lng: lon };
    setMarkerPoint(latlng);

    if (mapRef.current) {
      mapRef.current.flyTo([lat, lon], Math.max(mapRef.current.getZoom(), 6), {
        animate: true
      });
    }

    if (!selectedLayer) return;

    try {
      const res = await api.post("/extract", {
        layer: selectedLayer,
        lat,
        lon,
        timestep
      });
      setPointData(res.data);
    } catch {
      /* ignore extraction failure for assistant pins */
    }
  }

  function runActions(actions) {
    for (const action of actions || []) {
      const p = action.params || {};

      if (action.type === "set_layers") {
        const layers = Array.isArray(p.layers)
          ? p.layers
          : p.layers
          ? [p.layers]
          : [];
        if (layers.length) {
          setActiveLayers([layers[0]]);
          setSelectedLayer(layers[0]);
        }
      } else if (action.type === "deselect_all_layers") {
        deselectAll();
      } else if (action.type === "set_time") {
        if (typeof p.index === "number") {
          const max = Math.max(0, (timestamps.length || 1) - 1);
          setIsPlaying(false);
          setTimestep(Math.min(max, Math.max(0, p.index)));
        }
      } else if (action.type === "zoom_to") {
        if (mapRef.current && [p.south, p.west, p.north, p.east].every((n) => typeof n === "number")) {
          mapRef.current.flyToBounds(
            [[p.south, p.west], [p.north, p.east]],
            { animate: true, padding: [30, 30] }
          );
        }
      } else if (action.type === "drop_pin") {
        if (typeof p.lat === "number" && typeof p.lon === "number") {
          dropPin(p.lat, p.lon);
        }
      } else if (action.type === "set_opacity") {
        if (typeof p.opacity === "number") {
          setOpacity(Math.min(1, Math.max(0.1, p.opacity)));
        }
      }
    }
  }

  function assistantContext() {
    const layers = layersInfo
      ? Object.values(layersInfo).flatMap((domain) =>
          Object.entries(domain).map(([key, cfg]) => ({
            key,
            label: cfg.label
          }))
        )
      : [];

    const normLon = (lng) => ((((lng + 180) % 360) + 360) % 360) - 180;

    return {
      layers,
      timestamps,
      current_layer: selectedLayer,
      current_timestep: timestep,
      bounds: metadata?.bounds,
      pin: markerPoint
        ? {
            lat: Number(markerPoint.lat.toFixed(4)),
            lon: Number(normLon(markerPoint.lng).toFixed(4))
          }
        : null
    };
  }

  // Streams the assistant reply token-by-token via NDJSON; runs any actions.
  async function streamAssistant(text, onDelta, onReplace) {
    const res = await fetch(`${API_BASE}/assistant-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, context: assistantContext() })
    });

    if (!res.ok || !res.body) {
      let detail = "Assistant request failed.";
      try {
        detail = (await res.json())?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;

        let obj;
        try {
          obj = JSON.parse(line);
        } catch {
          continue;
        }

        if (obj.type === "delta") onDelta(obj.text);
        else if (obj.type === "replace") onReplace(obj.text || "");
        else if (obj.type === "actions") runActions(obj.actions);
        else if (obj.type === "error") throw new Error(obj.detail);
      }
    }
  }

  // Distance label for the measure tool (air = client-side, sea = backend).
  let measureText = "";
  if (measurePoints.length >= 2) {
    if (measureKind === "sea") {
      measureText = seaBusy
        ? "…"
        : seaInfo?.distance_km != null
        ? `${seaInfo.distance_km} km`
        : "—";
    } else {
      measureText = formatDistance(measureMeters(measurePoints));
    }
  }
  const measureWarning =
    measureKind === "sea" ? seaInfo?.warning || seaInfo?.error || "" : "";

  return (
    <div className="app-shell">
      <TopBar
        theme={theme}
        toggleTheme={toggleTheme}
        basemap={basemap}
        toggleBasemap={toggleBasemap}
        alerts={alerts}
        onJumpAlert={jumpToAlert}
        onCloseAlerts={() => setAlertMarker(null)}
        onPlaceSelect={flyToPlace}
      />

      <div className="app-body">
        <Sidebar
          selectedLayer={selectedLayer}
          setSelectedLayer={setSelectedLayer}
          activeLayers={activeLayers}
          toggleLayer={toggleLayer}
          deselectAll={deselectAll}
          layersInfo={layersInfo}
          open={sidebarOpen}
          setOpen={setSidebarOpen}
          datasetPath={datasetPath}
          setDatasetPath={setDatasetPath}
          onLoadDataset={onLoadDataset}
          onUploadZip={onUploadZip}
          loading={loading}
          metadata={metadata}
          opacity={opacity}
          setOpacity={setOpacity}
        />

        <main className="main-area">
        <MapView
          selectedLayer={selectedLayer}
          timestep={timestep}
          renderedLayer={renderedLayer}
          opacity={opacity}
          markerPoint={markerPoint}
          setMarkerPoint={setMarkerPoint}
          pointData={pointData}
          setPointData={setPointData}
          stats={stats}
          error={error}
          setError={setError}
          onMapReady={(map) => { mapRef.current = map; }}
          pinMode={pinMode}
          areaMode={areaMode}
          areaPoints={areaPoints}
          setAreaPoints={setAreaPoints}
          onFinishArea={finishArea}
          onClearArea={clearArea}
          areaPolygon={areaPolygon}
          basemap={basemap}
          measureMode={measureMode}
          measurePoints={measurePoints}
          setMeasurePoints={setMeasurePoints}
          onFinishMeasure={finishMeasure}
          measureText={measureText}
          measureRoute={measureKind === "sea" ? seaRoute : null}
          alertMarker={alertMarker}
          onClearAlertMarker={() => setAlertMarker(null)}
          animateLayer={animateLayer}
          darkBackground={basemap === "satellite" || theme === "dark"}
        />

        {["wind", "rain", "clouds"].includes(selectedLayer) && (
          <button
            className={`anim-fab ${animateLayer ? "active" : ""}`}
            onClick={() => setAnimateLayer((a) => !a)}
            title={
              animateLayer
                ? `Turn ${selectedLayer} animation off`
                : `Turn ${selectedLayer} animation on`
            }
            aria-label="Toggle layer animation"
          >
            {selectedLayer === "clouds" ? (
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 17a4 4 0 0 1-.8-7.9A5 5 0 0 1 15 8a3.5 3.5 0 0 1 1 6.8" />
                <path d="M8 17h9" />
              </svg>
            ) : selectedLayer === "rain" ? (
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 14a5 5 0 0 1-1-9.9A6 6 0 0 1 17 5a4 4 0 0 1 1 7.9" />
                <path d="M8 19l-1 2M12 19l-1 2M16 19l-1 2" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 8h11a3 3 0 1 0-3-3" />
                <path d="M3 12h15a3.5 3.5 0 1 1-3 3.4" />
                <path d="M3 16h7" />
              </svg>
            )}
          </button>
        )}

        <button
          className="reset-fab"
          onClick={resetView}
          title="Reset view to India"
          aria-label="Reset view to India"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 11l9-8 9 8" />
            <path d="M5 10v10h14V10" />
            <path d="M9 20v-6h6v6" />
          </svg>
        </button>

        <button
          className={`pin-fab ${pinMode ? "active" : ""}`}
          onClick={togglePinMode}
          disabled={!metadata}
          title={pinMode ? "Pin tool on — click the map" : "Drop a pin"}
          aria-label="Drop a pin"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 21s-6-5.686-6-10a6 6 0 1 1 12 0c0 4.314-6 10-6 10z" />
            <circle cx="12" cy="11" r="2.2" />
          </svg>
        </button>

        <MeasurePanel
          measureMode={measureMode}
          onStart={startMeasure}
          onFinish={finishMeasure}
          onCancel={cancelMeasure}
          onClear={clearMeasure}
          pointCount={measurePoints.length}
          distanceText={measureText}
          warning={measureWarning}
          kind={measureKind}
          setKind={setMeasureKind}
          busy={seaBusy}
          hasResult={!measureMode && measurePoints.length >= 2}
          disabled={!metadata}
        />

        <AreaPanel
          areaMode={areaMode}
          onStart={startArea}
          onFinish={finishArea}
          onCancel={cancelArea}
          onClear={clearArea}
          pointCount={areaPoints.length}
          areaStats={areaStats}
          areaBusy={areaBusy}
          disabled={!metadata}
        />

        <AssistantPanel streamMessage={streamAssistant} disabled={!metadata} />

        {rendering && (
          <div className="loading-overlay">
            Rendering WRF layer...
          </div>
        )}
        </main>
      </div>

      <Timeline
        timestamps={timestamps}
        timestep={timestep}
        setTimestep={setTimestep}
        isPlaying={isPlaying}
        setIsPlaying={setIsPlaying}
        loop={loop}
        setLoop={setLoop}
        speed={speed}
        setSpeed={setSpeed}
        rendering={rendering}
        hasDataset={!!metadata}
        alertSeverity={alertSeverity}
      />
    </div>
  );
}