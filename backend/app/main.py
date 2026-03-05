from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import upload, forecast

app = FastAPI(
    title="Market Pulse",
    description="Smart forecasting engine for sellers",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://market-pulse.vercel.app",
        "https://market-pulse-*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(forecast.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "market-pulse"}
