from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from pathlib import Path

import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timedelta

import numpy as np
import xarray as xr

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


# Import torch FIRST so its bundled CUDA libraries (cuBLAS/cuDNN/cudart) load
# into the process and satisfy BOTH torch (XTTS-v2) and CTranslate2 (faster-
# whisper). If the separate nvidia-* pip cuDNN loads first, torch's bundled
# cuDNN clashes with it (WinError 127). When torch is present we let it own the
# CUDA libs and skip the manual preload below.
try:
    import torch  # noqa: F401

    _TORCH_LOADED = True
except Exception:
    _TORCH_LOADED = False


# On Windows the CUDA runtime DLLs ship inside the pip `nvidia-*` packages but
# aren't on the search path. Registering the dirs isn't enough: cuBLAS is loaded
# lazily by name and can't find its own dependency (cudart) from its folder. So
# we also PRELOAD the DLLs by full path in dependency order — once cudart is in
# memory, cuBLAS/cuDNN resolve no matter how CTranslate2 loads them.
def _register_cuda_dlls():
    if _TORCH_LOADED:
        return  # torch already loaded compatible CUDA libs for the whole process
    try:
        import ctypes
        import glob
        import nvidia

        # `nvidia` is a namespace package: use __path__, not __file__ (which is None).
        roots = list(getattr(nvidia, "__path__", []) or [])
        if not roots and getattr(nvidia, "__file__", None):
            roots = [os.path.dirname(nvidia.__file__)]

        bins = []
        for root in roots:
            bins += [
                os.path.abspath(d)
                for d in glob.glob(os.path.join(root, "*", "bin"))
            ]

        # 1) Make every nvidia bin dir discoverable.
        for d in bins:
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(d)
            except Exception:
                pass

        # 2) Collect all DLLs, then preload them in dependency order.
        dlls = {}
        for d in bins:
            for f in os.listdir(d):
                if f.lower().endswith(".dll"):
                    dlls.setdefault(f.lower(), os.path.join(d, f))

        order = [
            "cudart64",        # CUDA runtime — everything else needs it first
            "cublaslt64",      # cuBLAS depends on cuBLASLt
            "cublas64",
            "cudnn_ops",
            "cudnn_cnn",
            "cudnn_adv",
            "cudnn_engines",
            "cudnn_heuristic",
            "cudnn_graph",
            "cudnn64",         # main cuDNN entry depends on the sub-libs above
        ]
        loaded = set()
        for key in order:
            for name, full in dlls.items():
                if name.startswith(key) and name not in loaded:
                    try:
                        ctypes.WinDLL(full)
                        loaded.add(name)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[cuda] DLL preload issue: {e}")


_register_cuda_dlls()

# Lazily-loaded Whisper model for offline speech-to-text.
_WHISPER = None
_WHISPER_DEVICE = None


def get_whisper():
    global _WHISPER, _WHISPER_DEVICE
    if _WHISPER is None:
        import time

        from faster_whisper import WhisperModel

        model = os.getenv("WHISPER_MODEL", "small.en")
        device = os.getenv("WHISPER_DEVICE", "cuda")
        compute = os.getenv("WHISPER_COMPUTE", "float16")
        t0 = time.time()
        try:
            _WHISPER = WhisperModel(model, device=device, compute_type=compute)
            _WHISPER_DEVICE = device
        except Exception as e:
            print(f"[whisper] {device} load failed ({e}); falling back to CPU int8.")
            _WHISPER = WhisperModel(model, device="cpu", compute_type="int8")
            _WHISPER_DEVICE = "cpu"
        print(
            f"[whisper] loaded '{model}' on {_WHISPER_DEVICE} "
            f"({compute}) in {time.time() - t0:.1f}s"
        )
    return _WHISPER


# Skip Coqui's interactive license prompt (would hang a headless server).
os.environ.setdefault("COQUI_TOS_AGREED", "1")

# Lazily-loaded Coqui XTTS-v2 model for offline text-to-speech.
_TTS = None
_TTS_DEVICE = None


def get_tts():
    global _TTS, _TTS_DEVICE
    if _TTS is None:
        import time

        from TTS.api import TTS

        model = os.getenv(
            "TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"
        )
        device = os.getenv("TTS_DEVICE", "cuda")
        t0 = time.time()
        _TTS = TTS(model)
        try:
            _TTS.to(device)
            _TTS_DEVICE = device
        except Exception as e:
            print(f"[tts] {device} move failed ({e}); using CPU.")
            _TTS.to("cpu")
            _TTS_DEVICE = "cpu"
        print(f"[tts] loaded XTTS-v2 on {_TTS_DEVICE} in {time.time() - t0:.1f}s")
    return _TTS


app = FastAPI(title="WRF Windy Style GIS Backend")


@app.on_event("startup")
def _warm_whisper():
    """Load + run the model once in the background so the first real
    transcription doesn't pay the cold-start (model load + VAD init)."""
    if os.getenv("DISABLE_WHISPER_WARMUP", "1") == "1":
        print("[whisper] warmup disabled")
        return

    import threading

    def _run():
        try:
            import time

            t0 = time.time()
            model = get_whisper()
            list(
                model.transcribe(
                    np.zeros(16000, dtype=np.float32),
                    language="en",
                    beam_size=1,
                    vad_filter=True,
                )[0]
            )
            print(f"[whisper] warm and ready in {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[whisper] warmup skipped: {e}")

    threading.Thread(target=_run, daemon=True).start()


@app.on_event("startup")
def _warm_tts():
    """Pre-load XTTS-v2 in the background so the first spoken reply is fast."""
    if os.getenv("DISABLE_TTS_WARMUP", "1") == "1":
        print("[tts] warmup disabled")
        return

    import threading

    def _run():
        try:
            import time

            t0 = time.time()
            model = get_tts()
            speaker = os.getenv("TTS_SPEAKER", "Ana Florence")
            model.tts(text="Ready.", speaker=speaker, language="en")
            print(f"[tts] warm and ready in {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[tts] warmup skipped: {e}")

    threading.Thread(target=_run, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATASET = None
DATASET_PATH = None

CACHE_DIR = Path("cache/rasters")
UPLOAD_DIR = Path("uploaded_data")

CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class LoadRequest(BaseModel):
    file_path: str


class ExtractRequest(BaseModel):
    layer: str
    lat: float
    lon: float
    timestep: int = 0


LAYER_REGISTRY = {
    "temperature": {
        "label": "Temperature",
        "variables": ["T2", "TH2", "TSK"],
        "colormap": "turbo",
        "unit": "K",
    },
    "wind": {
        "label": "Wind",
        "variables": ["U10", "V10", "U", "V"],
        "colormap": "viridis",
        "unit": "m/s",
    },
    "pressure": {
        "label": "Pressure",
        "variables": ["PSFC", "MU", "MUB"],
        "colormap": "plasma",
        "unit": "Pa",
    },
    "humidity": {
        "label": "Humidity",
        "variables": ["Q2", "CANWAT", "SNOWC"],
        "colormap": "YlGnBu",
        "unit": "kg/kg",
    },
    "clouds": {
        "label": "Clouds",
        "variables": ["CLDFRA", "CLOUD_FRAC", "COSZEN", "EMISS"],
        "colormap": "Greys",
        "unit": "",
    },
    "radiation": {
        "label": "Radiation",
        "variables": [
            "SWDOWN",
            "GLW",
            "SWUPT",
            "SWUPB",
            "SWDNT",
            "SWDNB",
            "LWUPT",
            "LWUPB",
            "LWDNT",
            "LWDNB",
            "OLR",
            "ALBEDO",
        ],
        "colormap": "inferno",
        "unit": "W/m²",
    },
    "rain": {
        "label": "Rain",
        "variables": ["RAINC", "RAINNC", "RAINSH", "SFROFF", "UDROFF"],
        "colormap": "Blues",
        "unit": "mm",
    },
    "snow": {
        "label": "Snow",
        "variables": ["SNOW", "SNOWH", "SNOWNC", "SNOALB", "SNOWC"],
        "colormap": "cool",
        "unit": "",
    },
    "hail": {
        "label": "Hail",
        "variables": ["HAILNC", "GRAUPELNC"],
        "colormap": "Purples",
        "unit": "",
    },
    "sst": {
        "label": "Sea Surface Temperature",
        "variables": ["SST", "SSTSK", "SST_INPUT"],
        "colormap": "turbo",
        "unit": "K",
    },
    "seaice": {
        "label": "Sea Ice",
        "variables": ["SEAICE", "XICEM"],
        "colormap": "winter",
        "unit": "",
    },
    "currents": {
        "label": "Currents",
        "variables": ["U10", "V10"],
        "colormap": "viridis",
        "unit": "m/s",
    },
    "waves": {
        "label": "Waves",
        "variables": ["SWNORM", "SWDOWN", "OLR"],
        "colormap": "ocean",
        "unit": "",
    },
    "seastate": {
        "label": "Sea State",
        "variables": ["SST", "SEAICE", "U10", "V10", "PSFC"],
        "colormap": "cubehelix",
        "unit": "",
    },
    "terrain": {
        "label": "Terrain",
        "variables": ["HGT", "VAR_SSO", "MAPFAC_M", "MAPFAC_MX", "MAPFAC_MY"],
        "colormap": "terrain",
        "unit": "m",
    },
    "vegetation": {
        "label": "Vegetation",
        "variables": ["VEGFRA", "SHDMAX", "SHDMIN", "LAI", "IVGTYP"],
        "colormap": "Greens",
        "unit": "",
    },
    "soil": {
        "label": "Soil",
        "variables": ["TMN", "GRDFLX", "ACGRDFLX", "ISLTYP", "NOAHRES"],
        "colormap": "copper",
        "unit": "",
    },
    "landuse": {
        "label": "Land Use",
        "variables": ["LU_INDEX", "XLAND", "LANDMASK", "LAKEMASK"],
        "colormap": "tab20",
        "unit": "",
    },
}


LAYER_METADATA = {
    "temperature": {
        "unit": "K",
        "combination": "mean",
        "description": "Mean of available T2, TH2, and TSK temperature fields.",
    },
    "wind": {
        "unit": "m/s",
        "combination": "vector",
        "description": "Wind speed magnitude from U and V wind components.",
    },
    "pressure": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of surface pressure and dry-air mass fields.",
    },
    "humidity": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of near-surface humidity, canopy water, and snow cover.",
    },
    "clouds": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized cloud and sky composite using cloud fraction when available, plus COSZEN and EMISS.",
    },
    "radiation": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of available shortwave, longwave, OLR, and albedo fields.",
    },
    "rain": {
        "unit": "mm",
        "combination": "sum",
        "description": "Sum of available rain and runoff accumulations.",
    },
    "snow": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of snow water, height, snowfall, albedo, and cover.",
    },
    "hail": {
        "unit": "mm",
        "combination": "sum",
        "description": "Sum of available hail and graupel accumulations.",
    },
    "sst": {
        "unit": "K",
        "combination": "mean",
        "description": "Mean of available sea-surface temperature fields.",
    },
    "seaice": {
        "unit": "fraction",
        "combination": "mean",
        "description": "Mean of available sea-ice fraction and mask fields.",
    },
    "currents": {
        "unit": "m/s",
        "combination": "vector",
        "description": "Surface current approximation from U10 and V10 component magnitude.",
    },
    "waves": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized wave/radiation proxy using SWNORM, SWDOWN, and OLR.",
    },
    "seastate": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of SST, sea ice, surface winds, and surface pressure.",
    },
    "terrain": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of terrain height, terrain variance, and map-scale factors.",
    },
    "vegetation": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of vegetation fraction, shade, leaf area, and vegetation type.",
    },
    "soil": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of soil temperature, heat flux, soil type, and Noah residual.",
    },
    "landuse": {
        "unit": "index",
        "combination": "index",
        "description": "Normalized composite of land-use category, land/water mask, land mask, and lake mask.",
    },
}

for layer_key, metadata in LAYER_METADATA.items():
    LAYER_REGISTRY[layer_key].update(metadata)


LAYER_TREE = {
    "Atmosphere": ["temperature", "wind", "pressure", "humidity", "clouds", "radiation"],
    "Precipitation": ["rain", "snow", "hail"],
    "Ocean": ["sst", "seaice", "currents", "waves", "seastate"],
    "Land": ["terrain", "vegetation", "soil", "landuse"],
}


def require_dataset():
    if DATASET is None:
        raise HTTPException(status_code=400, detail="Dataset not loaded")
    return DATASET


DATESTR_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ _T]\d{2}:\d{2}:\d{2}")


def _row_to_str(row):
    """Turn a WRF ``Times`` entry into a string.

    WRF stores times either as a 2D character array (one ``|S1`` byte per
    character) or as a 1D array of fixed-width byte strings (``|S19``). Some
    readers also surface the characters as raw integer ASCII codes. Handle all
    of these so the timeline always gets real dates.
    """
    if isinstance(row, (bytes, bytearray)):
        return row.decode("utf-8", "ignore")

    if isinstance(row, str):
        return row

    parts = []
    for x in np.ravel(row):
        if isinstance(x, (bytes, bytearray)):
            parts.append(x.decode("utf-8", "ignore"))
        elif isinstance(x, str):
            parts.append(x)
        else:
            try:
                parts.append(chr(int(x)))
            except (ValueError, TypeError):
                pass
    return "".join(parts)


def parse_start_from_filename(path):
    """Read the initialisation time encoded in a wrfout filename.

    e.g. ``wrfout_d01_2025-07-01_00_00_00`` -> 2025-07-01 00:00:00.
    """
    if not path:
        return None

    match = re.search(
        r"(\d{4})-(\d{2})-(\d{2})[_-](\d{2})[_:-](\d{2})[_:-](\d{2})",
        str(path),
    )
    if not match:
        return None

    try:
        return datetime(*[int(g) for g in match.groups()])
    except ValueError:
        return None


def decode_times(ds, path=None):
    if path is None:
        path = DATASET_PATH

    # 1) Authoritative source: the Times character/byte array.
    if "Times" in ds:
        output = []
        for row in ds["Times"].values:
            raw = _row_to_str(row).replace("_", " ").strip().strip("\x00")
            if DATESTR_RE.match(raw):
                output.append(raw)
            else:
                output = None
                break

        if output:
            return output

    # 2) XTIME: xarray often decodes this straight to real datetimes;
    #    otherwise it is "minutes since" the filename's start time.
    if "XTIME" in ds:
        try:
            xvals = np.ravel(ds["XTIME"].values)

            if np.issubdtype(xvals.dtype, np.datetime64):
                return [
                    np.datetime_as_string(x, unit="s").replace("T", " ")
                    for x in xvals
                ]

            start = parse_start_from_filename(path)
            if start is not None:
                return [
                    (start + timedelta(minutes=float(m))).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    for m in xvals
                ]
        except Exception:
            pass

    # 3) Last resort: filename start time + an inferred step.
    start = parse_start_from_filename(path)
    if start is not None:
        steps = int(ds.sizes.get("Time", 1))
        step_minutes = 360  # 6-hourly WRF history output is the common default

        if "XTIME" in ds and ds["XTIME"].size >= 2:
            try:
                xs = np.ravel(ds["XTIME"].values).astype(float)
                step_minutes = float(xs[1] - xs[0]) or step_minutes
            except Exception:
                pass

        return [
            (start + timedelta(minutes=i * step_minutes)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            for i in range(steps)
        ]

    return []


def clear_raster_cache():
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_lat_lon(ds):
    if "XLAT" not in ds or "XLONG" not in ds:
        raise HTTPException(
            status_code=500,
            detail="XLAT/XLONG missing from WRF file",
        )

    lat = ds["XLAT"]
    lon = ds["XLONG"]

    if "Time" in lat.dims:
        lat = lat.isel(Time=0)

    if "Time" in lon.dims:
        lon = lon.isel(Time=0)

    return lat.values, lon.values


def get_bounds(ds):
    lat, lon = get_lat_lon(ds)

    return [
        [float(np.nanmin(lat)), float(np.nanmin(lon))],
        [float(np.nanmax(lat)), float(np.nanmax(lon))],
    ]


def get_domain_mask(ds):
    lat, lon = get_lat_lon(ds)
    return np.isfinite(lat) & np.isfinite(lon)


def get_grid_threshold(ds):
    lat, lon = get_lat_lon(ds)
    mask = np.isfinite(lat) & np.isfinite(lon)

    if mask.sum() < 2:
        return 0.25

    d1 = np.sqrt(np.diff(lat, axis=0) ** 2 + np.diff(lon, axis=0) ** 2)
    d2 = np.sqrt(np.diff(lat, axis=1) ** 2 + np.diff(lon, axis=1) ** 2)

    vals = np.concatenate(
        [
            d1[np.isfinite(d1)].ravel(),
            d2[np.isfinite(d2)].ravel(),
        ]
    )

    if vals.size == 0:
        return 0.25

    return float(np.nanmedian(vals) * 2.5)


def first_available(ds, variables):
    for v in variables:
        if v in ds:
            return v
    return None


def read_2d(ds, variable, timestep=0):
    if variable not in ds:
        raise HTTPException(
            status_code=404,
            detail=f"{variable} not found in dataset",
        )

    da = ds[variable]
    indexers = {}

    if "Time" in da.dims:
        indexers["Time"] = timestep

    if "bottom_top" in da.dims:
        indexers["bottom_top"] = 0

    if "soil_layers_stag" in da.dims:
        indexers["soil_layers_stag"] = 0

    if "num_land_cat" in da.dims:
        indexers["num_land_cat"] = 0

    da = da.isel(**indexers)

    if "west_east_stag" in da.dims:
        da = 0.5 * (
            da.isel(west_east_stag=slice(0, -1)).values
            + da.isel(west_east_stag=slice(1, None)).values
        )
        arr = np.squeeze(da)
    elif "south_north_stag" in da.dims:
        da = 0.5 * (
            da.isel(south_north_stag=slice(0, -1)).values
            + da.isel(south_north_stag=slice(1, None)).values
        )
        arr = np.squeeze(da)
    else:
        arr = da.squeeze().compute().values

    if arr.ndim != 2:
        raise HTTPException(
            status_code=500,
            detail=f"{variable} could not be reduced to 2D. Shape: {arr.shape}",
        )

    return np.array(arr, dtype=float)


def read_vector_pair(ds, primary_u, primary_v, fallback_u, fallback_v, timestep=0):
    if primary_u in ds and primary_v in ds:
        return read_2d(ds, primary_u, timestep), read_2d(ds, primary_v, timestep), f"{primary_u} + {primary_v}"

    if fallback_u in ds and fallback_v in ds:
        return read_2d(ds, fallback_u, timestep), read_2d(ds, fallback_v, timestep), f"{fallback_u} + {fallback_v}"

    raise HTTPException(
        status_code=404,
        detail=f"No vector pair found. Expected {primary_u}/{primary_v} or {fallback_u}/{fallback_v}",
    )


def available_layer_variables(ds, variables):
    return [variable for variable in variables if variable in ds]


def normalized_0_1(arr):
    finite = arr[np.isfinite(arr)]

    if finite.size == 0:
        return np.full_like(arr, np.nan, dtype=float)

    lo = float(np.nanpercentile(finite, 2))
    hi = float(np.nanpercentile(finite, 98))

    if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
        lo = float(np.nanmin(finite))
        hi = float(np.nanmax(finite))

    if lo == hi:
        normalized = np.zeros_like(arr, dtype=float)
        normalized[~np.isfinite(arr)] = np.nan
        return normalized

    return np.clip((arr - lo) / (hi - lo), 0, 1)


def stack_available_arrays(ds, variables, timestep=0):
    available = available_layer_variables(ds, variables)

    if not available:
        raise HTTPException(
            status_code=404,
            detail="No variables found for this layer",
        )

    arrays = [read_2d(ds, variable, timestep) for variable in available]
    return available, np.stack(arrays, axis=0)


def compute_scalar_combination(ds, layer_info, timestep=0):
    variables, stacked = stack_available_arrays(ds, layer_info["variables"], timestep)
    combination = layer_info.get("combination", "index")

    if combination == "sum":
        arr = np.nansum(stacked, axis=0)
        arr[np.sum(np.isfinite(stacked), axis=0) == 0] = np.nan
        source_variable = " + ".join(variables)
    elif combination == "mean":
        arr = np.nanmean(stacked, axis=0)
        source_variable = f"mean({', '.join(variables)})"
    else:
        normalized = np.stack([normalized_0_1(arr) for arr in stacked], axis=0)
        arr = np.nanmean(normalized, axis=0)
        source_variable = f"normalized mean({', '.join(variables)})"

    return arr, {
        "source_variable": source_variable,
        "source_variables": variables,
        "combination_method": combination,
        "component_count": len(variables),
        "legend_description": layer_info["description"],
    }


def wind_direction(u, v):
    return (270 - np.degrees(np.arctan2(v, u))) % 360


def direction_label(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((deg + 22.5) // 45) % 8
    return dirs[index]


def prepare_raster_for_leaflet(arr, ds):
    lat, _ = get_lat_lon(ds)
    raster = np.array(arr, dtype=float)

    domain_mask = get_domain_mask(ds)
    raster[~domain_mask] = np.nan

    if lat[0, 0] > lat[-1, 0]:
        raster = np.flipud(raster)

    return raster


def compute_layer(ds, layer, timestep=0):
    if layer not in LAYER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown layer: {layer}")

    layer_info = LAYER_REGISTRY[layer]

    if layer in ("wind", "currents"):
        u, v, source_variable = read_vector_pair(ds, "U10", "V10", "U", "V", timestep)
        speed = np.sqrt(u**2 + v**2)

        return speed, {
            "source_variable": source_variable,
            "source_variables": source_variable.split(" + "),
            "combination_method": "vector",
            "component_count": 2,
            "legend_description": layer_info["description"],
            "u": u,
            "v": v,
            "direction": wind_direction(u, v),
        }

    return compute_scalar_combination(ds, layer_info, timestep)


def load_wrf_dataset(path: Path):
    global DATASET
    global DATASET_PATH

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {str(path)}",
        )

    try:
        DATASET = xr.open_dataset(
            str(path),
            engine="netcdf4",
            chunks={
                "Time": 1,
                "south_north": 200,
                "west_east": 200,
            },
        )

        DATASET_PATH = str(path)
        clear_raster_cache()

        return {
            "status": "loaded",
            "file": DATASET_PATH,
            "variables": list(DATASET.data_vars.keys()),
            "bounds": get_bounds(DATASET),
            "timestamps": decode_times(DATASET),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load WRF dataset: {str(e)}",
        )


@app.get("/")
def root():
    return {
        "message": "WRF Windy Style Backend Running",
        "endpoints": [
            "/load",
            "/upload-zip",
            "/layers",
            "/timestamps",
            "/render/{layer}",
            "/extract",
            "/statistics/{layer}",
        ],
    }


@app.post("/load")
def load_dataset(req: LoadRequest):
    return load_wrf_dataset(Path(req.file_path))


@app.post("/upload-zip")
async def upload_zip(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a ZIP file",
        )

    safe_name = Path(file.filename).name
    zip_path = UPLOAD_DIR / safe_name

    try:
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded ZIP: {str(e)}",
        )

    extract_dir = UPLOAD_DIR / safe_name.replace(".zip", "")
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="Invalid ZIP file",
        )

    wrf_files = list(extract_dir.rglob("wrfout_d01*"))

    if not wrf_files:
        raise HTTPException(
            status_code=404,
            detail="No WRF file found inside ZIP. Expected wrfout_d01_*",
        )

    wrf_file = wrf_files[0]
    response = load_wrf_dataset(wrf_file)

    response["message"] = "ZIP uploaded, extracted, and WRF dataset loaded successfully"
    response["uploaded_zip"] = str(zip_path)

    return response


@app.get("/layers")
def get_layers():
    ds = DATASET
    output = {}

    for domain, layer_keys in LAYER_TREE.items():
        output[domain] = {}

        for key in layer_keys:
            cfg = LAYER_REGISTRY[key]
            available = False
            available_vars = []

            if ds is not None:
                available_vars = [v for v in cfg["variables"] if v in ds]
                if key in ("wind", "currents"):
                    available = ("U10" in ds and "V10" in ds) or ("U" in ds and "V" in ds)
                else:
                    available = len(available_vars) > 0

            output[domain][key] = {
                **cfg,
                "available": available,
                "available_variables": available_vars,
            }

    return output


@app.get("/timestamps")
def timestamps():
    ds = require_dataset()
    return {"timestamps": decode_times(ds)}


@app.post("/extract")
def extract(req: ExtractRequest):
    ds = require_dataset()

    lats, lons = get_lat_lon(ds)
    domain_mask = get_domain_mask(ds)
    arr, extra = compute_layer(ds, req.layer, req.timestep)

    dist = (lats - req.lat) ** 2 + (lons - req.lon) ** 2
    dist[~domain_mask] = np.nan

    iy, ix = np.unravel_index(np.nanargmin(dist), dist.shape)

    nearest_distance = float(np.sqrt(dist[iy, ix]))
    threshold = get_grid_threshold(ds)

    if nearest_distance > threshold or not np.isfinite(arr[iy, ix]):
        cfg = LAYER_REGISTRY[req.layer]

        return {
            "layer": req.layer,
            "label": cfg["label"],
            "value": None,
            "is_na": True,
            "display_text": "NA",
            "reason": "Clicked point is outside the WRF dataset domain",
            "requested_lat": float(req.lat),
            "requested_lon": float(req.lon),
            "nearest_lat": None,
            "nearest_lon": None,
            "grid_x": None,
            "grid_y": None,
        }

    value = arr[iy, ix]

    response = {
        "layer": req.layer,
        "label": LAYER_REGISTRY[req.layer]["label"],
        "value": float(value),
        "is_na": False,
        "source_variable": extra["source_variable"],
        "source_variables": extra.get("source_variables", []),
        "combination_method": extra.get("combination_method"),
        "legend_description": extra.get("legend_description"),
        "grid_x": int(ix),
        "grid_y": int(iy),
        "nearest_lat": float(lats[iy, ix]),
        "nearest_lon": float(lons[iy, ix]),
    }

    if req.layer in ("wind", "currents"):
        u = extra["u"][iy, ix]
        v = extra["v"][iy, ix]
        direction = extra["direction"][iy, ix]

        response.update(
            {
                "wind_speed": float(value),
                "u_component": float(u),
                "v_component": float(v),
                "wind_direction": float(direction),
                "wind_direction_deg": float(direction),
                "wind_direction_label": direction_label(float(direction)),
                "display_text": (
                    f"{float(value):.2f} m/s from "
                    f"{direction_label(float(direction))} "
                    f"({float(direction):.0f}°)"
                ),
            }
        )

    elif req.layer == "temperature":
        response.update(
            {
                "temperature_k": float(value),
                "temperature_c": float(value - 273.15),
                "display_text": f"{float(value - 273.15):.2f} °C",
            }
        )

    elif req.layer == "rain":
        response["display_text"] = f"{float(value):.2f} mm"

    elif LAYER_REGISTRY[req.layer]["unit"] == "index":
        response["display_text"] = f"{float(value):.2f} composite index"

    else:
        unit = LAYER_REGISTRY[req.layer]["unit"]
        response["display_text"] = f"{float(value):.2f} {unit}".strip()

    return response


@app.get("/statistics/{layer}")
def statistics(layer: str, timestep: int = 0):
    ds = require_dataset()

    arr, extra = compute_layer(ds, layer, timestep)
    finite = arr[np.isfinite(arr)]

    if finite.size == 0:
        raise HTTPException(status_code=500, detail="No finite data found")

    return {
        "layer": layer,
        "source_variable": extra["source_variable"],
        "source_variables": extra.get("source_variables", []),
        "combination_method": extra.get("combination_method"),
        "legend_description": extra.get("legend_description"),
        "min": float(np.nanmin(finite)),
        "max": float(np.nanmax(finite)),
        "mean": float(np.nanmean(finite)),
        "std": float(np.nanstd(finite)),
    }


@app.get("/render/{layer}")
def render_layer(
    layer: str,
    timestep: int = Query(0),
    dark: bool = Query(True),
    density: bool = Query(False),
):
    ds = require_dataset()

    if layer not in LAYER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown layer: {layer}")

    cfg = LAYER_REGISTRY[layer]
    arr, extra = compute_layer(ds, layer, timestep)

    # Clouds: default to the normal colormap composite (the original data).
    # Only when the animation toggle requests `density` do we swap to the
    # transparent->white cloud-cover overlay (thick opaque, clear transparent).
    cloud_density = layer == "clouds" and density and "CLDFRA" in ds
    if cloud_density:
        cda = ds["CLDFRA"]
        if "Time" in cda.dims:
            cda = cda.isel(Time=timestep)
        arr = np.asarray(cda.max(dim="bottom_top").compute().values, dtype=float)

    arr = prepare_raster_for_leaflet(arr, ds)
    bounds = get_bounds(ds)

    finite = arr[np.isfinite(arr)]

    if finite.size == 0:
        raise HTTPException(
            status_code=500,
            detail="No finite data found for this layer",
        )

    if cloud_density:
        vmin, vmax = 0.0, 1.0
    else:
        vmin = float(np.nanpercentile(finite, 2))
        vmax = float(np.nanpercentile(finite, 98))

        if vmin == vmax:
            vmin = float(np.nanmin(finite))
            vmax = float(np.nanmax(finite))

    # Only the cloud density overlay varies with the background; everything
    # else (incl. the normal cloud colormap) shares one key.
    dtag = ("dens_d" if dark else "dens_l") if cloud_density else "x"
    key = hashlib.md5(
        f"{DATASET_PATH}_{layer}_{timestep}_{dtag}_combined_layers_v6".encode()
    ).hexdigest()

    out = CACHE_DIR / f"{key}.png"

    if not out.exists():
        masked = np.ma.masked_invalid(arr)

        fig = plt.figure(figsize=(10, 8), dpi=180)
        ax = plt.axes([0, 0, 1, 1])
        ax.axis("off")

        if cloud_density:
            from matplotlib.colors import LinearSegmentedColormap

            if dark:  # white clouds on satellite / dark theme
                cmap = LinearSegmentedColormap.from_list(
                    "clouddensity_d",
                    [
                        (0.92, 0.94, 0.98, 0.0),
                        (0.95, 0.965, 0.99, 0.65),
                        (1.0, 1.0, 1.0, 0.96),
                    ],
                )
            else:  # dark slate clouds so they read on the light street map
                cmap = LinearSegmentedColormap.from_list(
                    "clouddensity_l",
                    [
                        (0.42, 0.47, 0.56, 0.0),
                        (0.33, 0.38, 0.48, 0.62),
                        (0.20, 0.25, 0.34, 0.92),
                    ],
                )
        else:
            cmap = plt.get_cmap(cfg["colormap"]).copy()
        cmap.set_bad(alpha=0)

        ax.imshow(
            masked,
            origin="lower",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            interpolation="bilinear",
        )

        fig.savefig(
            out,
            transparent=True,
            bbox_inches="tight",
            pad_inches=0,
        )

        plt.close(fig)

    return {
        "layer": layer,
        "label": cfg["label"],
        "unit": cfg["unit"],
        "colormap": cfg["colormap"],
        "source_variable": extra["source_variable"],
        "source_variables": extra.get("source_variables", []),
        "combination_method": extra.get("combination_method"),
        "legend_description": extra.get("legend_description"),
        "component_count": extra.get("component_count", 1),
        "image_url": f"http://localhost:8000/raster-image/{out.name}",
        "bounds": bounds,
        "vmin": vmin,
        "vmax": vmax,
    }


@app.get("/raster-image/{filename}")
def raster_image(filename: str):
    path = CACHE_DIR / filename

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Raster image not found",
        )

    return FileResponse(path, media_type="image/png")


# ---------------------------------------------------------------------------
# Area selection: aggregate a layer's values inside a drawn polygon
# ---------------------------------------------------------------------------


class AreaRequest(BaseModel):
    layer: str
    timestep: int = 0
    polygon: list  # [[lat, lon], ...]


@app.post("/area-statistics")
def area_statistics(req: AreaRequest):
    ds = require_dataset()

    if not req.polygon or len(req.polygon) < 3:
        raise HTTPException(
            status_code=400,
            detail="Polygon needs at least 3 points",
        )

    lats, lons = get_lat_lon(ds)
    domain_mask = get_domain_mask(ds)
    arr, extra = compute_layer(ds, req.layer, req.timestep)

    # matplotlib Path expects (x, y) = (lon, lat)
    poly_xy = [(float(lon), float(lat)) for lat, lon in req.polygon]
    path = MplPath(poly_xy)

    points = np.column_stack([lons.ravel(), lats.ravel()])
    inside = path.contains_points(points).reshape(lats.shape)

    mask = inside & domain_mask & np.isfinite(arr)
    values = arr[mask]

    cfg = LAYER_REGISTRY[req.layer]

    if values.size == 0:
        return {
            "layer": req.layer,
            "label": cfg["label"],
            "is_empty": True,
            "count": 0,
            "display_text": "No grid points inside this area",
        }

    mean = float(np.nanmean(values))

    response = {
        "layer": req.layer,
        "label": cfg["label"],
        "unit": cfg["unit"],
        "is_empty": False,
        "count": int(values.size),
        "min": float(np.nanmin(values)),
        "max": float(np.nanmax(values)),
        "mean": mean,
        "std": float(np.nanstd(values)),
        "source_variable": extra["source_variable"],
        "legend_description": extra.get("legend_description"),
    }

    if req.layer == "temperature":
        response["display_text"] = f"mean {mean - 273.15:.2f} °C"
    else:
        unit = cfg["unit"]
        response["display_text"] = f"mean {mean:.2f} {unit}".strip()

    return response


# ---------------------------------------------------------------------------
# Wind field: U10/V10 regridded to a regular lat/lon grid for the animated
# particle overlay (leaflet-velocity / Windy-style streamlines).
# ---------------------------------------------------------------------------

_WIND_CACHE = {}


@app.get("/wind-field")
def wind_field(timestep: int = 0, nx: int = 150, ny: int = 130):
    ds = require_dataset()
    if "U10" not in ds or "V10" not in ds:
        raise HTTPException(status_code=400, detail="Dataset has no U10/V10 wind.")

    key = (DATASET_PATH, timestep, nx, ny)
    if key in _WIND_CACHE:
        return _WIND_CACHE[key]

    from scipy.interpolate import griddata

    lats, lons = get_lat_lon(ds)
    u = read_2d(ds, "U10", timestep)
    v = read_2d(ds, "V10", timestep)

    # Rotate grid-relative winds to TRUE earth-relative (east/north) so the
    # directions are correct on ANY projection. For Mercator/Lat-Lon this is a
    # no-op (COSALPHA=1, SINALPHA=0); for Lambert/polar it applies the real
    # grid->earth rotation (wrf-python uvmet convention).
    if "COSALPHA" in ds and "SINALPHA" in ds:
        ca = read_2d(ds, "COSALPHA", timestep)
        sa = read_2d(ds, "SINALPHA", timestep)
        u, v = (u * ca + v * sa, -u * sa + v * ca)

    # Downsample the (curvilinear) source grid for a fast triangulation.
    s = max(1, max(lats.shape) // 250)
    plat = lats[::s, ::s].ravel()
    plon = lons[::s, ::s].ravel()
    pu = u[::s, ::s].ravel()
    pv = v[::s, ::s].ravel()
    m = np.isfinite(plat) & np.isfinite(plon) & np.isfinite(pu) & np.isfinite(pv)
    pts = np.column_stack([plon[m], plat[m]])

    lon_min, lon_max = float(np.nanmin(lons)), float(np.nanmax(lons))
    lat_min, lat_max = float(np.nanmin(lats)), float(np.nanmax(lats))
    gx = np.linspace(lon_min, lon_max, nx)
    gy = np.linspace(lat_max, lat_min, ny)  # north -> south (GFS scan order)
    GX, GY = np.meshgrid(gx, gy)

    gu = np.nan_to_num(griddata(pts, pu[m], (GX, GY), method="linear"), nan=0.0)
    gv = np.nan_to_num(griddata(pts, pv[m], (GX, GY), method="linear"), nan=0.0)

    header = {
        "nx": nx,
        "ny": ny,
        "lo1": lon_min,
        "la1": lat_max,
        "lo2": lon_max,
        "la2": lat_min,
        "dx": (lon_max - lon_min) / (nx - 1),
        "dy": (lat_max - lat_min) / (ny - 1),
        "parameterUnit": "m.s-1",
        "refTime": "2025-01-01T00:00:00Z",
    }

    result = [
        {
            "header": {**header, "parameterCategory": 2, "parameterNumber": 2,
                       "parameterNumberName": "eastward_wind"},
            "data": [round(float(x), 2) for x in gu.ravel()],
        },
        {
            "header": {**header, "parameterCategory": 2, "parameterNumber": 3,
                       "parameterNumberName": "northward_wind"},
            "data": [round(float(x), 2) for x in gv.ravel()],
        },
    ]

    if len(_WIND_CACHE) > 60:
        _WIND_CACHE.clear()
    _WIND_CACHE[key] = result
    return result


@app.get("/cloud-field")
def cloud_field(timestep: int = 0, nx: int = 140, ny: int = 120):
    """Total cloud cover (max CLDFRA over the column) + true-direction wind,
    regridded together, so the cloud puffs can drift along the real flow."""
    ds = require_dataset()
    if "CLDFRA" not in ds:
        raise HTTPException(status_code=400, detail="Dataset has no CLDFRA.")

    key = (DATASET_PATH, "cloud", timestep, nx, ny)
    if key in _WIND_CACHE:
        return _WIND_CACHE[key]

    from scipy.interpolate import LinearNDInterpolator

    da = ds["CLDFRA"]
    if "Time" in da.dims:
        da = da.isel(Time=timestep)
    cf = np.asarray(da.max(dim="bottom_top").compute().values, dtype=float)

    u = read_2d(ds, "U10", timestep)
    v = read_2d(ds, "V10", timestep)
    if "COSALPHA" in ds and "SINALPHA" in ds:  # true earth-relative direction
        ca = read_2d(ds, "COSALPHA", timestep)
        sa = read_2d(ds, "SINALPHA", timestep)
        u, v = (u * ca + v * sa, -u * sa + v * ca)

    lats, lons = get_lat_lon(ds)
    s = max(1, max(lats.shape) // 220)
    plat = lats[::s, ::s].ravel()
    plon = lons[::s, ::s].ravel()
    pcf = cf[::s, ::s].ravel()
    pu = u[::s, ::s].ravel()
    pv = v[::s, ::s].ravel()
    m = (
        np.isfinite(plat) & np.isfinite(plon)
        & np.isfinite(pcf) & np.isfinite(pu) & np.isfinite(pv)
    )
    pts = np.column_stack([plon[m], plat[m]])

    lon_min, lon_max = float(np.nanmin(lons)), float(np.nanmax(lons))
    lat_min, lat_max = float(np.nanmin(lats)), float(np.nanmax(lats))
    gx = np.linspace(lon_min, lon_max, nx)
    gy = np.linspace(lat_max, lat_min, ny)
    GX, GY = np.meshgrid(gx, gy)

    interp = LinearNDInterpolator(
        pts, np.column_stack([pcf[m], pu[m], pv[m]]), fill_value=0.0
    )
    out = interp(GX.ravel(), GY.ravel())
    cloud = np.clip(out[:, 0], 0, 1)

    result = {
        "nx": nx,
        "ny": ny,
        "lo1": lon_min,
        "la1": lat_max,
        "lo2": lon_max,
        "la2": lat_min,
        "dx": (lon_max - lon_min) / (nx - 1),
        "dy": (lat_max - lat_min) / (ny - 1),
        "cloud": [round(float(x), 3) for x in cloud],
        "u": [round(float(x), 2) for x in out[:, 1]],
        "v": [round(float(x), 2) for x in out[:, 2]],
    }

    if len(_WIND_CACHE) > 60:
        _WIND_CACHE.clear()
    _WIND_CACHE[key] = result
    return result


@app.get("/precip-field")
def precip_field(timestep: int = 0, nx: int = 170, ny: int = 150):
    """Rain RATE (mm per forecast step) regridded to a regular lat/lon grid for
    the falling-rain particle overlay."""
    ds = require_dataset()
    rain_vars = [v for v in ("RAINC", "RAINNC") if v in ds]
    if not rain_vars:
        raise HTTPException(status_code=400, detail="Dataset has no RAINC/RAINNC.")

    key = (DATASET_PATH, "precip", timestep, nx, ny)
    if key in _WIND_CACHE:
        return _WIND_CACHE[key]

    from scipy.interpolate import griddata

    n = int(ds.sizes.get("Time", 1))

    def accum(t):
        return sum(read_2d(ds, v, t) for v in rain_vars)

    cur = accum(timestep)
    if timestep >= 1:
        rate = np.clip(cur - accum(timestep - 1), 0, None)
    elif n > 1:
        rate = np.clip(accum(1) - cur, 0, None)  # forward diff for first frame
    else:
        rate = np.zeros_like(cur)

    lats, lons = get_lat_lon(ds)
    s = max(1, max(lats.shape) // 250)
    plat = lats[::s, ::s].ravel()
    plon = lons[::s, ::s].ravel()
    pr = rate[::s, ::s].ravel()
    m = np.isfinite(plat) & np.isfinite(plon) & np.isfinite(pr)
    pts = np.column_stack([plon[m], plat[m]])

    lon_min, lon_max = float(np.nanmin(lons)), float(np.nanmax(lons))
    lat_min, lat_max = float(np.nanmin(lats)), float(np.nanmax(lats))
    gx = np.linspace(lon_min, lon_max, nx)
    gy = np.linspace(lat_max, lat_min, ny)
    GX, GY = np.meshgrid(gx, gy)
    gr = np.clip(
        np.nan_to_num(griddata(pts, pr[m], (GX, GY), method="linear"), nan=0.0),
        0,
        None,
    )

    result = {
        "nx": nx,
        "ny": ny,
        "lo1": lon_min,
        "la1": lat_max,
        "lo2": lon_max,
        "la2": lat_min,
        "dx": (lon_max - lon_min) / (nx - 1),
        "dy": (lat_max - lat_min) / (ny - 1),
        "max": float(gr.max()),
        "data": [round(float(x), 2) for x in gr.ravel()],
    }

    if len(_WIND_CACHE) > 60:
        _WIND_CACHE.clear()
    _WIND_CACHE[key] = result
    return result


# ---------------------------------------------------------------------------
# Sea-route distance: water-following path between points (via searoute)
# ---------------------------------------------------------------------------


class SeaRouteRequest(BaseModel):
    points: list  # [[lat, lon], ...]


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p = np.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    h = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin(dlon / 2) ** 2
    )
    return float(2 * R * np.arcsin(min(1.0, np.sqrt(h))))


@app.post("/searoute")
def sea_route(req: SeaRouteRequest):
    try:
        import searoute as sr
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="The 'searoute' package is not installed on the server.",
        )

    pts = req.points or []
    if len(pts) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 points")

    coords = []  # [lat, lon] for drawing
    total_km = 0.0
    total_hours = 0.0

    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        origin = [float(a[1]), float(a[0])]  # searoute wants [lon, lat]
        dest = [float(b[1]), float(b[0])]
        try:
            r = sr.searoute(origin, dest, units="km")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Sea route failed: {e}")

        props = r.get("properties", {})
        total_km += float(props.get("length", 0) or 0)
        total_hours += float(props.get("duration_hours", 0) or 0)

        seg = [[c[1], c[0]] for c in r["geometry"]["coordinates"]]  # -> [lat, lon]
        if coords and seg:
            coords.extend(seg[1:])  # avoid duplicating the shared join point
        else:
            coords.extend(seg)

    # Warning logic (from the RAW route ends, before we stitch). Distinguish a
    # genuine on-land endpoint from a point that's simply far from searoute's
    # sparse shipping-lane network (open-ocean points can snap 100+ km).
    warning = None
    if coords:
        start_snap = _haversine_km(pts[0][0], pts[0][1], coords[0][0], coords[0][1])
        end_snap = _haversine_km(pts[-1][0], pts[-1][1], coords[-1][0], coords[-1][1])

        on_land = None
        try:
            from global_land_mask import globe

            on_land = bool(
                globe.is_land(float(pts[0][0]), float(pts[0][1]))
                or globe.is_land(float(pts[-1][0]), float(pts[-1][1]))
            )
        except Exception:
            on_land = None  # package missing — fall back to snap heuristic

        if on_land:
            warning = (
                "An endpoint is on land — the sea route is measured from the "
                "nearest coastline, so the distance is approximate."
            )
        elif on_land is None and max(start_snap, end_snap) > 60:
            warning = (
                "An endpoint may be inland — it snapped far from the sea network, "
                "so this sea distance is approximate."
            )
        elif max(start_snap, end_snap) > 150:
            warning = (
                "An endpoint is far from the nearest shipping lane, so this sea "
                "distance is approximate."
            )

    # searoute snaps each endpoint to its nearest sea node, which can sit well
    # off the clicked pin. Stitch the real clicked endpoints onto the route so
    # the drawn line connects to the markers instead of overshooting.
    if coords:
        origin_pt = [float(pts[0][0]), float(pts[0][1])]
        dest_pt = [float(pts[-1][0]), float(pts[-1][1])]
        if coords[0] != origin_pt:
            coords.insert(0, origin_pt)
        if coords[-1] != dest_pt:
            coords.append(dest_pt)

    return {
        "route": coords,
        "distance_km": round(total_km, 1),
        "duration_hours": round(total_hours, 1),
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Speech-to-text: transcribe a spoken clip locally on the GPU (faster-whisper)
# ---------------------------------------------------------------------------


def _decode_audio(path, target_sr=16000):
    """Decode any container/codec (webm/opus, wav, ogg…) to 16 kHz mono
    float32 using PyAV. Robust to MediaRecorder's streaming webm."""
    import av

    resampler = av.audio.resampler.AudioResampler(
        format="s16", layout="mono", rate=target_sr
    )
    chunks = []
    with av.open(path) as container:
        for frame in container.decode(audio=0):
            frame.pts = None
            out = resampler.resample(frame)
            for rf in out if isinstance(out, list) else [out]:
                if rf is not None:
                    chunks.append(rf.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    import tempfile
    import time
    import traceback

    data = await file.read()
    if not data:
        return {"text": ""}

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = tmp.name

    try:
        audio = _decode_audio(path)
        if audio.size < target_min_samples():
            return {"text": ""}  # too short / silent — nothing to transcribe

        model = get_whisper()
        t0 = time.time()
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        print(
            f"[whisper] {len(data) / 1024:.0f}KB -> {text!r} "
            f"in {time.time() - t0:.2f}s on {_WHISPER_DEVICE}"
        )
        return {"text": text}
    except Exception as e:
        traceback.print_exc()  # full cause in the server console
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def target_min_samples():
    return 1600  # 0.1 s at 16 kHz


class TTSRequest(BaseModel):
    text: str


@app.post("/tts")
def synthesize_speech(req: TTSRequest):
    import io
    import wave

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text to speak")
    text = text[:1200]  # keep clips reasonable

    try:
        import time

        model = get_tts()
        speaker = os.getenv("TTS_SPEAKER", "Ana Florence")
        language = os.getenv("TTS_LANGUAGE", "en")

        t0 = time.time()
        wav = model.tts(text=text, speaker=speaker, language=language)
        sr = int(getattr(model.synthesizer, "output_sample_rate", 24000))

        pcm = (np.clip(np.asarray(wav, dtype=np.float32), -1, 1) * 32767).astype("<i2")
        buf = io.BytesIO()
        w = wave.open(buf, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
        w.close()
        print(f"[tts] {len(text)} chars -> {len(pcm)/sr:.1f}s audio in "
              f"{time.time() - t0:.2f}s on {_TTS_DEVICE}")
        return Response(content=buf.getvalue(), media_type="audio/wav")
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


# ---------------------------------------------------------------------------
# Forecast alerts: scan the whole timeline for preset weather thresholds
# ---------------------------------------------------------------------------

_SEV_ORDER = {"yellow": 1, "orange": 2, "red": 3}


def _alert(kind, label, severity, t, time, lat, lon, value, unit, text):
    return {
        "type": kind,
        "label": label,
        "severity": severity,
        "timestep": t,
        "time": time,
        "lat": round(float(lat), 3),
        "lon": round(float(lon), 3),
        "value": value,
        "unit": unit,
        "text": text,
    }


def scan_alerts(ds):
    lats, lons = get_lat_lon(ds)
    domain = get_domain_mask(ds)
    times = decode_times(ds)
    n = len(times) if times else int(ds.sizes.get("Time", 1))

    def has(v):
        return v in ds

    def extreme(arr, mode):
        masked = np.where(domain & np.isfinite(arr), arr, np.nan)
        if not np.isfinite(masked).any():
            return None
        idx = np.nanargmax(masked) if mode == "max" else np.nanargmin(masked)
        iy, ix = np.unravel_index(idx, masked.shape)
        return float(masked[iy, ix]), float(lats[iy, ix]), float(lons[iy, ix])

    def sev(value, ladder):
        for thr, s in ladder:
            if value >= thr:
                return s
        return None

    raw = []
    tvar = "T2" if has("T2") else ("TSK" if has("TSK") else None)
    rain_vars = [v for v in ("RAINC", "RAINNC") if has(v)]
    prev_rain = None

    for t in range(n):
        time = times[t] if t < len(times) else str(t)

        if tvar:
            ex = extreme(read_2d(ds, tvar, t), "max")
            if ex:
                c = ex[0] - 273.15
                s = sev(c, [(45, "red"), (42, "orange"), (40, "yellow")])
                if s:
                    raw.append(_alert("heat", "Heatwave", s, t, time, ex[1], ex[2], round(c, 1), "°C", ""))

        if has("U10") and has("V10"):
            spd = np.hypot(read_2d(ds, "U10", t), read_2d(ds, "V10", t))
            ex = extreme(spd, "max")
            if ex:
                s = sev(ex[0], [(32, "red"), (24, "orange"), (17, "yellow")])
                if s:
                    raw.append(_alert("wind", "High wind", s, t, time, ex[1], ex[2], round(ex[0], 1), "m/s", ""))

        # Storm: reduce surface pressure to MEAN SEA LEVEL so terrain doesn't
        # masquerade as a storm (PSFC alone is dominated by elevation).
        if has("PSFC") and has("HGT") and tvar:
            psfc = read_2d(ds, "PSFC", t)
            hgt = read_2d(ds, "HGT", t)
            temp = read_2d(ds, tvar, t)
            temp = np.where(temp > 100, temp, 288.0)  # guard
            mslp = psfc * (1 + 0.0065 * hgt / temp) ** 5.257
            # MSLP reduction is only valid over low terrain — exclude plateaus.
            mslp = np.where(hgt < 500, mslp, np.nan)
            ex = extreme(mslp, "min")
            if ex:
                hpa = ex[0] / 100
                s = sev(-hpa, [(-980, "red"), (-990, "orange"), (-1000, "yellow")])
                if s:
                    raw.append(_alert("storm", "Low pressure", s, t, time, ex[1], ex[2], round(hpa, 1), "hPa", ""))

        if rain_vars:
            cur = sum(read_2d(ds, v, t) for v in rain_vars)
            if prev_rain is not None:
                rate = np.clip(cur - prev_rain, 0, None)
                ex = extreme(rate, "max")
                if ex:
                    s = sev(ex[0], [(70, "red"), (40, "orange"), (20, "yellow")])
                    if s:
                        raw.append(_alert("rain", "Heavy rain", s, t, time, ex[1], ex[2], round(ex[0], 1), "mm", ""))
            prev_rain = cur

    # Aggregate per type into one card with its peak + affected frames.
    text_for = {
        "heat": lambda v: f"Peak {v:.0f}°C",
        "wind": lambda v: f"Peak {v:.0f} m/s (~{v * 3.6:.0f} km/h)",
        "storm": lambda v: f"Min {v:.0f} hPa at sea level",
        "rain": lambda v: f"Up to {v:.0f} mm per step",
    }

    groups = {}
    for a in raw:
        g = groups.setdefault(
            a["type"],
            {"type": a["type"], "label": a["label"], "unit": a["unit"], "frames": []},
        )
        g["frames"].append(
            {
                "timestep": a["timestep"],
                "time": a["time"],
                "severity": a["severity"],
                "value": a["value"],
                "lat": a["lat"],
                "lon": a["lon"],
            }
        )

    alerts = []
    for g in groups.values():
        frames = g["frames"]
        max_sev = max(_SEV_ORDER[f["severity"]] for f in frames)
        sev_name = next(k for k, v in _SEV_ORDER.items() if v == max_sev)
        candidates = [f for f in frames if _SEV_ORDER[f["severity"]] == max_sev]
        peak = (
            min(candidates, key=lambda f: f["value"])
            if g["type"] == "storm"
            else max(candidates, key=lambda f: f["value"])
        )
        alerts.append(
            {
                "type": g["type"],
                "label": g["label"],
                "severity": sev_name,
                "unit": g["unit"],
                "peak_value": peak["value"],
                "peak_time": peak["time"],
                "peak_timestep": peak["timestep"],
                "lat": peak["lat"],
                "lon": peak["lon"],
                "frame_count": len(frames),
                "total_frames": n,
                "text": text_for.get(g["type"], lambda v: f"{v}")(peak["value"]),
                "frames": [
                    {"timestep": f["timestep"], "severity": f["severity"]} for f in frames
                ],
            }
        )

    alerts.sort(key=lambda a: (-_SEV_ORDER[a["severity"]], -a["frame_count"]))

    by_timestep = {}
    for a in raw:
        cur = by_timestep.get(a["timestep"])
        if cur is None or _SEV_ORDER[a["severity"]] > _SEV_ORDER[cur]:
            by_timestep[a["timestep"]] = a["severity"]

    return {"alerts": alerts, "by_timestep": by_timestep, "count": len(alerts)}


@app.get("/alerts")
def alerts():
    ds = require_dataset()
    return scan_alerts(ds)


# ---------------------------------------------------------------------------
# Offline place search: a local GeoNames gazetteer (no network at runtime).
# Build it once with:  python scripts/build_gazetteer.py
# ---------------------------------------------------------------------------
GAZETTEER_PATH = Path(__file__).resolve().parent / "data" / "geonames.tsv"
_GAZETTEER = None


def _load_gazetteer():
    """Load the gazetteer into memory once, sorted by population (desc) so the
    most prominent places surface first. Returns None if it hasn't been built."""
    global _GAZETTEER
    if _GAZETTEER is not None:
        return _GAZETTEER
    if not GAZETTEER_PATH.exists():
        return None

    entries = []
    with open(GAZETTEER_PATH, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            name, ascii_name, lat, lon, country, admin1, pop = parts[:7]
            try:
                lat_f, lon_f = float(lat), float(lon)
                pop_i = int(pop or 0)
            except ValueError:
                continue
            label = ", ".join(x for x in (name, admin1, country) if x)
            entries.append(
                {
                    "name": name,
                    "search": (ascii_name or name).lower(),
                    "lat": lat_f,
                    "lon": lon_f,
                    "label": label,
                    "population": pop_i,
                }
            )

    entries.sort(key=lambda e: e["population"], reverse=True)
    _GAZETTEER = entries
    print(f"[geocode] loaded {len(entries):,} places")
    return _GAZETTEER


@app.get("/geocode")
def geocode(q: str = Query(...), limit: int = 6):
    """Offline place lookup. Prefix matches rank above substring matches; within
    each tier the more populous place wins (entries are pre-sorted by pop)."""
    entries = _load_gazetteer()
    if entries is None:
        raise HTTPException(
            status_code=503,
            detail="Offline gazetteer not built. Run: python scripts/build_gazetteer.py",
        )

    qq = q.strip().lower()
    if len(qq) < 2:
        return {"results": []}

    starts, contains = [], []
    for e in entries:
        s = e["search"]
        if s.startswith(qq):
            starts.append(e)
            if len(starts) >= limit:
                break
        elif len(contains) < limit and qq in s:
            contains.append(e)

    chosen = (starts + contains)[:limit]
    return {
        "results": [
            {
                "lat": e["lat"],
                "lon": e["lon"],
                "label": e["label"],
                "name": e["name"],
                "population": e["population"],
            }
            for e in chosen
        ]
    }


# ---------------------------------------------------------------------------
# Natural-language assistant: turn a request into map actions via local Ollama
# ---------------------------------------------------------------------------


class AssistantRequest(BaseModel):
    message: str
    context: dict = {}


def run_point_weather(lat, lon, time_index=0):
    """Read actual weather values at a lat/lon (and time) from the dataset."""
    if DATASET is None:
        return {"error": "No dataset is loaded yet."}

    if lat is None or lon is None:
        return {"error": "I need a location (latitude and longitude) to read the weather."}

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return {"error": "Invalid coordinates."}

    try:
        time_index = int(time_index)
    except (TypeError, ValueError):
        time_index = 0

    ds = DATASET

    try:
        lats, lons = get_lat_lon(ds)
    except Exception:
        return {"error": "Dataset has no coordinates."}

    domain = np.isfinite(lats) & np.isfinite(lons)
    dist = np.where(domain, (lats - lat) ** 2 + (lons - lon) ** 2, np.nan)

    if not np.isfinite(dist).any():
        return {"error": "Dataset domain is empty."}

    iy, ix = np.unravel_index(np.nanargmin(dist), dist.shape)
    nearest_dist = float(np.sqrt(dist[iy, ix]))
    threshold = get_grid_threshold(ds)

    times = decode_times(ds)
    n = len(times) if times else int(ds.sizes.get("Time", 1))
    ts = max(0, min(n - 1 if n else 0, int(time_index)))

    if nearest_dist > threshold:
        return {
            "in_domain": False,
            "requested_lat": float(lat),
            "requested_lon": float(lon),
            "message": "That location is outside the loaded WRF model domain, so there is no data for it.",
        }

    def sample(var):
        if var in ds:
            try:
                value = read_2d(ds, var, ts)[iy, ix]
                return float(value) if np.isfinite(value) else None
            except Exception:
                return None
        return None

    out = {
        "in_domain": True,
        "time": times[ts] if ts < len(times) else None,
        "nearest_lat": round(float(lats[iy, ix]), 3),
        "nearest_lon": round(float(lons[iy, ix]), 3),
    }

    temp = sample("T2")
    if temp is None:
        temp = sample("TSK")
    if temp is not None:
        out["temperature_c"] = round(temp - 273.15, 1)

    u = sample("U10")
    v = sample("V10")
    if u is not None and v is not None:
        out["wind_speed_ms"] = round(float(np.hypot(u, v)), 1)
        deg = float(wind_direction(np.array(u), np.array(v)))
        out["wind_from"] = direction_label(deg)
        out["wind_direction_deg"] = round(deg)

    psfc = sample("PSFC")
    if psfc is not None:
        out["pressure_hpa"] = round(psfc / 100, 1)

    q2 = sample("Q2")
    if q2 is not None:
        out["humidity_g_per_kg"] = round(q2 * 1000, 2)

    rainc = sample("RAINC")
    rainnc = sample("RAINNC")
    rain_parts = [r for r in (rainc, rainnc) if r is not None]
    if rain_parts:
        out["rain_accum_mm"] = round(sum(rain_parts), 2)

    return out


def build_assistant_tools():
    layer_keys = list(LAYER_REGISTRY.keys())

    return [
        {
            "name": "get_weather",
            "description": "Read the ACTUAL weather values (temperature, wind, pressure, humidity, rain) at a latitude/longitude from the loaded WRF dataset, optionally at a specific timestep. Use this to ANSWER questions like 'what's the weather in Mumbai' or 'weather at 8, 77'. Resolve place names to coordinates yourself. Returns data you must then summarise in plain language.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "place": {"type": "string", "description": "Name of the place, for your reference"},
                    "time_index": {
                        "type": "integer",
                        "description": "0-based timestep index; default to the current timestep if the user gave no date",
                    },
                },
                "required": ["lat", "lon"],
            },
        },
        {
            "name": "set_layers",
            "description": "Turn on one or more weather layers on the map. This replaces the currently shown layer.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "layers": {
                        "type": "array",
                        "items": {"type": "string", "enum": layer_keys},
                        "description": "Layer keys to activate",
                    }
                },
                "required": ["layers"],
            },
        },
        {
            "name": "deselect_all_layers",
            "description": "Turn off all weather layers and show only the base map.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "set_time",
            "description": "Move the forecast timeline to a specific timestep by its 0-based index in the timestamps list provided in the system prompt.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "0-based timestep index",
                    }
                },
                "required": ["index"],
            },
        },
        {
            "name": "zoom_to",
            "description": "Zoom and pan the map to a geographic area. Provide an approximate latitude/longitude bounding box for the place the user named, using your own geographic knowledge.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "south": {"type": "number"},
                    "west": {"type": "number"},
                    "north": {"type": "number"},
                    "east": {"type": "number"},
                    "place": {"type": "string", "description": "Name of the place"},
                },
                "required": ["south", "west", "north", "east"],
            },
        },
        {
            "name": "drop_pin",
            "description": "Place a pin at a latitude/longitude and read the data value there. Resolve a named location to coordinates using your geographic knowledge.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "label": {"type": "string"},
                },
                "required": ["lat", "lon"],
            },
        },
        {
            "name": "set_opacity",
            "description": "Set the layer overlay opacity, from 0 (transparent) to 1 (opaque).",
            "input_schema": {
                "type": "object",
                "properties": {"opacity": {"type": "number"}},
                "required": ["opacity"],
            },
        },
    ]


def _coerce_args(params):
    """Local models often stringify arguments (e.g. layers='[\"wind\"]', lat='8').
    Best-effort parse strings that look like JSON values back into real types."""
    if not isinstance(params, dict):
        return {}

    out = {}
    for key, value in params.items():
        if isinstance(value, str):
            s = value.strip()
            for candidate in (s, s.replace("'", '"')):
                try:
                    out[key] = json.loads(candidate)
                    break
                except Exception:
                    continue
            else:
                out[key] = value
        else:
            out[key] = value
    return out


def _maybe_leaked_tool(content):
    """Weak local models sometimes emit a tool call as plain text JSON instead of
    using the tool mechanism. Detect and parse it: returns (name, args) or None."""
    s = (content or "").strip()
    if not (s.startswith("{") and '"name"' in s):
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    args = obj.get("parameters") or obj.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    return obj.get("name"), _coerce_args(args)


def _dispatch_tool_calls(tool_calls, current_ts, actions):
    """Execute tool calls. Returns (server_results, had_server_tool).

    `tool_calls` is a list of (id, name, params). Frontend actions are recorded
    in `actions`; get_weather runs server-side and its data is returned.
    """
    results = []
    had_server = False
    for call_id, name, params in tool_calls:
        params = params or {}
        if name == "get_weather":
            had_server = True
            data = run_point_weather(
                params.get("lat"),
                params.get("lon"),
                params.get("time_index", current_ts if current_ts is not None else 0),
            )
            results.append((call_id, json.dumps(data)))
        else:
            actions.append({"type": name, "params": params})
            results.append((call_id, "Done — the UI is performing this action."))
    return results, had_server


def _assistant_ollama(system, message, current_ts):
    import urllib.error
    import urllib.request

    base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in build_assistant_tools()
    ]

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]

    actions = []
    reply = ""

    def chat():
        body = json.dumps(
            {
                "model": model,
                "messages": messages,
                "tools": ollama_tools,
                "stream": False,
                "options": {"temperature": 0.2},
            }
        ).encode("utf-8")
        req_obj = urllib.request.Request(
            base_url + "/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_obj, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        for _ in range(5):
            data = chat()
            msg = data.get("message", {}) or {}
            content = (msg.get("content") or "").strip()
            tool_calls_raw = msg.get("tool_calls") or []

            if content:
                reply = content

            if not tool_calls_raw:
                break

            tool_calls = []
            for tc in tool_calls_raw:
                fn = tc.get("function", {}) or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append((None, fn.get("name"), _coerce_args(args or {})))

            messages.append(msg)
            results, _ = _dispatch_tool_calls(tool_calls, current_ts, actions)
            for _cid, out in results:
                messages.append({"role": "tool", "content": out})
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Couldn't reach Ollama at {base_url} — is it running? ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama assistant failed: {str(e)}")

    if not reply:
        reply = "Done." if actions else FALLBACK_HINT

    return {"reply": reply, "actions": actions}


_COVERAGE_RE = re.compile(
    r"\bdates?\b|\btime\s*range\b|\bdate\s*range\b|\bforecast\s*range\b"
    r"|how many\s*(time\s*steps|steps|days|times|hours)"
    r"|\bcoverage\b|what\s*(times|dates|period)|which\s*(dates|times)"
    r"|how (far|long)\b|time\s*period",
    re.IGNORECASE,
)


def _interval_hours(timestamps):
    """Hours between consecutive timesteps, inferred from the data. None if unknown."""
    if not timestamps or len(timestamps) < 2:
        return None
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        a = datetime.strptime(timestamps[0], fmt)
        b = datetime.strptime(timestamps[1], fmt)
    except Exception:
        return None
    hours = (b - a).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return int(hours) if hours == int(hours) else round(hours, 2)


_HELP_TEXT = (
    "I can:\n"
    '• Show a layer — "show wind", "turn on rain"\n'
    '• Hide layers — "clear the map"\n'
    '• Move in time — "go to July 3 at noon"\n'
    '• Zoom — "zoom to Pakistan"\n'
    '• Drop a pin — "drop a pin on Delhi"\n'
    '• Read the weather — "weather in Mumbai" or "weather at 8, 77"\n'
    '• Coverage — "what dates are available"'
)

FALLBACK_HINT = (
    "I couldn't map that to an action. Try things like \"show wind\", "
    "\"weather in Mumbai\", \"go to July 3 at noon\", or \"zoom to India\"."
)


def _quick_answer(message, ctx):
    """Deterministic answers for common inputs (greetings, help, layer list,
    coverage), so the assistant is always helpful even with a weak local model.
    Returns a string, or None to fall through to the LLM."""
    ctx = ctx or {}
    timestamps = ctx.get("timestamps") or []
    layers = ctx.get("layers") or [
        {"key": k, "label": LAYER_REGISTRY[k]["label"]} for k in LAYER_REGISTRY
    ]

    raw = (message or "").strip()
    m = raw.lower()
    if not m:
        return None

    # Greeting
    if re.fullmatch(r"(hi|hello|hey|hiya|yo|namaste|greetings|good (morning|evening|afternoon))( there| everyone)?[\s.!]*", m):
        return (
            "Hi! I can turn weather layers on or off, jump to a time, zoom to a "
            'place, drop a pin, or tell you the weather. Try "show wind", '
            '"weather in Mumbai", or "what can you do".'
        )

    # Thanks
    if re.search(r"\b(thanks|thank you|thx|cheers|appreciate it)\b", m):
        return "You're welcome!"

    # Help / capabilities
    if re.search(
        r"\b(help|what can you do|what can i (ask|say|do)|how (do|can) i use|commands?|capabilit|what do you do)\b",
        m,
    ):
        return _HELP_TEXT

    # List of available layers
    if re.search(
        r"((what|which|list|show me the|available).{0,25}\blayers?\b)"
        r"|(\blayers?\b.{0,25}(available|are there|can i (use|see|pick)))",
        m,
    ):
        names = ", ".join(l["label"] for l in layers)
        return f"Available layers: {names}."

    # Weather alerts
    if re.search(r"\b(alert|alerts|warning|warnings|severe|hazard|dangerous)\b", m):
        if DATASET is None:
            return "Load a dataset first, then I can check it for weather alerts."
        try:
            res = scan_alerts(DATASET)
        except Exception:
            return None
        if not res["alerts"]:
            return "Good news — no weather alerts in this forecast."
        parts = [f"{a['label']} ({a['severity']}, {a['text'].lower()})" for a in res["alerts"][:5]]
        return "Forecast alerts: " + "; ".join(parts) + "."

    # Forecast coverage / dates
    if timestamps and _COVERAGE_RE.search(raw):
        n = len(timestamps)
        step = _interval_hours(timestamps)
        cadence = f"{step}-hourly, " if step else ""
        return (
            f"The loaded forecast has {n} time steps, {cadence}"
            f"from {timestamps[0]} to {timestamps[-1]} UTC."
        )

    return None


def _ollama_post(payload, timeout=600):
    import urllib.request

    base = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text):
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if "\n" in s:
            s = s.split("\n", 1)[1]
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i : j + 1])
        except Exception:
            return None
    return None


PROMPT_MODE_TAIL = """

RESPONSE FORMAT — VERY IMPORTANT:
Reply with ONLY a single JSON object and nothing else (no markdown, no code fences):
{"reply": "<one or two short sentences for the user>", "actions": [ ... ]}

Each action is {"name": "<action>", "params": { ... }}. Available actions:
- set_layers          {"layers": ["<layer key>"]}                       show a weather layer
- deselect_all_layers {}                                                hide all layers
- set_time            {"index": <int>}                                  move timeline to a timestep index
- zoom_to             {"south":<n>,"west":<n>,"north":<n>,"east":<n>}   zoom the map to an area
- drop_pin            {"lat":<n>,"lon":<n>}                              place a marker
- set_opacity         {"opacity": <0..1>}
- get_weather         {"lat":<n>,"lon":<n>,"time_index":<int>}          read real weather at a point

Rules:
- For a weather question at a place / coordinate / the pin, output a get_weather action with the coordinates; keep "reply" brief — you will then be given the data to summarise.
- If no map action is needed, use "actions": [].
- Output the JSON object only."""


def _assistant_ollama_prompt(system, message, current_ts):
    import urllib.error

    model = os.environ.get("OLLAMA_MODEL", "llama3:8b")
    base_system = system + PROMPT_MODE_TAIL
    messages = [
        {"role": "system", "content": base_system},
        {"role": "user", "content": message},
    ]

    actions = []
    reply = ""
    known = {t["name"] for t in build_assistant_tools()}

    try:
        for _ in range(3):
            data = _ollama_post(
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                }
            )
            content = (data.get("message", {}) or {}).get("content", "") or ""
            parsed = _extract_json(content)

            if not parsed:
                reply = content.strip()[:600]
                break

            acts = parsed.get("actions") or []
            weather = []
            has_weather = False

            for a in acts:
                if not isinstance(a, dict):
                    continue
                name = a.get("name")
                params = _coerce_args(a.get("params") or a.get("parameters") or {})
                if name == "get_weather":
                    has_weather = True
                    weather.append(
                        run_point_weather(
                            params.get("lat"),
                            params.get("lon"),
                            params.get(
                                "time_index", current_ts if current_ts is not None else 0
                            ),
                        )
                    )
                elif name in known:
                    actions.append({"type": name, "params": params})

            if has_weather:
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": "Weather data: "
                        + json.dumps(weather)
                        + '. Now reply with ONLY JSON {"reply":"<1-2 sentence summary using these values, temperature in C, wind in m/s, pressure in hPa, rain in mm>","actions":[]}.',
                    }
                )
                continue

            reply = (parsed.get("reply") or "").strip()
            break
    except urllib.error.URLError as e:
        base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        raise HTTPException(
            status_code=502,
            detail=f"Couldn't reach Ollama at {base_url} — is it running? ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama assistant failed: {str(e)}")

    if not reply:
        reply = "Done." if actions else FALLBACK_HINT

    return {"reply": reply, "actions": actions}


def _assistant_system(ctx):
    ctx = ctx or {}
    layers = ctx.get("layers") or [
        {"key": k, "label": LAYER_REGISTRY[k]["label"]} for k in LAYER_REGISTRY
    ]
    timestamps = ctx.get("timestamps") or []

    layer_lines = "\n".join(f"{l['key']}: {l['label']}" for l in layers)
    ts_lines = "\n".join(f"{i}: {t}" for i, t in enumerate(timestamps[:200]))

    if timestamps:
        step = _interval_hours(timestamps)
        cadence = f", {step}-hourly" if step else ""
        coverage = (
            f"{len(timestamps)} timesteps{cadence} from {timestamps[0]} to "
            f"{timestamps[-1]} (UTC)"
        )
    else:
        coverage = "no dataset loaded yet"

    current_ts = ctx.get("current_timestep")

    system = f"""You are the assistant for a WRF weather visualization web map.
You can both DRIVE the map (tool calls the UI performs) and ANSWER weather questions using real data.

Available layers (key: label):
{layer_lines}

Current layer: {ctx.get('current_layer')}
Current timestep index: {current_ts}
Map data bounds [[minLat, minLon], [maxLat, maxLon]]: {ctx.get('bounds')}
Dropped pin / marker location (lat, lon): {ctx.get('pin')}
Forecast coverage: {coverage}

Forecast timestamps (index: time, UTC):
{ts_lines}

Guidance:
- If the user asks which dates or times are available, the date/time range, how far the forecast goes, or how many timesteps there are, answer DIRECTLY from the forecast coverage and timestamps above (state the first time, the last time, and the 6-hour interval). Do NOT ask for a location for these questions and do NOT call any tool.
- If the user refers to "the pin", "the marker", "this point", or "here", use the dropped pin location above as the coordinates. If no pin is set (it is null) and the user refers to one, tell them to click the map to drop a pin first.
- To ANSWER what the weather is at a place or coordinate (e.g. "weather in Mumbai", "weather at 8, 77"), call get_weather with its latitude/longitude. For a place name, resolve the coordinates yourself. If the user gives a date/time, map it to the closest timestamp index and pass it as time_index; otherwise use the current timestep index ({current_ts}). Then write a short, friendly weather summary from the values returned (give temperature in °C, wind in m/s with direction, pressure in hPa, rain in mm). If the data says it is outside the domain, say so plainly.
- The dataset only covers the forecast timestamps listed above (see "Forecast coverage") — you cannot give weather for dates outside that range.
- To change the shown weather layer, call set_layers with the matching key(s).
- To move the timeline, call set_time with the closest matching index.
- To zoom to a place, call zoom_to with an approximate bounding box.
- To place a marker, call drop_pin with coordinates.
- Keep replies short. If the request maps to no action and no data, just answer in text."""

    return system, current_ts


def _ndjson(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


def _stream_ollama(system, message, current_ts):
    import urllib.error
    import urllib.request

    base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in build_assistant_tools()
    ]

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]
    actions = []

    try:
        for _ in range(5):
            body = json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "tools": ollama_tools,
                    "stream": True,
                    "options": {"temperature": 0.2},
                }
            ).encode("utf-8")
            req_obj = urllib.request.Request(
                base_url + "/api/chat",
                data=body,
                headers={"Content-Type": "application/json"},
            )

            assembled = ""
            tool_calls_raw = []

            with urllib.request.urlopen(req_obj, timeout=300) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    m = obj.get("message", {}) or {}
                    piece = m.get("content") or ""
                    if piece:
                        assembled += piece
                        yield _ndjson({"type": "delta", "text": piece})
                    if m.get("tool_calls"):
                        tool_calls_raw.extend(m["tool_calls"])

            assistant_msg = {"role": "assistant", "content": assembled}
            if tool_calls_raw:
                assistant_msg["tool_calls"] = tool_calls_raw
            messages.append(assistant_msg)

            known_tools = {t["name"] for t in build_assistant_tools()}

            # Salvage a tool call that the model leaked as plain-text JSON.
            if not tool_calls_raw:
                leak = _maybe_leaked_tool(assembled)
                if leak:
                    name, args = leak
                    yield _ndjson({"type": "replace", "text": ""})  # clear the JSON
                    if name in known_tools:
                        tool_calls_raw = [{"function": {"name": name, "arguments": args}}]
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": "That tool does not exist. Answer the question in plain English using the information already provided. Do not output JSON.",
                            }
                        )
                        continue

            if not tool_calls_raw:
                break

            tool_calls = []
            for tc in tool_calls_raw:
                fn = tc.get("function", {}) or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append((None, fn.get("name"), _coerce_args(args or {})))

            results, _ = _dispatch_tool_calls(tool_calls, current_ts, actions)
            for _cid, out in results:
                messages.append({"role": "tool", "content": out})
    except urllib.error.URLError as e:
        yield _ndjson(
            {"type": "error", "detail": f"Couldn't reach Ollama at {base_url} — is it running? ({e})"}
        )
        return
    except Exception as e:
        yield _ndjson({"type": "error", "detail": f"Ollama assistant failed: {str(e)}"})
        return

    yield _ndjson({"type": "actions", "actions": actions})
    yield _ndjson({"type": "done"})


@app.post("/assistant-stream")
def assistant_stream(req: AssistantRequest):
    ctx = req.context or {}
    quick = _quick_answer(req.message, ctx)

    if quick is not None:
        def quick_gen():
            yield _ndjson({"type": "delta", "text": quick})
            yield _ndjson({"type": "actions", "actions": []})
            yield _ndjson({"type": "done"})

        return StreamingResponse(quick_gen(), media_type="application/x-ndjson")

    system, current_ts = _assistant_system(ctx)
    provider = os.environ.get("ASSISTANT_PROVIDER", "ollama-prompt").lower()

    if provider == "ollama":
        return StreamingResponse(
            _stream_ollama(system, req.message, current_ts),
            media_type="application/x-ndjson",
        )

    # Default: prompt-based mode (works with any local Ollama model). It is
    # non-streaming, so emit the final reply as a single chunk.
    def prompt_gen():
        result = _assistant_ollama_prompt(system, req.message, current_ts)
        yield _ndjson({"type": "delta", "text": result["reply"]})
        yield _ndjson({"type": "actions", "actions": result["actions"]})
        yield _ndjson({"type": "done"})

    return StreamingResponse(prompt_gen(), media_type="application/x-ndjson")


@app.post("/assistant")
def assistant(req: AssistantRequest):
    ctx = req.context or {}
    quick = _quick_answer(req.message, ctx)
    if quick is not None:
        return {"reply": quick, "actions": []}

    system, current_ts = _assistant_system(ctx)

    provider = os.environ.get("ASSISTANT_PROVIDER", "ollama-prompt").lower()

    if provider == "ollama":
        return _assistant_ollama(system, req.message, current_ts)

    # Default: prompt-based mode (works with any local Ollama model).
    return _assistant_ollama_prompt(system, req.message, current_ts)


# ---------------------------------------------------------------------------
# Dev entrypoint:  python main.py
# Ctrl+C force-exits immediately. We install our OWN signal handlers (and stop
# uvicorn from replacing them) so the process dies instantly instead of getting
# stuck in uvicorn's graceful shutdown — which can hang on open streaming
# connections, the warmup thread, or CUDA/CTranslate2 teardown on Windows.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import signal

    import uvicorn

    def _force_exit(*_):
        os._exit(0)

    for _sig in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK = Windows Ctrl+Break
        s = getattr(signal, _sig, None)
        if s is not None:
            try:
                signal.signal(s, _force_exit)
            except Exception:
                pass

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(app, host=host, port=port, timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    # Keep our force-exit handlers (uvicorn would otherwise install its own
    # graceful-shutdown handlers that can hang).
    server.install_signal_handlers = lambda: None
    server.run()
