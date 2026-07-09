import xarray as xr

class DatasetService:

    def __init__(self):
        self.ds = None

    def load_dataset(self, path):
        self.ds = xr.open_dataset(
            path,
            engine="netcdf4",
            chunks={
                "Time": 1,
                "south_north": 200,
                "west_east": 200
            }
        )

        return {
            "variables": list(self.ds.data_vars),
            "dimensions": dict(self.ds.dims)
        }

    def get_dataset(self):
        return self.ds

dataset_service = DatasetService()