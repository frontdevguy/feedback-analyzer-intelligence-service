# Import all models here to ensure they are registered with SQLAlchemy
# This is important for Alembic to detect all models

from src.models.user import User
from src.models.feedback import Feedback
from src.models.job import Job
from src.models.job_config import JobConfig
from src.models.topic import Topic

__all__ = ["User", "Feedback", "Job", "JobConfig", "Topic"]
