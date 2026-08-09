from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.routers import categories, dashboards, ladder_tiers, payroll, ratings, shifts, supervisor_channels

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="ЗДР KPI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router)
app.include_router(dashboards.router)
app.include_router(ladder_tiers.router)
app.include_router(payroll.router)
app.include_router(ratings.router)
app.include_router(shifts.router)
app.include_router(supervisor_channels.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/info")
async def root():
    return {
        "service": "ЗДР KPI Backend",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")
