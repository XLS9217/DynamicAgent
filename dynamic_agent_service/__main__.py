import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from dynamic_agent_service.service.session_router import router as session_router

app = FastAPI()
app.include_router(session_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(
        "dynamic_agent_service.__main__:app",
        host="0.0.0.0",
        port=7777,
        reload=True
    )
