from fastapi import APIRouter
from pydantic import BaseModel

from services.dataset_service import dataset_service

router = APIRouter()

class LoadRequest(BaseModel):
    file_path: str

@router.post("/load")
def load(req: LoadRequest):
    return dataset_service.load_dataset(req.file_path)