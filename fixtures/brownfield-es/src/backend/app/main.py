from fastapi import FastAPI

from app.routes import router
from app.settings import settings

app = FastAPI(title="Conciliación")
app.include_router(router, prefix=settings.API_PREFIX)
