import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../config";

// Offline place search: the backend serves matches from a local GeoNames
// gazetteer (see backend/scripts/build_gazetteer.py). No external calls.

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

export default function PlaceSearch({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(-1);

  const wrapRef = useRef(null);
  const abortRef = useRef(null);

  // Debounced geocoding lookup as the user types.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) {
      setResults([]);
      setOpen(false);
      return;
    }

    const t = setTimeout(async () => {
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setBusy(true);
      try {
        const url = `${API_BASE}/geocode?limit=6&q=` + encodeURIComponent(q);
        const res = await fetch(url, { signal: ctrl.signal });
        if (!res.ok) throw new Error("geocode failed");
        const data = await res.json();
        setResults(Array.isArray(data.results) ? data.results : []);
        setActive(-1);
        setOpen(true);
      } catch (err) {
        if (err.name !== "AbortError") {
          setResults([]);
          setOpen(true);
        }
      } finally {
        setBusy(false);
      }
    }, 400);

    return () => clearTimeout(t);
  }, [query]);

  // Close the dropdown when clicking elsewhere.
  useEffect(() => {
    function onDocClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function choose(r) {
    if (!r) return;
    const lat = Number(r.lat);
    const lon = Number(r.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    onSelect && onSelect({ lat, lon, label: r.label, bbox: null });
    setQuery(r.name || (r.label || "").split(",")[0]);
    setOpen(false);
    setResults([]);
  }

  function onKeyDown(e) {
    if (!open || results.length === 0) {
      if (e.key === "Enter" && results.length > 0) choose(results[0]);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(results.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active >= 0 ? active : 0]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function clear() {
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  return (
    <div className="place-search" ref={wrapRef}>
      <div className="place-search-box">
        <span className="place-search-icon">
          <SearchIcon />
        </span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => results.length && setOpen(true)}
          placeholder="Search for a place…"
          aria-label="Search for a place"
        />
        {query && (
          <button className="place-search-clear" onClick={clear} aria-label="Clear search">
            ✕
          </button>
        )}
      </div>

      {open && (
        <div className="place-search-results">
          {busy && results.length === 0 ? (
            <div className="place-search-empty">Searching…</div>
          ) : results.length === 0 ? (
            <div className="place-search-empty">No places found.</div>
          ) : (
            results.map((r, i) => (
              <button
                key={i}
                className={`place-search-item ${i === active ? "active" : ""}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(r)}
                title={r.label}
              >
                <strong>{r.name || (r.label || "").split(",")[0]}</strong>
                <small>{r.label}</small>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
