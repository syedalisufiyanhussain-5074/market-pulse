import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import upload, forecast

REQUEST_TIMEOUT_SECONDS = 120

app = FastAPI(
    title="Market Pulse",
    description="Smart forecasting engine for sellers",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"detail": "Request timed out. Try a smaller dataset or coarser time granularity."},
        )

app.include_router(upload.router)
app.include_router(forecast.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "market-pulse"}
