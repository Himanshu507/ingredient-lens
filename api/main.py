from fastapi import FastAPI

app = FastAPI(title="Regulatory Intelligence Engine")


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Regulatory Intelligence Engine"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
