from fastapi import FastAPI

from api.routers import ingredients, products, recalls, warnings

app = FastAPI(title="Regulatory Intelligence Engine")

app.include_router(ingredients.router)
app.include_router(products.router)
app.include_router(warnings.router)
app.include_router(recalls.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Regulatory Intelligence Engine"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
