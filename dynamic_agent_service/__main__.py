import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from dotenv import load_dotenv
load_dotenv()

from dynamic_agent_service.util.setup_logging import my_logger_setup, get_my_logger
my_logger_setup()

from dynamic_agent_service.service.service_router import router as session_router
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine


logger = get_my_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing external services...")
    await PgInstance.initialize()
    logger.info("PgInstance initialized")
    MilvusInstance.initialize()
    logger.info("MilvusInstance initialized")
    KnowledgeEngine.initialize()
    logger.info("KnowledgeEngine initialized")

    yield

    # Shutdown
    logger.info("Closing external services...")
    await PgInstance.close()
    logger.info("Services closed")

app = FastAPI(lifespan=lifespan)
app.include_router(session_router)

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
