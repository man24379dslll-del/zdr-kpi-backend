from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import categories, payroll, ratings, shifts, supervisor_channels

app = FastAPI(title="ЗДР KPI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router)
app.include_router(payroll.router)
app.include_router(ratings.router)
app.include_router(shifts.router)
app.include_router(supervisor_channels.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "ЗДР KPI Backend",
        "docs": "/docs",
        "health": "/health",
    }
