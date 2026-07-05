"""FastAPI routes for the local operations dashboard."""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.dashboard.labels import (
    authority_tier_label,
    job_status_label,
    source_status_label,
    source_type_label,
    verification_label,
)
from ai_media_os.dashboard.queries import DashboardQueries
from ai_media_os.dashboard.security import (
    DashboardSecurityError,
    csrf_token,
    validate_csrf_token,
)
from ai_media_os.domain.job_queue import QueueError
from ai_media_os.infrastructure.database.session import SessionLocal
from ai_media_os.infrastructure.settings import AppSettings, get_settings

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["job_status_label"] = job_status_label
templates.env.filters["source_status_label"] = source_status_label
templates.env.filters["source_type_label"] = source_type_label
templates.env.filters["authority_tier_label"] = authority_tier_label
templates.env.filters["verification_label"] = verification_label

router = APIRouter()


def get_dashboard_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DashboardSession = Annotated[Session, Depends(get_dashboard_session)]


def template_context(
    request: Request,
    *,
    settings: AppSettings | None = None,
    error: str | None = None,
    success: str | None = None,
) -> dict[str, object]:
    resolved = settings or get_settings()
    return {
        "request": request,
        "csrf_token": csrf_token(resolved),
        "poll_seconds": resolved.dashboard_poll_seconds,
        "error": error or request.query_params.get("error"),
        "success": success or request.query_params.get("success"),
    }


def request_settings(request: Request) -> AppSettings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, AppSettings) else get_settings()


def validate_project_id(project_id: str) -> str:
    try:
        return str(UUID(project_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: DashboardSession) -> HTMLResponse:
    settings = request_settings(request)
    queries = DashboardQueries(session, settings)
    context = template_context(request, settings=settings)
    context["home"] = queries.home()
    return templates.TemplateResponse(request, "dashboard/home.html", context)


@router.get("/projects", response_class=HTMLResponse)
def projects(
    request: Request,
    session: DashboardSession,
    filter: str = "all",
) -> HTMLResponse:
    settings = request_settings(request)
    queries = DashboardQueries(session, settings)
    context = template_context(request, settings=settings)
    context["projects"] = queries.projects(filter)
    context["active_filter"] = filter
    return templates.TemplateResponse(request, "dashboard/projects.html", context)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(
    request: Request,
    project_id: str,
    session: DashboardSession,
) -> HTMLResponse:
    project_key = validate_project_id(project_id)
    settings = request_settings(request)
    queries = DashboardQueries(session, settings)
    project = queries.project(project_key)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    context = template_context(request, settings=settings)
    context["project"] = project
    context["item"] = queries.project_list_item(project)
    context["stages"] = queries.stage_statuses_for_project(project)
    context["activity"] = queries.activity(project_id=project.id, limit=12)
    context["recent_jobs"] = [queries.job_item(job) for job in project.jobs[:8]]
    context["pending_approvals"] = [
        queries.approval_item(approval)
        for approval in project.approvals
        if approval.status.value == "pending"
    ]
    context["research"] = queries.research_view(project)
    return templates.TemplateResponse(request, "dashboard/project_detail.html", context)


@router.get("/projects/{project_id}/research", response_class=HTMLResponse)
def project_research(
    request: Request,
    project_id: str,
    session: DashboardSession,
) -> HTMLResponse:
    project_key = validate_project_id(project_id)
    settings = request_settings(request)
    queries = DashboardQueries(session, settings)
    project = queries.project(project_key)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    context = template_context(request, settings=settings)
    context["project"] = project
    context["research"] = queries.research_view(project)
    return templates.TemplateResponse(request, "dashboard/research.html", context)


@router.get("/approvals", response_class=HTMLResponse)
def approvals(request: Request, session: DashboardSession) -> HTMLResponse:
    settings = request_settings(request)
    context = template_context(request, settings=settings)
    context["approvals"] = DashboardQueries(session, settings).approvals()
    return templates.TemplateResponse(request, "dashboard/approvals.html", context)


@router.post("/approvals/{approval_id}/{action}")
def approval_action(
    request: Request,
    approval_id: str,
    action: str,
    session: DashboardSession,
    csrf: str = Form(...),
    feedback: str | None = Form(None),
) -> RedirectResponse:
    try:
        validate_csrf_token(csrf, request_settings(request))
        service = ApprovalService(session)
        if action == "approve":
            service.approve(approval_id, reviewer="dashboard", feedback=feedback)
        elif action == "reject":
            service.reject(approval_id, reviewer="dashboard", feedback=feedback)
        elif action == "request-changes":
            service.request_changes(approval_id, reviewer="dashboard", feedback=feedback)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except DashboardSecurityError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from None
    except ApprovalError as exc:
        return _redirect("/approvals", error=str(exc))
    return _redirect("/approvals", success="Approval updated.")


@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request,
    session: DashboardSession,
    status: str | None = None,
    project_id: str | None = None,
    resource_class: str | None = None,
    job_type: str | None = None,
) -> HTMLResponse:
    settings = request_settings(request)
    queries = DashboardQueries(session, settings)
    context = template_context(request, settings=settings)
    context["groups"] = queries.jobs(
        status=status,
        project_id=project_id,
        resource_class=resource_class,
        job_type=job_type,
    )
    context["filters"] = {
        "status": status or "",
        "project_id": project_id or "",
        "resource_class": resource_class or "",
        "job_type": job_type or "",
    }
    return templates.TemplateResponse(request, "dashboard/jobs.html", context)


@router.post("/jobs/{job_id}/{action}")
def job_action(
    request: Request,
    job_id: str,
    action: str,
    session: DashboardSession,
    csrf: str = Form(...),
) -> RedirectResponse:
    try:
        validate_csrf_token(csrf, request_settings(request))
        service = QueueService(session)
        if action == "cancel":
            service.cancel_job(job_id)
        elif action == "pause":
            service.pause_job(job_id)
        elif action == "resume":
            service.resume_job(job_id)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except DashboardSecurityError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from None
    except QueueError as exc:
        return _redirect("/jobs", error=str(exc))
    return _redirect("/jobs", success="Job updated.")


@router.get("/ui/fragments/status-counters", response_class=HTMLResponse)
def status_counters(
    request: Request,
    session: DashboardSession,
) -> HTMLResponse:
    settings = request_settings(request)
    context = template_context(request, settings=settings)
    context["home"] = DashboardQueries(session, settings).home()
    return templates.TemplateResponse(request, "dashboard/fragments/status_counters.html", context)


@router.get("/ui/fragments/running-jobs", response_class=HTMLResponse)
def running_jobs(
    request: Request,
    session: DashboardSession,
) -> HTMLResponse:
    settings = request_settings(request)
    context = template_context(request, settings=settings)
    context["groups"] = DashboardQueries(session, settings).jobs(status="RUNNING")
    return templates.TemplateResponse(request, "dashboard/fragments/running_jobs.html", context)


@router.get("/ui/fragments/pending-approvals", response_class=HTMLResponse)
def pending_approvals(
    request: Request,
    session: DashboardSession,
) -> HTMLResponse:
    settings = request_settings(request)
    context = template_context(request, settings=settings)
    context["approvals"] = DashboardQueries(session, settings).approvals()
    return templates.TemplateResponse(
        request, "dashboard/fragments/pending_approvals.html", context
    )


@router.get("/ui/fragments/activity", response_class=HTMLResponse)
def activity_fragment(
    request: Request,
    session: DashboardSession,
) -> HTMLResponse:
    settings = request_settings(request)
    context = template_context(request, settings=settings)
    context["activity"] = DashboardQueries(session, settings).activity(limit=12)
    return templates.TemplateResponse(request, "dashboard/fragments/activity.html", context)


def _redirect(
    path: str, *, error: str | None = None, success: str | None = None
) -> RedirectResponse:
    if error:
        path = f"{path}?{urlencode({'error': error})}"
    elif success:
        path = f"{path}?{urlencode({'success': success})}"
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)
