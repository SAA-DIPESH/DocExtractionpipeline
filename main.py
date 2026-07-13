from fastapi import FastAPI

from app.api.routes.document_extractor_router import router

app = FastAPI(
    title="Document Extraction API",
    version="1.0.0"
)

app.include_router(router)