// Central place for every external/online endpoint the frontend talks to.
// All values come from Vite env vars (frontend/.env) with safe fallbacks, so
// changing the .env (then rebuilding / restarting the dev server) is enough.
const env = import.meta.env;

// Backend API (FastAPI) base URL.
export const API_BASE = env.VITE_API_BASE || "http://localhost:8000";

// Online map tile providers.
export const TILES = {
  street: {
    url:
      env.VITE_TILE_STREET_URL ||
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: env.VITE_TILE_STREET_ATTRIBUTION || "OpenStreetMap"
  },
  satellite: {
    url:
      env.VITE_TILE_SATELLITE_URL ||
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution:
      env.VITE_TILE_SATELLITE_ATTRIBUTION ||
      "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics"
  }
};
