from fastapi import APIRouter

from services.dataset_service import dataset_service

router = APIRouter()

@router.get("/metadata")
def metadata():

    ds = dataset_service.get_dataset()

    return {
        "variables": list(ds.data_vars),
        "dimensions": dict(ds.dims),
        "coordinates": list(ds.coords)
    }