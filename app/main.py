from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from sqlalchemy import select

from app.config import CORS_ORIGIN_LIST, SessionLocal, engine
from app.models import Base, REQUEST_STATUS_NAMES, ROLE_NAMES, RequestStatus, Role
from app.routes import router


def sync_bootstrap_lookup_tables() -> None:
    with SessionLocal() as session:
        for model, names in [(Role, ROLE_NAMES), (RequestStatus, REQUEST_STATUS_NAMES)]:
            existing_names = set(session.scalars(select(model.name)).all())
            session.add_all(model(name=name) for name in names if name not in existing_names)
        session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    sync_bootstrap_lookup_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="david-api", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGIN_LIST, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8002, reload=True)
