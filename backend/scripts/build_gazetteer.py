"""One-time builder for the OFFLINE place-search gazetteer.

Downloads the free GeoNames `cities1000` dataset (~150k populated places
worldwide, CC-BY 4.0) plus the country and admin-region name tables, then
writes a compact TSV the backend loads for the /geocode endpoint.

    python scripts/build_gazetteer.py

This is the ONLY step that needs the internet. After it runs, place search
works fully offline. Re-run it to refresh the data.
"""

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
OUT = DATA_DIR / "geonames.tsv"

CITIES_URL = "https://download.geonames.org/export/dump/cities1000.zip"
COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"


def _fetch(url):
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "wrf-gis/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _country_names():
    """ISO country code -> full country name."""
    text = _fetch(COUNTRY_URL).decode("utf-8")
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) > 4 and cols[0]:
            out[cols[0]] = cols[4]
    return out


def _admin1_names():
    """'CC.admin1code' -> region name (e.g. 'IN.07' -> 'Delhi')."""
    text = _fetch(ADMIN1_URL).decode("utf-8")
    out = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0]:
            out[cols[0]] = cols[1]
    return out


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching reference tables…")
    countries = _country_names()
    admin1 = _admin1_names()

    print("Fetching cities1000…")
    zbytes = _fetch(CITIES_URL)
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        raw = zf.read("cities1000.txt").decode("utf-8")

    rows = 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for line in raw.splitlines():
            c = line.split("\t")
            if len(c) < 15:
                continue
            name, ascii_name = c[1], c[2]
            lat, lon = c[4], c[5]
            cc, admin1_code = c[8], c[10]
            population = c[14] or "0"

            country = countries.get(cc, cc)
            region = admin1.get(f"{cc}.{admin1_code}", "")

            # name \t asciiname \t lat \t lon \t country \t admin1 \t population
            f.write(
                "\t".join(
                    [name, ascii_name or name, lat, lon, country, region, population]
                )
                + "\n"
            )
            rows += 1

    size_mb = OUT.stat().st_size / 1e6
    print(f"\nDone — wrote {rows:,} places to {OUT} ({size_mb:.1f} MB).")
    print("Place search now runs fully offline.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nBuild failed: {e}", file=sys.stderr)
        sys.exit(1)
