import uvicorn
from fastapi import FastAPI

from dotenv import load_dotenv
load_dotenv()

from dynamic_agent_service.util.setup_logging import my_logger_setup, get_my_logger
my_logger_setup()

from dynamic_agent_service.service.service_router import router as session_router



logger = get_my_logger()

app = FastAPI()
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
