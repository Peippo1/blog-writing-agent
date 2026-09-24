from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from .schemas import Article, ArticleStatus, PublishingJob, PublishingStatus


class MemoryStore:
    """Local/test adapter; production can replace this boundary with Firestore."""

    def __init__(self) -> None:
        self.articles: dict[UUID, Article] = {}
        self.jobs: dict[UUID, PublishingJob] = {}

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    def create_article(self, article: Article) -> Article:
        self.articles[article.id] = article
        return article

    def list_articles(self, owner_id: str) -> list[Article]:
        return sorted((a for a in self.articles.values() if a.owner_id == owner_id), key=lambda a: a.updated_at, reverse=True)

    def article(self, article_id: UUID, owner_id: str) -> Article:
        article = self.articles.get(article_id)
        if not article or article.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
        return article

    def update_article(self, article: Article, **changes: object) -> Article:
        for key, value in changes.items():
            if value is not None:
                setattr(article, key, value)
        article.updated_at = self.now()
        self.articles[article.id] = article
        return article

    def queue_job(self, job: PublishingJob) -> PublishingJob:
        for existing in self.jobs.values():
            if existing.scheduled_for == job.scheduled_for and existing.status not in {PublishingStatus.CANCELLED, PublishingStatus.FAILED}:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That release slot is already occupied")
        self.jobs[job.id] = job
        return job

    def job(self, job_id: UUID, owner_id: str | None = None) -> PublishingJob:
        job = self.jobs.get(job_id)
        if not job or (owner_id and job.owner_id != owner_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publishing job not found")
        return job

    def jobs_for_owner(self, owner_id: str) -> list[PublishingJob]:
        return sorted((j for j in self.jobs.values() if j.owner_id == owner_id), key=lambda j: j.scheduled_for)

    def due_job(self, release_id: UUID | None = None) -> PublishingJob | None:
        if release_id:
            job = self.jobs.get(release_id)
            return job if job and job.status == PublishingStatus.QUEUED else None
        now = self.now()
        return next((j for j in self.jobs.values() if j.status == PublishingStatus.QUEUED and j.scheduled_for <= now), None)

    def update_job(self, job: PublishingJob, **changes: object) -> PublishingJob:
        for key, value in changes.items():
            if value is not None:
                setattr(job, key, value)
        job.updated_at = self.now()
        self.jobs[job.id] = job
        return job

    def job_for_pr(self, repository: str, pr_number: int) -> PublishingJob | None:
        return next((job for job in self.jobs.values() if job.repository == repository and job.pr_number == pr_number), None)


class FirestoreStore(MemoryStore):
    """Firestore persistence used by Cloud Run; keeps the same ownership API as local tests."""

    def __init__(self, project_id: str) -> None:
        super().__init__()
        import firebase_admin
        from firebase_admin import firestore

        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={"projectId": project_id})
        self.db = firestore.client()

    @staticmethod
    def _article(document: dict) -> Article:
        return Article.model_validate(document)

    @staticmethod
    def _job(document: dict) -> PublishingJob:
        return PublishingJob.model_validate(document)

    def create_article(self, article: Article) -> Article:
        self.db.collection("articles").document(str(article.id)).set(article.model_dump(mode="json"))
        return article

    def list_articles(self, owner_id: str) -> list[Article]:
        documents = self.db.collection("articles").where("owner_id", "==", owner_id).stream()
        return sorted((self._article(document.to_dict()) for document in documents), key=lambda article: article.updated_at, reverse=True)

    def article(self, article_id: UUID, owner_id: str) -> Article:
        document = self.db.collection("articles").document(str(article_id)).get()
        if not document.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
        article = self._article(document.to_dict())
        if article.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
        return article

    def update_article(self, article: Article, **changes: object) -> Article:
        article = super().update_article(article, **changes)
        self.db.collection("articles").document(str(article.id)).set(article.model_dump(mode="json"))
        return article

    def queue_job(self, job: PublishingJob) -> PublishingJob:
        conflict = self.db.collection("publishing_jobs").where("scheduled_for", "==", job.scheduled_for.isoformat()).where("status", "in", [PublishingStatus.QUEUED.value, PublishingStatus.PR_OPEN.value, PublishingStatus.MERGED.value, PublishingStatus.LIVE.value]).limit(1).stream()
        if next(conflict, None):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That release slot is already occupied")
        self.db.collection("publishing_jobs").document(str(job.id)).set(job.model_dump(mode="json"))
        return job

    def job(self, job_id: UUID, owner_id: str | None = None) -> PublishingJob:
        document = self.db.collection("publishing_jobs").document(str(job_id)).get()
        if not document.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publishing job not found")
        job = self._job(document.to_dict())
        if owner_id and job.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publishing job not found")
        return job

    def jobs_for_owner(self, owner_id: str) -> list[PublishingJob]:
        documents = self.db.collection("publishing_jobs").where("owner_id", "==", owner_id).stream()
        return sorted((self._job(document.to_dict()) for document in documents), key=lambda job: job.scheduled_for)

    def due_job(self, release_id: UUID | None = None) -> PublishingJob | None:
        if release_id:
            job = self.job(release_id)
            return job if job.status == PublishingStatus.QUEUED else None
        documents = self.db.collection("publishing_jobs").where("status", "==", PublishingStatus.QUEUED.value).where("scheduled_for", "<=", self.now().isoformat()).limit(1).stream()
        document = next(documents, None)
        return self._job(document.to_dict()) if document else None

    def update_job(self, job: PublishingJob, **changes: object) -> PublishingJob:
        job = super().update_job(job, **changes)
        self.db.collection("publishing_jobs").document(str(job.id)).set(job.model_dump(mode="json"))
        return job

    def job_for_pr(self, repository: str, pr_number: int) -> PublishingJob | None:
        documents = self.db.collection("publishing_jobs").where("repository", "==", repository).where("pr_number", "==", pr_number).limit(1).stream()
        document = next(documents, None)
        return self._job(document.to_dict()) if document else None
