import Clock from "./Clock";
import AlertsPanel from "./AlertsPanel";
import PlaceSearch from "./PlaceSearch";

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

export default function TopBar({
  theme,
  toggleTheme,
  basemap,
  toggleBasemap,
  alerts,
  onJumpAlert,
  onCloseAlerts,
  onPlaceSelect
}) {
  const isDark = theme === "dark";

  return (
    <div className="topbar">
      <div className="topbar-title">
        <span className="eyebrow">Weather Application</span>
        <strong>Interactive Weather Layers</strong>
      </div>

      <PlaceSearch onSelect={onPlaceSelect} />

      <button
        className="topbar-basemap"
        onClick={toggleBasemap}
        title={basemap === "street" ? "Switch to satellite" : "Switch to map"}
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
        {basemap === "street" ? "Change to Satellite" : "Change to OSM"}
      </button>

      <Clock />

      <AlertsPanel alerts={alerts} onJump={onJumpAlert} onClose={onCloseAlerts} />

      <button
        className="theme-toggle"
        onClick={toggleTheme}
        title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      >
        {isDark ? <SunIcon /> : <MoonIcon />}
      </button>
    </div>
  );
}
