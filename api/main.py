from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers import ask, ingredients, observability, products, recalls, warnings

app = FastAPI(title="Regulatory Intelligence Engine")

app.include_router(ingredients.router)
app.include_router(products.router)
app.include_router(warnings.router)
app.include_router(recalls.router)
app.include_router(observability.router)
app.include_router(ask.router)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=_FRONTEND_DIR, html=True), name="ui")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Regulatory Intelligence Engine"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
