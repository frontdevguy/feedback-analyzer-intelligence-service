from sqlalchemy import Column, BigInteger, String, DateTime, JSON, Enum
from sqlalchemy.sql import func
from src.database.config import Base
import enum


class JobStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True, index=True)
    job_name = Column(String, index=True)
    last_processed_id = Column(BigInteger, nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.PROCESSING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
