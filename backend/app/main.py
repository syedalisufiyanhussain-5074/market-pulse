from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import APP_VERSION
from app.routers import upload, forecast


class SessionIDMiddleware(BaseHTTPMiddleware):
    """Extract X-Session-ID header and attach to request.state."""
    async def dispatch(self, request: Request, call_next):
        request.state.session_id = request.headers.get("X-Session-ID")
        return await call_next(request)

app = FastAPI(
    title="Market Pulse",
    description="Smart forecasting engine for sellers",
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionIDMiddleware)

app.include_router(upload.router)
app.include_router(forecast.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "market-pulse", "version": APP_VERSION}
