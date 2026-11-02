"""Render the HTML emails in ``app/templates/email``.

The templates share the layout and styling of the EveryCRED DCS emails, so
a holder gets the same-looking email from either service. Values are
HTML-escaped (``autoescape``); templates never receive raw HTML.
"""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

EMAIL_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "templates" / "email"
)


@lru_cache
def _environment() -> Environment:
    # StrictUndefined: a missing value fails the render in tests instead of
    # silently mailing a blank field.
    return Environment(
        loader=FileSystemLoader(EMAIL_TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
    )


def render_email(template_name: str, **context: Any) -> str:
    """Return the HTML of ``template_name`` filled with ``context``.

    ``year`` is added for the footer unless the caller passes one.

    Raises:
        jinja2.TemplateNotFound: No such template.
        jinja2.UndefinedError: The template uses a value not given.
    """
    context.setdefault("year", datetime.now(UTC).year)
    return _environment().get_template(template_name).render(**context)
