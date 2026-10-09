from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


ROLE_CUSTOMER = "customer"
ROLE_ADMIN = "admin"
ROLE_NAMES = [ROLE_CUSTOMER, ROLE_ADMIN]
STATUS_SUBMITTED = "submitted"
STATUS_REVIEWING = "reviewing"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DELIVERED = "delivered"
REQUEST_STATUS_NAMES = [STATUS_SUBMITTED, STATUS_REVIEWING, STATUS_IN_PROGRESS, STATUS_DELIVERED]


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class RequestStatus(Base):
    __tablename__ = "request_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PortfolioSite(Base):
    __tablename__ = "portfolio_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    screenshot_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    screenshot_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebsiteRequest(Base):
    __tablename__ = "website_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_number: Mapped[str] = mapped_column(String(6), nullable=False, unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_phone: Mapped[str] = mapped_column(String(64), nullable=False)
    project_description: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[str] = mapped_column(String(32), nullable=False)
    budget_range: Mapped[str] = mapped_column(String(255), nullable=False)
    status_id: Mapped[int] = mapped_column(ForeignKey("request_statuses.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    status: Mapped[RequestStatus] = relationship()


class WebsiteRequestComment(Base):
    __tablename__ = "website_request_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_request_id: Mapped[int] = mapped_column(ForeignKey("website_requests.id"), nullable=False, index=True)
    author_role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    author_role: Mapped[Role] = relationship()
