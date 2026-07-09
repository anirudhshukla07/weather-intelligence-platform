import numpy as np

from services.dataset_service import dataset_service

class ExtractionService:

    def extract_point(self, variable, lat, lon, timestep=0):

        ds = dataset_service.get_dataset()

        lats = ds["XLAT"].isel(Time=0).values
        lons = ds["XLONG"].isel(Time=0).values

        dist = np.sqrt(
            (lats - lat) ** 2 +
            (lons - lon) ** 2
        )

        iy, ix = np.unravel_index(
            np.argmin(dist),
            dist.shape
        )

        value = (
            ds[variable]
            .isel(Time=timestep)
            .values[iy, ix]
        )

        return {
            "variable": variable,
            "lat": lat,
            "lon": lon,
            "value": float(value),
            "grid_x": int(ix),
            "grid_y": int(iy)
        }

extraction_service = ExtractionService()