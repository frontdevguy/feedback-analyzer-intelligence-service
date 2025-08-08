from fastapi import FastAPI
from src.routes import setup_routes
from config import get_config
from src.utils.logger import get_logger
from src.services.chat_service import ChatService
import multiprocessing

logger = get_logger(__name__)

config = get_config()
app = FastAPI()

def bootstrap_services():
    return {"chat_service": ChatService(config)}

services = bootstrap_services()

setup_routes(app, config, services)

if __name__ == "__main__":
    import uvicorn

    # Get the number of CPU cores
    workers = multiprocessing.cpu_count()
    # It's recommended to use 2-4 workers per CPU core
    workers = workers * 2

    # Log the number of workers being used
    logger.info(f"Starting server with {workers} workers")

    # Run with multiple workers
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, workers=workers)
