from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class DtoModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UserResponse(DtoModel):
    name: str
    email: str
    role: str


class AuthResponse(DtoModel):
    token: str
    user: UserResponse


class LoginRequest(DtoModel):
    email: EmailStr
    password: str


class PortfolioSiteResponse(DtoModel):
    id: int
    site_url: str
    screenshot_url: str
    display_order: int


class PortfolioReorderRequest(DtoModel):
    ordered_ids: list[int]


class WebsiteRequestCreate(DtoModel):
    customer_name: str
    customer_email: EmailStr
    customer_phone: str
    project_description: str
    target_date: str
    budget_range: str


class WebsiteRequestCommentCreate(DtoModel):
    body: str


class WebsiteRequestStatusUpdate(DtoModel):
    status: str


class WebsiteRequestCommentResponse(DtoModel):
    id: int
    author_role: str
    body: str
    created_at: datetime
    updated_at: datetime


class WebsiteRequestResponse(DtoModel):
    request_number: str
    customer_name: str
    customer_email: str
    customer_phone: str
    project_description: str
    target_date: str
    budget_range: str
    status: str
    created_at: datetime
    updated_at: datetime
    viewer_is_admin: bool
    comments: list[WebsiteRequestCommentResponse]
