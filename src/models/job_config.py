from sqlalchemy import Column, BigInteger, JSON
from src.database.config import Base


class JobConfig(Base):
    __tablename__ = "job_configs"

    id = Column(BigInteger, primary_key=True, index=True)
    config = Column(JSON, nullable=True, server_default="{}")
