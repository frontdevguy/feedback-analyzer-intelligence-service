from sqlalchemy import Column, BigInteger, String, DateTime, JSON
from sqlalchemy.sql import func
from src.database.config import Base


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(BigInteger, primary_key=True, index=True)
    sender_id = Column(String, index=True)
    product_name = Column(String)
    feedback_text = Column(String)
    media_urls = Column(JSON, nullable=True, default=lambda: [])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
