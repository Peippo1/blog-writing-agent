from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import current_user, scheduler_authorized
from .config import Settings, get_settings
from .schemas import (
    Article, ArticleCreate, ArticleStatus, ArticleUpdate, ExportDocument, PublishingJob,
    PublishingStatus, QueueReleaseRequest, SchedulerRequest, Suggestion, SuggestionRequest,
)
from .services import ContentGenerator, GitHubPublisher, article_url, github_signature_valid, slugify, live_url_exists
from .store import FirestoreStore, MemoryStore


class LimitBodyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        length = request.headers.get("content-length")
        if length and int(length) > settings.request_max_bytes:
            return Response(status_code=413, content="Request body is too large")
        return await call_next(request)


def now() -> datetime:
    return datetime.now(UTC)


def create_app(store: MemoryStore | None = None, generator: ContentGenerator | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Publishing Studio", docs_url=None if settings.is_production else "/docs", redoc_url=None if settings.is_production else "/redoc")
    if store:
        app.state.store = store
    elif settings.is_production:
        if not settings.firebase_project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is required in production")
        app.state.store = FirestoreStore(settings.firebase_project_id)
    else:
        app.state.store = MemoryStore()
    app.state.generator = generator or ContentGenerator()
    app.add_middleware(LimitBodyMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts if settings.is_production else ["*"])
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    protected = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

    def user(request: Request) -> str:
        # The dependency resolution caches the verified user for this request.
        return request.scope.get("state", {}).get("user", "")

    async def owner(identity: str = Depends(current_user)) -> str:
        return identity

    @protected.get("/articles", response_model=list[Article])
    async def list_articles(identity: str = Depends(owner)):
        return app.state.store.list_articles(identity)

    @protected.post("/articles", response_model=Article, status_code=status.HTTP_201_CREATED)
    async def create_article(payload: ArticleCreate, identity: str = Depends(owner)):
        timestamp = now()
        title = payload.brief.topic.strip()
        article = Article(owner_id=identity, brief=payload.brief, title=title, slug=slugify(title), summary=payload.brief.topic, created_at=timestamp, updated_at=timestamp)
        return app.state.store.create_article(article)

    @protected.get("/articles/{article_id}", response_model=Article)
    async def get_article(article_id: UUID, identity: str = Depends(owner)):
        return app.state.store.article(article_id, identity)

    @protected.patch("/articles/{article_id}", response_model=Article)
    async def update_article(article_id: UUID, payload: ArticleUpdate, identity: str = Depends(owner)):
        article = app.state.store.article(article_id, identity)
        return app.state.store.update_article(article, **payload.model_dump(exclude_unset=True))

    @protected.post("/articles/{article_id}/outline", response_model=Article)
    async def generate_outline(article_id: UUID, identity: str = Depends(owner)):
        article = app.state.store.article(article_id, identity)
        return app.state.store.update_article(article, outline=app.state.generator.outline(article), status=ArticleStatus.OUTLINE_READY)

    @protected.post("/articles/{article_id}/draft", response_model=Article)
    async def generate_draft(article_id: UUID, identity: str = Depends(owner)):
        article = app.state.store.article(article_id, identity)
        if not article.outline:
            raise HTTPException(status_code=409, detail="Generate and review an outline before drafting")
        return app.state.store.update_article(article, markdown=app.state.generator.draft(article), status=ArticleStatus.DRAFT_READY)

    @protected.post("/articles/{article_id}/suggestions", response_model=Suggestion)
    async def create_suggestion(article_id: UUID, payload: SuggestionRequest, identity: str = Depends(owner)):
        app.state.store.article(article_id, identity)
        return app.state.generator.suggestion(payload.action, payload.selected_text, payload.instruction)

    @protected.get("/articles/{article_id}/publishing-kit")
    async def publishing_kit(article_id: UUID, identity: str = Depends(owner)):
        article = app.state.store.article(article_id, identity)
        if not article.markdown:
            raise HTTPException(status_code=409, detail="Draft the article before generating a publishing kit")
        return app.state.generator.publishing_kit(article)

    @protected.get("/articles/{article_id}/export", response_model=ExportDocument)
    async def export_article(article_id: UUID, identity: str = Depends(owner)):
        from .services import front_matter
        article = app.state.store.article(article_id, identity)
        return ExportDocument(filename=f"{article.slug}.md", content=front_matter(article))

    @protected.post("/articles/{article_id}/queue", response_model=PublishingJob, status_code=status.HTTP_201_CREATED)
    async def queue_article(article_id: UUID, payload: QueueReleaseRequest, identity: str = Depends(owner)):
        settings = get_settings()
        article = app.state.store.article(article_id, identity)
        if not article.outline or not article.markdown or not article.title or not article.summary:
            raise HTTPException(status_code=409, detail="An approved outline, draft, title, and summary are required before queueing")
        if payload.scheduled_for.tzinfo is None:
            raise HTTPException(status_code=422, detail="scheduled_for must include a timezone")
        if not settings.portfolio_repository:
            raise HTTPException(status_code=503, detail="PORTFOLIO_REPOSITORY is not configured")
        timestamp = now()
        job = PublishingJob(article_id=article.id, owner_id=identity, scheduled_for=payload.scheduled_for.astimezone(UTC), repository=settings.portfolio_repository, created_at=timestamp, updated_at=timestamp)
        app.state.store.update_article(article, status=ArticleStatus.QUEUED)
        return app.state.store.queue_job(job)

    @protected.get("/publishing-jobs", response_model=list[PublishingJob])
    async def list_jobs(identity: str = Depends(owner)):
        return app.state.store.jobs_for_owner(identity)

    @protected.get("/publishing-jobs/{job_id}", response_model=PublishingJob)
    async def get_job(job_id: UUID, identity: str = Depends(owner)):
        return app.state.store.job(job_id, identity)

    @protected.post("/publishing-jobs/{job_id}/linkedin", response_model=PublishingJob)
    async def generate_linkedin(job_id: UUID, identity: str = Depends(owner)):
        settings = get_settings()
        job = app.state.store.job(job_id, identity)
        if job.status not in {PublishingStatus.LIVE, PublishingStatus.LINKEDIN_POSTED}:
            raise HTTPException(status_code=409, detail="The portfolio article must be live before generating LinkedIn copy")
        article = app.state.store.article(job.article_id, identity)
        return app.state.store.update_job(job, linkedin_package=app.state.generator.linkedin(settings, article))

    @protected.post("/publishing-jobs/{job_id}/linkedin-posted", response_model=PublishingJob)
    async def linkedin_posted(job_id: UUID, identity: str = Depends(owner)):
        job = app.state.store.job(job_id, identity)
        if not job.linkedin_package:
            raise HTTPException(status_code=409, detail="Generate the LinkedIn package before marking it posted")
        article = app.state.store.article(job.article_id, identity)
        app.state.store.update_article(article, status=ArticleStatus.LINKEDIN_POSTED)
        return app.state.store.update_job(job, status=PublishingStatus.LINKEDIN_POSTED)

    app.include_router(protected)

    @app.post("/internal/scheduler/run", dependencies=[Depends(scheduler_authorized)], response_model=PublishingJob | None)
    async def scheduler_run(payload: SchedulerRequest):
        job = app.state.store.due_job(payload.release_id)
        if not job:
            return None
        settings = get_settings()
        article = app.state.store.article(job.article_id, job.owner_id)
        try:
            branch, pr_number, pr_url = await GitHubPublisher(settings).open_pull_request(article, job.id)
        except HTTPException:
            raise
        except Exception:
            app.state.store.update_job(job, status=PublishingStatus.FAILED, error_code="github_pr_failed")
            raise HTTPException(status_code=502, detail="Could not open portfolio pull request")
        app.state.store.update_article(article, status=ArticleStatus.PR_OPEN)
        return app.state.store.update_job(job, status=PublishingStatus.PR_OPEN, branch_name=branch, pr_number=pr_number, pr_url=pr_url)

    @app.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
    async def github_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None)):
        settings = get_settings()
        body = await request.body()
        if not github_signature_valid(settings.github_webhook_secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        payload = json.loads(body)
        if request.headers.get("X-GitHub-Event") != "pull_request" or payload.get("action") != "closed":
            return {"accepted": True}
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {}).get("full_name")
        if not pr.get("merged") or repo != settings.portfolio_repository:
            return {"accepted": True}
        job = app.state.store.job_for_pr(repo, pr.get("number"))
        if not job or job.status in {PublishingStatus.LIVE, PublishingStatus.LINKEDIN_POSTED}:
            return {"accepted": True}
        article = app.state.store.article(job.article_id, job.owner_id)
        url = article_url(settings, article)
        if not await live_url_exists(url):
            app.state.store.update_job(job, status=PublishingStatus.MERGED)
            return {"accepted": True, "live": False}
        app.state.store.update_article(article, status=ArticleStatus.LIVE)
        app.state.store.update_job(job, status=PublishingStatus.LIVE, live_url=url)
        return {"accepted": True, "live": True}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    # The Docker image places the Vite production build here. Static content is
    # built by this service, not user-uploaded, and API routes were registered first.
    static_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app


app = create_app()
