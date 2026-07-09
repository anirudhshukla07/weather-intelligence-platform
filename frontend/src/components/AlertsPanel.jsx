import { useState } from "react";

const SEV_RANK = { red: 3, orange: 2, yellow: 1 };
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtTime(s) {
  const m = String(s || "").match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return s || "";
  return `${MON[+m[2] - 1]} ${+m[3]}, ${m[4]}:${m[5]}`;
}

export default function AlertsPanel({ alerts = [], onJump, onClose }) {
  const [open, setOpen] = useState(false);
  const count = alerts.length;
  const worst = alerts.reduce(
    (w, a) => (SEV_RANK[a.severity] > SEV_RANK[w] ? a.severity : w),
    "yellow"
  );

  // Close the panel and clear the alert pin dropped on the map.
  function close() {
    setOpen(false);
    onClose && onClose();
  }

  return (
    <div className="alerts-wrap">
      <button
        className="alerts-bell"
        onClick={() => (open ? close() : setOpen(true))}
        title="Weather alerts"
        aria-label="Weather alerts"
      >
        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {count > 0 && <span className={`alerts-badge sev-${worst}`}>{count}</span>}
      </button>

      {open && (
        <div className="alerts-dropdown">
          <div className="alerts-head">
            Forecast alerts
            <button className="alerts-close" onClick={close} aria-label="Close">
              ✕
            </button>
          </div>

          {count === 0 ? (
            <div className="alerts-empty">No weather alerts in this forecast.</div>
          ) : (
            <div className="alerts-list">
              {alerts.map((a, i) => (
                <button
                  key={i}
                  className="alert-row"
                  onClick={() => {
                    onJump && onJump(a);
                    setOpen(false);
                  }}
                  title="Jump to the peak time and location"
                >
                  <span className={`alert-dot sev-${a.severity}`} />
                  <span className="alert-body">
                    <strong>{a.label}</strong>
                    <small>
                      {a.text} · peak {fmtTime(a.peak_time)} · {a.frame_count}/
                      {a.total_frames} frames
                    </small>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
