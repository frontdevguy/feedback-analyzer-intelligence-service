from fastapi import APIRouter
from src.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    Returns 200 OK with service status.
    """
    return {"status": "healthy"}
