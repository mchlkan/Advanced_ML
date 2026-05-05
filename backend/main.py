from fastapi import FastAPI
from backend.routes import upload, publish, verify

app = FastAPI(title="Resell Copilot API")

app.include_router(upload.router)
app.include_router(publish.router)
app.include_router(verify.router)
