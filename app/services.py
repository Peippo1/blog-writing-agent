from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, status

from .config import Settings
from .schemas import Article, LinkedInPackage, PublishingKit, PublishingStatus, Suggestion, SuggestionAction


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:160] or "weekly-note"


def front_matter(article: Article) -> str:
    safe = lambda text: text.replace('"', '\\"').replace("\n", " ").strip()
    tags = ", ".join(f'"{safe(tag)}"' for tag in article.tags)
    return "\n".join([
        "---", f'title: "{safe(article.title)}"', f'slug: "{safe(article.slug)}"',
        f'description: "{safe(article.summary)}"', f'category: "{safe(article.category)}"', f"tags: [{tags}]", "---", "", article.markdown.strip(), "",
    ])


def article_url(settings: Settings, article: Article) -> str:
    path = settings.portfolio_article_url_pattern.replace("{slug}", article.slug)
    return urljoin(settings.portfolio_site_url.rstrip("/") + "/", path.lstrip("/"))


def tracked_url(settings: Settings, article: Article) -> str:
    return f"{article_url(settings, article)}?{urlencode({'utm_source': 'linkedin', 'utm_medium': 'social', 'utm_campaign': 'weekly_blog'})}"


def github_signature_valid(secret: str | None, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class ContentGenerator:
    """Gemini-backed content operations with a deterministic local-development fallback."""

    def _model_text(self, prompt: str) -> str | None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=os.getenv("MODEL", "gemini-flash-latest"), contents=prompt)
            return response.text.strip() if response.text else None
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The writing model could not complete this request") from exc

    def outline(self, article: Article) -> str:
        generated = self._model_text(f"""Create a concise Markdown outline for a technical portfolio article.
Topic: {article.brief.topic}
Audience: {article.brief.audience}
Goal: {article.brief.goal}
Tone: {article.brief.tone}
Return only a title, introduction, 4-6 sections, and conclusion. Do not claim research or facts you cannot support.""")
        if generated:
            return generated
        return f"# {article.brief.topic}\n\n## Introduction\nWhy this matters for {article.brief.audience}.\n\n## The problem\nThe constraint or opportunity.\n\n## A practical approach\nThe steps and trade-offs.\n\n## What to measure\nSignals that the approach is working.\n\n## Conclusion\nA useful next step."

    def draft(self, article: Article) -> str:
        generated = self._model_text(f"""Write a complete technical portfolio article in Markdown from this approved outline:
{article.outline}

Topic: {article.brief.topic}
Audience: {article.brief.audience}
Tone: {article.brief.tone}
Target length: {article.brief.target_length} words.
Use clear headings and practical explanations. Return only Markdown. Do not invent project-specific facts.""")
        if generated:
            return generated
        return f"# {article.title}\n\n{article.summary}\n\n## Introduction\n{article.brief.topic} matters when teams need systems that are useful, reliable, and easy to adopt.\n\n## A practical approach\nStart with the workflow, make the trade-offs explicit, and keep a person in control of meaningful decisions.\n\n## Conclusion\nThe strongest next step is a small, observable implementation that can be improved with evidence."

    def suggestion(self, action: SuggestionAction, selected: str, instruction: str) -> Suggestion:
        generated = self._model_text(f"""Return only a replacement Markdown passage for the selected text.
Action: {action.value}
Selected text: {selected}
Extra instruction: {instruction}
Keep claims grounded and preserve the author's tone.""")
        if generated:
            return Suggestion(action=action, original_text=selected, proposed_text=generated, rationale=f"A reviewable {action.value} proposal; accept it only if it matches your intent.")
        action_label = action.value.replace("-", " ")
        if action == SuggestionAction.EXPAND:
            proposed = f"{selected}\n\nThis matters because it makes the decision and its trade-offs visible. {instruction}".strip()
        elif action == SuggestionAction.SHORTEN:
            proposed = selected.split(".")[0].strip() + "."
        elif action == SuggestionAction.SIMPLIFY:
            proposed = selected.replace("utilize", "use").replace("leverage", "use")
        else:
            proposed = f"{selected}\n\n{instruction}".strip()
        return Suggestion(action=action, original_text=selected, proposed_text=proposed, rationale=f"A reviewable {action_label} proposal; accept it only if it matches your intent.")

    def publishing_kit(self, article: Article) -> PublishingKit:
        return PublishingKit(
            alternative_titles=[article.title, f"What {article.brief.topic} teaches us", f"A practical guide to {article.brief.topic}"],
            meta_description=(article.summary or article.brief.topic)[:155],
            suggested_links=["Add one relevant internal project link", "Add one primary source or official reference"],
            image_brief=f"Editorial technical illustration for {article.brief.topic}; clean, restrained, and factual.",
            alt_text=f"Editorial illustration representing {article.brief.topic}.",
        )

    def linkedin(self, settings: Settings, article: Article) -> LinkedInPackage:
        link = tracked_url(settings, article)
        generated = self._model_text(f"""Write one LinkedIn post to promote this technical portfolio article.
Title: {article.title}
Summary: {article.summary}
Tone: {article.brief.tone}
Canonical tracked URL: {link}
Return plain text only. Include the URL and a concise CTA; do not make unsupported claims.""")
        hooks = [
            f"Most work on {article.brief.topic} fails before the technical part starts.",
            f"A useful system for {article.brief.topic} starts with a clear workflow.",
            f"I wrote down the practical trade-offs behind {article.brief.topic}.",
        ]
        cta = "Read the full note for the workflow, trade-offs, and next steps."
        return LinkedInPackage(
            post_body=generated or f"{hooks[0]}\n\n{article.summary or article.brief.topic}\n\n{cta}\n\n{link}",
            hooks=hooks,
            cta=cta,
            hashtags=["#AIEngineering", "#ProductDevelopment", "#BuildInPublic"],
            first_comment=f"Full article: {link}",
            tracked_url=link,
        )


class GitHubPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _access_token(self) -> str:
        """Mint a short-lived installation token; the raw private key stays server-side."""
        if self.settings.github_app_id and self.settings.github_app_installation_id and self.settings.github_app_private_key:
            issued = int(datetime.now(UTC).timestamp())
            app_jwt = jwt.encode({"iat": issued - 60, "exp": issued + 540, "iss": self.settings.github_app_id}, self.settings.github_app_private_key.replace("\\n", "\n"), algorithm="RS256")
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"https://api.github.com/app/installations/{self.settings.github_app_installation_id}/access_tokens", headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"})
                response.raise_for_status()
                return response.json()["token"]
        if self.settings.github_token and not self.settings.is_production:
            return self.settings.github_token
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GitHub App integration is not configured")

    async def open_pull_request(self, article: Article, job_id: UUID) -> tuple[str, int, str]:
        if not self.settings.portfolio_repository:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Portfolio GitHub integration is not configured")
        branch = f"publishing/weekly-{article.slug}-{str(job_id)[:8]}"
        headers = {"Authorization": f"Bearer {await self._access_token()}", "Accept": "application/vnd.github+json"}
        repo = self.settings.portfolio_repository
        async with httpx.AsyncClient(timeout=15.0) as client:
            ref = await client.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{self.settings.portfolio_default_branch}", headers=headers)
            ref.raise_for_status()
            sha = ref.json()["object"]["sha"]
            create_ref = await client.post(f"https://api.github.com/repos/{repo}/git/refs", headers=headers, json={"ref": f"refs/heads/{branch}", "sha": sha})
            create_ref.raise_for_status()
            path = f"{self.settings.portfolio_content_path.rstrip('/')}/{article.slug}.md"
            contents = await client.put(f"https://api.github.com/repos/{repo}/contents/{path}", headers=headers, json={"message": f"Publish: {article.title}", "content": base64.b64encode(front_matter(article).encode()).decode(), "branch": branch})
            contents.raise_for_status()
            pr = await client.post(f"https://api.github.com/repos/{repo}/pulls", headers=headers, json={"title": f"Publish: {article.title}", "head": branch, "base": self.settings.portfolio_default_branch, "body": "Weekly publishing studio release. Review the rendered preview before merging."})
            pr.raise_for_status()
        return branch, pr.json()["number"], pr.json()["html_url"]


async def live_url_exists(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(url)
            return 200 <= response.status_code < 400
    except httpx.HTTPError:
        return False
