from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import logging
from pydantic import BaseModel
from sqlalchemy.orm import Session
from src.database.config import get_db

router = APIRouter()
router.config = {}
router.services = {}

logging.basicConfig(level=logging.INFO)

def verify_api_secret(
    x_intelligence_api_secret: Optional[str] = Header(
        default=None, convert_underscores=True
    ),
):
    expected_secret = router.config.get("INTELLIGENCE_API_SECRET")

    if not expected_secret:
        raise HTTPException(status_code=500, detail="Server configuration error")

    if x_intelligence_api_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# Define a model for the request body
class ReplyRequest(BaseModel):
    sender_id: str
    message: str


@router.post("/", dependencies=[Depends(verify_api_secret)])
async def reply_user(request: ReplyRequest, db: Session = Depends(get_db)):
    try:
        logging.info(f"Received request to reply to user {request.sender_id}")
        chat_service = router.services["chat_service"]
        chat_service.db = db  # Inject the database session
        await chat_service.reply_user(request.sender_id)

        return {"message": "Reply sent successfully."}
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred")
