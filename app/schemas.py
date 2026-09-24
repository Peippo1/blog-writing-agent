from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArticleStatus(StrEnum):
    BRIEF = "brief"
    OUTLINE_READY = "outline_ready"
    DRAFT_READY = "draft_ready"
    QUEUED = "queued"
    PR_OPEN = "pr_open"
    LIVE = "live"
    LINKEDIN_POSTED = "linkedin_posted"
    ARCHIVED = "archived"


class PublishingStatus(StrEnum):
    QUEUED = "queued"
    PR_OPEN = "pr_open"
    MERGED = "merged"
    LIVE = "live"
    LINKEDIN_POSTED = "linkedin_posted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArticleBrief(StrictModel):
    topic: Annotated[str, Field(min_length=5, max_length=300)]
    audience: Annotated[str, Field(min_length=2, max_length=120)] = "Technical practitioners"
    goal: Annotated[str, Field(min_length=2, max_length=200)] = "Teach a useful idea"
    tone: Annotated[str, Field(min_length=2, max_length=80)] = "Clear and practical"
    target_length: Annotated[int, Field(ge=300, le=8_000)] = 1_200
    keywords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)


class ArticleCreate(StrictModel):
    brief: ArticleBrief


class ArticleUpdate(StrictModel):
    title: Annotated[str, Field(min_length=3, max_length=180)] | None = None
    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)] | None = None
    markdown: Annotated[str, Field(max_length=100_000)] | None = None
    outline: Annotated[str, Field(max_length=30_000)] | None = None
    category: Annotated[str, Field(max_length=80)] | None = None
    summary: Annotated[str, Field(max_length=300)] | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] | None = Field(default=None, max_length=12)


class Article(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    owner_id: str
    brief: ArticleBrief
    title: str = "Untitled article"
    slug: str = "untitled-article"
    category: str = "Applied AI"
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    outline: str = ""
    markdown: str = ""
    status: ArticleStatus = ArticleStatus.BRIEF
    created_at: datetime
    updated_at: datetime


class SuggestionAction(StrEnum):
    EXPAND = "expand"
    REWRITE = "rewrite"
    SHORTEN = "shorten"
    SIMPLIFY = "simplify"
    IMPROVE_SEO = "improve-seo"


class SuggestionRequest(StrictModel):
    action: SuggestionAction
    selected_text: Annotated[str, Field(min_length=1, max_length=20_000)]
    instruction: Annotated[str, Field(max_length=500)] = ""


class Suggestion(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    action: SuggestionAction
    original_text: str
    proposed_text: str
    rationale: str


class PublishingKit(StrictModel):
    alternative_titles: list[str] = Field(default_factory=list)
    meta_description: str = ""
    suggested_links: list[str] = Field(default_factory=list)
    image_brief: str = ""
    alt_text: str = ""


class LinkedInPackage(StrictModel):
    post_body: str
    hooks: list[str] = Field(min_length=3, max_length=3)
    cta: str
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    first_comment: str
    tracked_url: str


class QueueReleaseRequest(StrictModel):
    scheduled_for: datetime


class PublishingJob(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    article_id: UUID
    owner_id: str
    scheduled_for: datetime
    status: PublishingStatus = PublishingStatus.QUEUED
    repository: str
    branch_name: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    live_url: str | None = None
    linkedin_package: LinkedInPackage | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class SchedulerRequest(StrictModel):
    release_id: UUID | None = None


class WebhookPullRequest(StrictModel):
    action: str
    pull_request: dict
    repository: dict


class ExportDocument(StrictModel):
    filename: str
    content: str
