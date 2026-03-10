"""Search question generation and storage.

For each drafted article, generates a configurable number of question-based
search capture pages.  Each page targets a long-tail query a reader might
type into Google related to the article's story.

Pages are stored in the ``search_page`` table and served at /q/{slug}.
They are indexed by sitemap.xml and become visible once the parent article
is published by an editor.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from nasvetlo.logging_utils import get_logger
from nasvetlo.models import GeneratedArticle, SearchPage, Event
from nasvetlo.llm import load_prompt, call_llm_json
from nasvetlo.utils.text import slugify

log = get_logger("search.question_generator")


class QuestionItem(BaseModel):
    question: str
    answer_html: str
    meta_description: str = ""
    slug: str = ""


class QuestionGeneratorResult(BaseModel):
    questions: list[QuestionItem] = Field(default_factory=list)


def generate_search_questions(
    article_title: str,
    article_text: str,
    n: int = 3,
) -> QuestionGeneratorResult:
    """Call LLM to generate ``n`` search capture questions for an article.

    Returns empty result on failure so the pipeline is never blocked.
    """
    system_prompt = load_prompt("search_question_generator.txt")

    # Truncate to keep prompt cost low — first 2500 chars covers the lead
    truncated = article_text[:2500]
    user_prompt = (
        f"Number of questions to generate: {n}\n\n"
        f"Article title: {article_title}\n\n"
        f"Article:\n{truncated}"
    )

    try:
        raw = call_llm_json(system=system_prompt, user=user_prompt)
        result = QuestionGeneratorResult(**raw)
        log.info(
            "Generated %d search questions for article '%s'",
            len(result.questions), article_title,
        )
        return result
    except Exception as e:
        log.error(
            "Search question generation failed for '%s': %s", article_title, e
        )
        return QuestionGeneratorResult()


def store_search_pages(
    session: Session,
    article: GeneratedArticle,
    event: Optional[Event],
    result: QuestionGeneratorResult,
) -> int:
    """Persist generated search pages to the database.

    Skips questions whose slug already exists (idempotent).
    Returns the count of pages stored.
    """
    stored = 0
    event_id = event.id if event else None

    for item in result.questions:
        question = item.question.strip()
        if not question:
            continue

        # Normalise slug — use LLM slug if provided, else generate from question
        slug = item.slug.strip() if item.slug else slugify(question, max_length=80)
        if not slug:
            continue

        # Idempotency check — skip if slug already exists
        existing = session.query(SearchPage).filter_by(slug=slug).first()
        if existing:
            log.debug("Search page slug '%s' already exists, skipping.", slug)
            continue

        # Also check for slug collision with article_id appended
        collision = session.query(SearchPage).filter_by(slug=slug).first()
        if collision:
            slug = f"{slug}-{article.id}"

        page = SearchPage(
            article_id=article.id,
            event_id=event_id,
            question=question,
            slug=slug,
            body_html=item.answer_html,
            meta_description=item.meta_description[:155] if item.meta_description else "",
        )
        session.add(page)
        stored += 1

    if stored:
        session.flush()

    log.info(
        "Stored %d search pages for article %d", stored, article.id
    )
    return stored
