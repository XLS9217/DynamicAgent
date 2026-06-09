import traceback
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
load_dotenv()

from dynamic_agent_service.util.setup_logging import my_logger_setup, get_my_logger
my_logger_setup()

from dynamic_agent_service.service.service_router import router as session_router
from dynamic_agent_service.service.monitor_router import router as monitor_router
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.redis_instance import RedisInstance


logger = get_my_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing external services...")
    await PgInstance.initialize()
    logger.info("PgInstance initialized")
    MilvusInstance.initialize()
    logger.info("MilvusInstance initialized")
    await KnowledgeEngine.initialize()
    logger.info("KnowledgeEngine initialized")
    await RedisInstance.initialize()
    logger.info("RedisInstance initialized")

    yield

    # Shutdown
    logger.info("Closing external services...")
    await PgInstance.close()
    await RedisInstance.close()
    logger.info("Services closed")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(monitor_router)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}:\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    logger.info("Starting Dynamic Agent Service")
    uvicorn.run(
        "dynamic_agent_service.__main__:app",
        host="0.0.0.0",
        port=7777,
        reload=True
    )
