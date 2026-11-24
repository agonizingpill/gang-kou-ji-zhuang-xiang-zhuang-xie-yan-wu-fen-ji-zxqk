import logging, os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .casework_routes import router as operational_cases
from .operations_evidence import router as operations_evidence
from .database import Base, engine
from .routes import router
from scripts.seed_demo import seed

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if os.getenv("SEED_DEMO", "true").lower() == "true":
        seed()
    yield

app = FastAPI(title="Container Delay Triage", version="1.0.0", lifespan=lifespan)
app.include_router(operational_cases)
app.include_router(operations_evidence)
app.include_router(router)

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "container-delay-backend"}

@app.exception_handler(Exception)
async def handle_error(request: Request, exc: Exception):
    logging.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "服务内部错误"})
