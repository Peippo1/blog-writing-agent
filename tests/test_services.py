from datetime import UTC, datetime

from app.config import Settings
from app.schemas import Article, ArticleBrief
from app.services import article_url, front_matter, github_signature_valid, slugify, tracked_url


def article() -> Article:
    return Article(owner_id="u1", brief=ArticleBrief(topic="Build reliable agent workflows"), title="Reliable agent workflows", slug="reliable-agent-workflows", summary="A practical note.", tags=["AI"], created_at=datetime.now(UTC), updated_at=datetime.now(UTC), markdown="# Hello")


def test_slug_and_front_matter_are_portable():
    assert slugify("A clear: technical post!") == "a-clear-technical-post"
    content = front_matter(article())
    assert content.startswith("---\ntitle: \"Reliable agent workflows\"")
    assert "# Hello" in content


def test_linkedin_url_is_canonical_and_tracked():
    settings = Settings(portfolio_site_url="https://tfinch.dev", portfolio_article_url_pattern="/writing/{slug}")
    assert article_url(settings, article()) == "https://tfinch.dev/writing/reliable-agent-workflows"
    assert "utm_source=linkedin" in tracked_url(settings, article())


def test_github_signature_rejects_tampering():
    body = b'{"action":"closed"}'
    import hashlib, hmac
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert github_signature_valid("secret", body, signature)
    assert not github_signature_valid("secret", b"different", signature)
