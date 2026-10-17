from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
import secrets
import smtplib
import logging

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
import jwt
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import ADMIN_EMAIL, ADMIN_NAME, ADMIN_PASSWORD, IMAGE_FOLDER, JWT_SECRET, MAIL_PASSWORD, MAIL_PORT, MAIL_SERVER, MAIL_USERNAME, PUBLIC_APP_BASE_URL, SessionLocal
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


def image_filename(site_id: int) -> str:
    return f"image-{site_id}"


def image_folder() -> Path:
    if not IMAGE_FOLDER:
        raise HTTPException(status_code=500, detail="IMAGE_FOLDER is required for portfolio images.")
    folder = Path(IMAGE_FOLDER).expanduser().resolve()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="IMAGE_FOLDER is not accessible.") from exc
    return folder


def image_path(site_id: int) -> Path:
    return image_folder() / image_filename(site_id)


def image_media_type(path: Path) -> str:
    with path.open("rb") as image:
        header = image.read(1024)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if header.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if header[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if b"<svg" in header.lstrip(b"\xef\xbb\xbf").lower():
        return "image/svg+xml"
    return "application/octet-stream"


def convert_image_to_avif(source_path: Path, destination_path: Path) -> None:
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.save(destination_path, format="AVIF", quality=55, speed=6)


async def save_image(screenshot: UploadFile, site_id: int) -> None:
    destination = image_path(site_id)
    token = secrets.token_hex(8)
    original = destination.with_name(f".{destination.name}-{token}.upload")
    converted = destination.with_name(f".{destination.name}-{token}.avif")
    try:
        with original.open("wb") as output:
            while chunk := await screenshot.read(1024 * 1024):
                output.write(chunk)
        try:
            await run_in_threadpool(convert_image_to_avif, original, converted)
            converted.replace(destination)
            original.unlink(missing_ok=True)
        except Exception:
            logging.getLogger(__name__).warning(
                "AVIF conversion failed for portfolio image %s; storing the original upload.",
                site_id,
                exc_info=True,
            )
            converted.unlink(missing_ok=True)
            original.replace(destination)
    except OSError as exc:
        original.unlink(missing_ok=True)
        converted.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to store portfolio image.") from exc


def build_site_response(site: PortfolioSite, request: Request) -> PortfolioSiteResponse:
    url = request.url_for("get_portfolio_image", filename=image_filename(site.id))
    return PortfolioSiteResponse(id=site.id, name=site.name, site_url=site.site_url, screenshot_url=str(url), display_order=site.display_order)


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


def send_request_update_email(recipient: str, request_number: str, subject: str, detail: str) -> None:
    try:
        send_email(recipient, f"{subject}: {request_number}", f"{detail}\n\nOpen your request:\n{PUBLIC_APP_BASE_URL}/request/{request_number}")
    except Exception:
        logging.getLogger(__name__).exception("Request update email failed for %s", request_number)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/portfolio", response_model=list[PortfolioSiteResponse])
def list_portfolio(request: Request):
    with SessionLocal() as session:
        sites = session.scalars(select(PortfolioSite).order_by(PortfolioSite.display_order, PortfolioSite.id)).all()
        return [build_site_response(site, request) for site in sites]


@router.get("/images/{filename}", name="get_portfolio_image")
def get_portfolio_image(filename: str):
    if not filename.startswith("image-") or not filename.removeprefix("image-").isdigit():
        raise HTTPException(status_code=404, detail="Image not found.")
    path = image_folder() / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(path, media_type=image_media_type(path), filename=filename, content_disposition_type="inline")


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
def list_admin_portfolio(request: Request, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    return list_portfolio(request)


@router.post("/admin/portfolio", response_model=PortfolioSiteResponse)
async def create_portfolio_site(request: Request, name: str = Form(), site_url: str = Form(), screenshot: UploadFile = File(), authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Site name is required.")
    if not site_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Site URL must start with http:// or https://.")
    if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Screenshot must be an image.")
    with SessionLocal() as session:
        next_order = (session.scalar(select(PortfolioSite.display_order).order_by(PortfolioSite.display_order.desc())) or 0) + 10
        site = PortfolioSite(name=name.strip(), site_url=site_url.strip(), display_order=next_order)
        session.add(site)
        session.flush()
        await save_image(screenshot, site.id)
        try:
            session.commit()
        except Exception:
            image_path(site.id).unlink(missing_ok=True)
            raise
        return build_site_response(site, request)


@router.patch("/admin/portfolio/{site_id}", response_model=PortfolioSiteResponse)
async def update_portfolio_site(request: Request, site_id: int, name: str = Form(), site_url: str = Form(), screenshot: UploadFile | None = File(default=None), authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Site name is required.")
    if not site_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Site URL must start with http:// or https://.")
    with SessionLocal() as session:
        site = session.get(PortfolioSite, site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Portfolio site not found.")
        site.name = name.strip()
        site.site_url = site_url.strip()
        if screenshot:
            if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="Screenshot must be an image.")
            await save_image(screenshot, site.id)
        session.commit()
        session.refresh(site)
        return build_site_response(site, request)


@router.delete("/admin/portfolio/{site_id}")
def delete_portfolio_site(site_id: int, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        site = session.get(PortfolioSite, site_id)
        if not site:
            raise HTTPException(status_code=404, detail="Portfolio site not found.")
        image_path(site.id).unlink(missing_ok=True)
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
def create_comment(request_number: str, payload: WebsiteRequestCommentCreate, background_tasks: BackgroundTasks, authorization: str | None = Header(default=None)):
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
        recipient = request.customer_email if role.name == ROLE_ADMIN else ADMIN_EMAIL
        background_tasks.add_task(send_request_update_email, recipient, request.request_number, "New website request message", comment.body)
        return WebsiteRequestCommentResponse(id=comment.id, author_role=comment.author_role.name, body=comment.body, created_at=comment.created_at, updated_at=comment.updated_at)


@router.post("/admin/requests/{request_number}/status", response_model=WebsiteRequestResponse)
def update_request_status(request_number: str, payload: WebsiteRequestStatusUpdate, background_tasks: BackgroundTasks, authorization: str | None = Header(default=None)):
    get_current_admin(authorization)
    with SessionLocal() as session:
        request = session.scalar(select(WebsiteRequest).where(WebsiteRequest.request_number == request_number))
        if not request:
            raise HTTPException(status_code=404, detail="Website request not found.")
        status = get_status(session, payload.status)
        changed = request.status_id != status.id
        request.status_id = status.id
        session.commit()
        session.refresh(request)
        if changed:
            background_tasks.add_task(send_request_update_email, request.customer_email, request.request_number, "Website request status updated", f"Your website request status is now {payload.status.replace('_', ' ')}.")
        return build_request_response(session, request, True)
