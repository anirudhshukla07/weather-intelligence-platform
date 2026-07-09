import {
  MapContainer,
  TileLayer,
  ImageOverlay,
  useMapEvents,
  Marker,
  Popup,
  Polygon,
  Polyline,
  CircleMarker,
  Tooltip,
  useMap
} from "react-leaflet";

import { useEffect } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// A glowing, pulsing alert pin (animated radar ping around a cored dot).
function alertIcon(color) {
  return L.divIcon({
    className: "alert-pin-wrap",
    html: `<span class="alert-pin" style="--c:${color}"><i class="alert-pin-core"></i></span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12]
  });
}

import api from "../services/api";
import { TILES } from "../config";
import Legend from "../components/Legend";
import InfoPanel from "../components/InfoPanel";
import WindAnimation from "./WindAnimation";
import RainAnimation from "./RainAnimation";

function FitLayerBounds({ bounds }) {
  const map = useMap();

  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, {
        padding: [20, 20],
        animate: false
      });
    }
  }, [bounds, map]);

  return null;
}

// Exposes the Leaflet map instance to the parent (for assistant-driven
// zoom / pin) and toggles double-click zoom while drawing an area.
function MapController({ onReady, areaMode }) {
  const map = useMap();

  useEffect(() => {
    if (onReady) onReady(map);
  }, [map, onReady]);

  useEffect(() => {
    if (areaMode) map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
  }, [map, areaMode]);

  return null;
}

// Map any wrapped-copy longitude back to the canonical -180..180 range so
// the same point always queries the same data, no matter which world copy.
function normalizeLon(lng) {
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

function MapClicks({
  selectedLayer,
  timestep,
  setPointData,
  setMarkerPoint,
  setError,
  pinMode,
  areaMode,
  areaPoints,
  setAreaPoints,
  onFinishArea,
  onClearArea,
  measureMode,
  measurePoints,
  setMeasurePoints,
  onFinishMeasure
}) {
  useMapEvents({
    async click(e) {
      // Drawing mode: collect polygon vertices instead of extracting.
      if (areaMode) {
        setAreaPoints([...areaPoints, e.latlng]);
        return;
      }

      // Measuring: collect path points.
      if (measureMode) {
        setMeasurePoints([...measurePoints, e.latlng]);
        return;
      }

      // Pins only drop when the pin tool is selected.
      if (!pinMode) return;

      // Dropping a pin clears any drawn area (mutually exclusive).
      if (onClearArea) onClearArea();
      setMarkerPoint(e.latlng);

      if (!selectedLayer) return;

      try {
        const res = await api.post("/extract", {
          layer: selectedLayer,
          lat: e.latlng.lat,
          lon: normalizeLon(e.latlng.lng),
          timestep
        });

        setPointData(res.data);
        setError("");
      } catch (err) {
        setPointData(null);
        setError(
          err?.response?.data?.detail ||
          "Point extraction failed. Load dataset first."
        );
      }
    },
    dblclick() {
      if (areaMode) onFinishArea();
      else if (measureMode) onFinishMeasure();
    }
  });

  return null;
}

export default function MapView({
  selectedLayer,
  timestep,
  renderedLayer,
  opacity,
  markerPoint,
  setMarkerPoint,
  pointData,
  setPointData,
  stats,
  error,
  setError,
  onMapReady,
  areaMode,
  areaPoints,
  setAreaPoints,
  onFinishArea,
  onClearArea,
  areaPolygon,
  pinMode,
  basemap = "street",
  measureMode,
  measurePoints = [],
  setMeasurePoints,
  onFinishMeasure,
  measureText,
  measureRoute,
  alertMarker,
  onClearAlertMarker,
  animateLayer = true,
  darkBackground = true
}) {
  const SEV_COLOR = { red: "#dc2626", orange: "#f97316", yellow: "#eab308" };
  const picking = pinMode || areaMode || measureMode;

  return (
    <div className={`map-wrap basemap-${basemap} ${picking ? "picking" : ""}`}>
      <InfoPanel
        selectedLayer={selectedLayer}
        renderedLayer={renderedLayer}
        pointData={pointData}
        stats={stats}
        error={error}
      />

      <MapContainer
        center={[20, 78]}
        zoom={4}
        minZoom={2}
        maxBounds={[[-90, -180], [90, 180]]}
        maxBoundsViscosity={1.0}
        worldCopyJump={false}
        zoomControl={false}
        attributionControl={false}
        className="leaflet-map"
      >
        <MapController onReady={onMapReady} areaMode={areaMode} />

        {basemap === "satellite" ? (
          <TileLayer
            attribution={TILES.satellite.attribution}
            noWrap={true}
            bounds={[[-90, -180], [90, 180]]}
            url={TILES.satellite.url}
          />
        ) : (
          <TileLayer
            attribution={TILES.street.attribution}
            noWrap={true}
            bounds={[[-90, -180], [90, 180]]}
            url={TILES.street.url}
          />
        )}

        {renderedLayer && (
          <>
            <FitLayerBounds bounds={renderedLayer.bounds} />

            <ImageOverlay
              url={renderedLayer.image_url}
              bounds={renderedLayer.bounds}
              opacity={opacity}
              interactive={false}
            />
          </>
        )}

        <WindAnimation
          active={selectedLayer === "wind" && animateLayer}
          timestep={timestep}
          dark={darkBackground}
        />

        <RainAnimation
          active={selectedLayer === "rain" && animateLayer}
          timestep={timestep}
          dark={darkBackground}
        />

        <MapClicks
          selectedLayer={selectedLayer}
          timestep={timestep}
          setPointData={setPointData}
          setMarkerPoint={setMarkerPoint}
          setError={setError}
          pinMode={pinMode}
          areaMode={areaMode}
          areaPoints={areaPoints}
          setAreaPoints={setAreaPoints}
          onFinishArea={onFinishArea}
          onClearArea={onClearArea}
          measureMode={measureMode}
          measurePoints={measurePoints}
          setMeasurePoints={setMeasurePoints}
          onFinishMeasure={onFinishMeasure}
        />

        {/* Distance measuring path */}
        {measurePoints.length > 0 && (
          <>
            {measureRoute && measureRoute.length >= 2 ? (
              // Sea route — the water-following path from the backend
              <Polyline
                positions={measureRoute}
                pathOptions={{ color: "#0c5b95", weight: 3 }}
              />
            ) : (
              <Polyline
                positions={measurePoints}
                pathOptions={{ color: "#0c5b95", weight: 2.5, dashArray: "5 6" }}
              />
            )}
            {measurePoints.map((p, i) => (
              <CircleMarker
                key={i}
                center={p}
                radius={4}
                pathOptions={{ color: "#0c5b95", fillColor: "#fff", fillOpacity: 1 }}
              >
                {i === measurePoints.length - 1 && measurePoints.length >= 2 && (
                  <Tooltip permanent direction="top" offset={[0, -6]} className="measure-tip">
                    {measureText}
                  </Tooltip>
                )}
              </CircleMarker>
            ))}
          </>
        )}

        {/* Marker pointing at a clicked weather alert */}
        {alertMarker &&
          typeof alertMarker.lat === "number" &&
          typeof alertMarker.lon === "number" && (
            <Marker
              position={[alertMarker.lat, alertMarker.lon]}
              icon={alertIcon(SEV_COLOR[alertMarker.severity] || "#dc2626")}
              eventHandlers={{ click: () => onClearAlertMarker && onClearAlertMarker() }}
            >
              <Tooltip permanent direction="top" offset={[0, -16]} className="alert-marker-tip">
                <strong>{alertMarker.label}</strong>
                {alertMarker.text ? ` · ${alertMarker.text}` : ""}
              </Tooltip>
            </Marker>
          )}

        {/* In-progress polygon while drawing */}
        {areaMode && areaPoints.length > 0 && (
          <>
            <Polyline
              positions={areaPoints}
              pathOptions={{ color: "#1769aa", weight: 2, dashArray: "6 6" }}
            />
            {areaPoints.map((p, i) => (
              <CircleMarker
                key={i}
                center={p}
                radius={4}
                pathOptions={{ color: "#1769aa", fillColor: "#fff", fillOpacity: 1 }}
              />
            ))}
          </>
        )}

        {/* Committed selection polygon */}
        {areaPolygon && areaPolygon.length >= 3 && (
          <Polygon
            positions={areaPolygon}
            pathOptions={{
              color: "#0c5b95",
              weight: 2,
              fillColor: "#2b8fd4",
              fillOpacity: 0.18
            }}
          />
        )}

        {markerPoint && (
          <Marker position={markerPoint}>
            <Popup>
              <div style={{ minWidth: "230px" }}>
                <strong>{pointData?.label || selectedLayer}</strong>

                <br />
                Lat: {markerPoint.lat.toFixed(4)}
                <br />
                Lon: {markerPoint.lng.toFixed(4)}
                <hr />

                {pointData ? (
                  pointData.is_na ? (
                    <>
                      <strong>NA</strong>
                      <br />
                      {pointData.reason}
                    </>
                  ) : (
                    <>
                      <strong>{pointData.display_text}</strong>
                      <br />
                      Source: {pointData.source_variable}
                      <br />
                      Grid: {pointData.grid_x}, {pointData.grid_y}

                      {(pointData.layer === "wind" || pointData.layer === "currents") && (
                        <>
                          <hr />
                          U: {pointData.u_component.toFixed(3)} m/s
                          <br />
                          V: {pointData.v_component.toFixed(3)} m/s
                          <br />
                          Direction: {pointData.wind_direction.toFixed(1)}°
                          {" "}
                          ({pointData.wind_direction_label})
                        </>
                      )}

                      {pointData.layer === "temperature" && (
                        <>
                          <hr />
                          Kelvin: {pointData.temperature_k.toFixed(2)} K
                          <br />
                          Celsius: {pointData.temperature_c.toFixed(2)} °C
                        </>
                      )}
                    </>
                  )
                ) : (
                  "Click extraction pending..."
                )}
              </div>
            </Popup>
          </Marker>
        )}
      </MapContainer>

      <Legend renderedLayer={renderedLayer} />
    </div>
  );
}
