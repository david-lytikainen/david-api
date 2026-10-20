from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from sqlalchemy import inspect, select, text

from app.config import CORS_ORIGIN_LIST, SessionLocal, engine
from app.models import Base, REQUEST_STATUS_NAMES, ROLE_NAMES, RequestStatus, Role
from app.routes import router


def sync_bootstrap_lookup_tables() -> None:
    with SessionLocal() as session:
        for model, names in [(Role, ROLE_NAMES), (RequestStatus, REQUEST_STATUS_NAMES)]:
            existing_names = set(session.scalars(select(model.name)).all())
            session.add_all(model(name=name) for name in names if name not in existing_names)
        session.commit()


def migrate_portfolio_sites() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("portfolio_sites")}
    legacy_columns = ("screenshot_url", "screenshot_s3_key")
    with engine.begin() as connection:
        if "name" not in columns:
            connection.execute(text("ALTER TABLE portfolio_sites ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''"))
        for column in legacy_columns:
            if column in columns:
                connection.execute(text(f"ALTER TABLE portfolio_sites DROP COLUMN {column}"))


def migrate_request_numbers() -> None:
    if engine.dialect.name != "postgresql":
        return
    columns = {column["name"]: column for column in inspect(engine).get_columns("website_requests")}
    if (getattr(columns["request_number"].get("type"), "length", None) or 0) < 13:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE website_requests ALTER COLUMN request_number TYPE VARCHAR(13)"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_portfolio_sites()
    migrate_request_numbers()
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
