from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib

import boto3
from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD, AWS_REGION, JWT_SECRET, MAIL_PASSWORD, MAIL_PORT, MAIL_SERVER, MAIL_USERNAME, PUBLIC_APP_BASE_URL, S3_BUCKET, SessionLocal
from app.dto import AuthResponse, LoginRequest, PortfolioReorderRequest, PortfolioSiteResponse, UserResponse, WebsiteRequestCommentCreate, WebsiteRequestCommentResponse, WebsiteRequestCreate, WebsiteRequestResponse, WebsiteRequestStatusUpdate
from app.models import ROLE_ADMIN, ROLE_CUSTOMER, STATUS_SUBMITTED, PortfolioSite, RequestStatus, Role, WebsiteRequest, WebsiteRequestComment


router = APIRouter()


def get_role(session: Session, name: str) -> Role:
    role = session.scalar(select(Role).where(Role.name == name))
    if not role:
        raise HTTPException(status_code=500, detail=f"Role '{name}' is not configured.")
    return role


def get_status(session: Session, name: str) -> RequestStatus:
    status = session.scalar(select(RequestStatus).where(RequestStatus.name == name))
    if not status:
        raise HTTPException(status_code=400, detail="Unknown request status.")
    return status


def build_admin_response() -> UserResponse:
    return UserResponse(name=ADMIN_NAME or "David", email=ADMIN_EMAIL, role=ROLE_ADMIN)


def get_current_admin(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc
    if payload.get("sub") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return True


def viewer_is_admin(authorization: str | None) -> bool:
    try:
        return get_current_admin(authorization)
    except HTTPException:
        return False


def build_screenshot_url(site: PortfolioSite) -> str:
    if not site.screenshot_s3_key or not S3_BUCKET or not AWS_REGION:
        return site.screenshot_url
    return boto3.client("s3", region_name=AWS_REGION).generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": site.screenshot_s3_key}, ExpiresIn=3600)


def build_site_response(site: PortfolioSite) -> PortfolioSiteResponse:
    return PortfolioSiteResponse(id=site.id, site_url=site.site_url, screenshot_url=build_screenshot_url(site), display_order=site.display_order)


def build_request_response(session: Session, request: WebsiteRequest, is_admin: bool) -> WebsiteRequestResponse:
    comments = session.scalars(select(WebsiteRequestComment).where(WebsiteRequestComment.website_request_id == request.id).order_by(WebsiteRequestComment.created_at, WebsiteRequestComment.id)).all()
    return WebsiteRequestResponse(
        request_number=request.request_number,
        customer_name=request.customer_name,
        customer_email=request.customer_email,
        customer_phone=request.customer_phone,
        project_description=request.project_description,
        target_date=request.target_date,
        budget_range=request.budget_range,
        status=request.status.name,
        created_at=request.created_at,
        updated_at=request.updated_at,
        viewer_is_admin=is_admin,
        comments=[WebsiteRequestCommentResponse(id=comment.id, author_role=comment.author_role.name, body=comment.body, created_at=comment.created_at, updated_at=comment.updated_at) for comment in comments],
    )


def new_request_number(session: Session) -> str:
    while True:
        request_number = f"{secrets.randbelow(1_000_000):06d}"
        if not session.scalar(select(WebsiteRequest.id).where(WebsiteRequest.request_number == request_number)):
            return request_number


def send_email(recipient: str, subject: str, body: str) -> None:
    if not recipient or not MAIL_SERVER or not MAIL_USERNAME:
        return
    message = EmailMessage()
    message["From"] = MAIL_USERNAME
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
        server.starttls()
        if MAIL_PASSWORD:
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(message)


def send_request_created_emails(request: WebsiteRequest) -> None:
    request_url = f"{PUBLIC_APP_BASE_URL}/request/{request.request_number}"
    customer_body = f"Hi {request.customer_name},\n\nYour website request is in. You can view its status and message David here:\n{request_url}\n\nDavid"
    admin_body = f"A new website request came in from {request.customer_name}.\n\nOpen it here:\n{request_url}"
    try:
        send_email(request.customer_email, "Your website request", customer_body)
        send_email(ADMIN_EMAIL, f"New website request: {request.request_number}", admin_body)
    except Exception:
        return


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/portfolio", response_model=list[PortfolioSiteResponse])
def list_portfolio():
    with SessionLocal() as session:
        sites = session.scalars(select(PortfolioSite).order_by(PortfolioSite.display_order, PortfolioSite.id)).all()
        return [build_site_response(site) for site in sites]


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    if not ADMIN_EMAIL or not ADMIN_PASSWORD or payload.email.lower() != ADMIN_EMAIL.lower() or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = jwt.encode({"sub": ROLE_ADMIN, "exp": datetime.now(timezone.utc) + timedelta(days=365)}, JWT_SECRET, algorithm="HS256")
    return AuthResponse(token=token, user=build_admin_response())


@router.get("/auth/validate-token", response_model=UserResponse)
def validate_token(authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    return build_admin_response()


@router.get("/admin/portfolio", response_model=list[PortfolioSiteResponse])
def list_admin_portfolio(authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    return list_portfolio()


@router.post("/admin/portfolio", response_model=PortfolioSiteResponse)
async def create_portfolio_site(site_url: str = Form(), screenshot: UploadFile = File(), authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    if not site_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Site URL must start with http:// or https://.")
    if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Screenshot must be an image.")
    if not S3_BUCKET or not AWS_REGION:
        raise HTTPException(status_code=500, detail="S3_BUCKET and AWS_REGION are required for screenshot uploads.")
    with SessionLocal() as session:
        next_order = (session.scalar(select(PortfolioSite.display_order).order_by(PortfolioSite.display_order.desc())) or 0) + 10
        key = f"portfolio/{secrets.token_hex(16)}-{screenshot.filename or 'screenshot'}"
        boto3.client("s3", region_name=AWS_REGION).upload_fileobj(screenshot.file, S3_BUCKET, key, ExtraArgs={"ContentType": screenshot.content_type})
        site = PortfolioSite(site_url=site_url.strip(), screenshot_url="", screenshot_s3_key=key, display_order=next_order)
        session.add(site)
        session.commit()
        session.refresh(site)
        return build_site_response(site)


@router.patch("/admin/portfolio/{site_id}", response_model=PortfolioSiteResponse)
async def update_portfolio_site(site_id: int, site_url: str = Form(), screenshot: UploadFile | None = File(default=None), authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    if not site_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Site URL must start with http:// or https://.")
    with SessionLocal() as session:
        site = session.get(PortfolioSite, site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Portfolio site not found.")
        site.site_url = site_url.strip()
        if screenshot:
            if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="Screenshot must be an image.")
            if not S3_BUCKET or not AWS_REGION:
                raise HTTPException(status_code=500, detail="S3_BUCKET and AWS_REGION are required for screenshot uploads.")
            if site.screenshot_s3_key:
                boto3.client("s3", region_name=AWS_REGION).delete_object(Bucket=S3_BUCKET, Key=site.screenshot_s3_key)
            site.screenshot_s3_key = f"portfolio/{secrets.token_hex(16)}-{screenshot.filename or 'screenshot'}"
            boto3.client("s3", region_name=AWS_REGION).upload_fileobj(screenshot.file, S3_BUCKET, site.screenshot_s3_key, ExtraArgs={"ContentType": screenshot.content_type})
        session.commit()
        session.refresh(site)
        return build_site_response(site)


@router.delete("/admin/portfolio/{site_id}")
def delete_portfolio_site(site_id: int, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        site = session.get(PortfolioSite, site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Portfolio site not found.")
        if site.screenshot_s3_key and S3_BUCKET and AWS_REGION:
            boto3.client("s3", region_name=AWS_REGION).delete_object(Bucket=S3_BUCKET, Key=site.screenshot_s3_key)
        session.delete(site)
        session.commit()
    return {"status": "deleted"}


@router.post("/admin/portfolio/reorder")
def reorder_portfolio(payload: PortfolioReorderRequest, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        sites = session.scalars(select(PortfolioSite).where(PortfolioSite.id.in_(payload.ordered_ids))).all()
        if len(sites) != len(payload.ordered_ids):
            raise HTTPException(status_code=400, detail="Portfolio list changed. Refresh and try again.")
        for index, site_id in enumerate(payload.ordered_ids):
            next(site for site in sites if site.id == site_id).display_order = (index + 1) * 10
        session.commit()
    return {"status": "saved"}


@router.post("/requests", response_model=WebsiteRequestResponse)
def create_request(payload: WebsiteRequestCreate, background_tasks: BackgroundTasks):
    values = [payload.customer_name, payload.customer_phone, payload.project_description, payload.target_date, payload.budget_range]
    if not all(value.strip() for value in values):
        raise HTTPException(status_code=400, detail="All request fields are required.")
    with SessionLocal() as session:
        request = WebsiteRequest(request_number=new_request_number(session), customer_name=payload.customer_name.strip(), customer_email=str(payload.customer_email).lower(), customer_phone=payload.customer_phone.strip(), project_description=payload.project_description.strip(), target_date=payload.target_date.strip(), budget_range=payload.budget_range.strip(), status_id=get_status(session, STATUS_SUBMITTED).id)
        session.add(request)
        session.commit()
        session.refresh(request)
        background_tasks.add_task(send_request_created_emails, request)
        return build_request_response(session, request, False)


@router.get("/admin/requests", response_model=list[WebsiteRequestResponse])
def list_admin_requests(authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        requests = session.scalars(select(WebsiteRequest).order_by(WebsiteRequest.created_at.desc())).all()
        return [build_request_response(session, request, True) for request in requests]


@router.get("/requests/{request_number}", response_model=WebsiteRequestResponse)
def get_request(request_number: str, authorization: str | None = Header(default=None)):
    with SessionLocal() as session:
        request = session.scalar(select(WebsiteRequest).where(WebsiteRequest.request_number == request_number))
        if not request:
            raise HTTPException(status_code=404, detail="Website request not found.")
        return build_request_response(session, request, viewer_is_admin(authorization))


@router.post("/requests/{request_number}/comments", response_model=WebsiteRequestCommentResponse)
def create_comment(request_number: str, payload: WebsiteRequestCommentCreate, authorization: str | None = Header(default=None)):
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Message is required.")
    with SessionLocal() as session:
        request = session.scalar(select(WebsiteRequest).where(WebsiteRequest.request_number == request_number))
        if not request:
            raise HTTPException(status_code=404, detail="Website request not found.")
        role = get_role(session, ROLE_ADMIN if viewer_is_admin(authorization) else ROLE_CUSTOMER)
        comment = WebsiteRequestComment(website_request_id=request.id, author_role_id=role.id, body=payload.body.strip())
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return WebsiteRequestCommentResponse(id=comment.id, author_role=comment.author_role.name, body=comment.body, created_at=comment.created_at, updated_at=comment.updated_at)


@router.post("/admin/requests/{request_number}/status", response_model=WebsiteRequestResponse)
def update_request_status(request_number: str, payload: WebsiteRequestStatusUpdate, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        request = session.scalar(select(WebsiteRequest).where(WebsiteRequest.request_number == request_number))
        if not request:
            raise HTTPException(status_code=404, detail="Website request not found.")
        request.status_id = get_status(session, payload.status).id
        session.commit()
        session.refresh(request)
        return build_request_response(session, request, True)
