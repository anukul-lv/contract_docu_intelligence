"""API route aggregation.

All route modules register their routers here.
Imported by app.py to mount on the FastAPI application.
"""
from fastapi import APIRouter

from backend.routes.documents import router as documents_router
from backend.routes.extraction import router as extraction_router
from backend.routes.review import router as review_router
from backend.routes.explorer import router as explorer_router
from backend.routes.settings import router as settings_router
from backend.routes.admin import router as admin_router
from backend.routes.chat import router as chat_router
from backend.routes.provenance import router as provenance_router

api_router = APIRouter(prefix="/api")

# R1_04: Document intake
api_router.include_router(documents_router)

# R1_05: Extraction pipeline
api_router.include_router(extraction_router)

# R1_06: Review workbench
api_router.include_router(review_router)

# R1_07: Contract explorer
api_router.include_router(explorer_router)

# R1_08: Settings and admin
api_router.include_router(settings_router)
api_router.include_router(admin_router)

# R2_04: Chat API
api_router.include_router(chat_router)

# R2_05: Provenance / amendment engine
api_router.include_router(provenance_router)
