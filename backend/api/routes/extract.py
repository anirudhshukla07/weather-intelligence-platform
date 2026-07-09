from fastapi import APIRouter
from pydantic import BaseModel

from services.extraction_service import extraction_service

router = APIRouter()

class ExtractRequest(BaseModel):
    variable: str
    lat: float
    lon: float
    timestep: int = 0

@router.post("/extract")
def extract(req: ExtractRequest):

    return extraction_service.extract_point(
        req.variable,
        req.lat,
        req.lon,
        req.timestep
    )