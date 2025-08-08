from sqlalchemy import Column, BigInteger, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from src.database.config import Base


class Topic(Base):
    __tablename__ = "topics"

    id = Column(BigInteger, primary_key=True, index=True)
    label = Column(String(500), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
