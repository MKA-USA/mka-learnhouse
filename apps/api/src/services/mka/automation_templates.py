"""MKA fork: wording for the compliance-automation emails (spec 2026-10-05 sections 2B/2C).

Pure functions, no I/O: each returns :class:`Rendered` (subject, HTML, plain text). Rules:

* short, conversational, plain and professional (no marketing tone, no emojis); ONE link per message;
* addressed to a role title ("Nazim Tabligh, Albany") when only a role mailbox is known (:func:`addressee`);
* tells the reader who to contact (``contact_email``, from ``MKA_AUTOMATION_CONTACT_EMAIL``); omitted if unset;
* NEVER names another person: the digest lists role titles only, reminders list courses only;
* every interpolated value is HTML-escaped in the HTML part and stripped of control characters everywhere
  (role titles and course names come from data); links must be http(s).

The HTML is a small self-contained layout on purpose (no dependency on the upstream email layout, so an
upstream merge cannot silently change the golden output). There is deliberately no unsubscribe link: these are
organisational-duty notices, not marketing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

from src.services.mka import automation_config as cfg

_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
MAX_DIGEST_ROLES = 50
STATUS_PHRASES = {
    "not_signed_in": "not signed in yet",
    "not_started": "not started",
    "in_progress": "in progress",
    "overdue": "overdue",
}


@dataclass(frozen=True)
class Rendered:
    subject: str
    html: str
    text: str


# --- helpers ---------------------------------------------------------------------------------------------


def _plain(value: object) -> str:
    """Single-line plain text: control characters (incl. CR/LF) collapse to a space."""
    return _CTRL.sub(" ", str(value if value is not None else "")).strip()


def _esc(value: object) -> str:
    return html.escape(_plain(value), quote=True)


def _url(value: str) -> str:
    candidate = _plain(value)
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("link must be an absolute http(s) URL")
    return candidate


def _contact(contact_email: Optional[str]) -> str:
    value = _plain(contact_email)
    return value if value and cfg.valid_address(value) else ""


def addressee(
    *, first_name: Optional[str] = None, role_title: Optional[str] = None, majlis: Optional[str] = None
) -> str:
    """Who the greeting names. A first name wins; otherwise the role title (plus Majlis when it is not already
    part of the title), e.g. ``Nazim Tabligh, Albany``; otherwise an empty string (greeting becomes "Hello,")."""
    name = _plain(first_name)
    if name:
        return name
    title = _plain(role_title)
    place = _plain(majlis)
    if title and place and place.lower() not in title.lower():
        return f"{title}, {place}"
    return title


def _join(items: Sequence[str]) -> str:
    items = [_plain(i) for i in items if _plain(i)]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _when(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    local = aware.astimezone(cfg.cycle_tz())
    hour = local.hour % 12 or 12
    return f"{local.strftime('%B')} {local.day}, {local.year} at {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} {local.strftime('%Z')}"


def _day(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _greeting_text(who: str) -> str:
    return f"Hello {who}," if who else "Hello,"


def _p(text: str, bottom: int = 12) -> str:
    return f'<p style="margin:0 0 {bottom}px">{_esc(text)}</p>'


def _ul(items: Sequence[str]) -> str:
    return '<ul style="margin:0 0 12px;padding-left:20px">' + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


def _layout(blocks: Iterable[str], link: Optional[tuple[str, str]], contact: str) -> str:
    """``blocks`` are finished HTML fragments (built with ``_p`` / ``_ul``, which escape)."""
    parts = list(blocks)
    if link:
        parts.append(f'<p style="margin:0 0 12px"><a href="{html.escape(link[1], quote=True)}">{_esc(link[0])}</a></p>')
    if contact:
        parts.append(f'<p style="margin:0 0 12px">Questions? Write to <a href="mailto:{_esc(contact)}">{_esc(contact)}</a>.</p>')
    parts.append('<p style="margin:16px 0 0;color:#666;font-size:12px">This is an automatic notice from MKA USA.</p>')
    return '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px">' + "".join(parts) + "</div>"


def _text(blocks: Iterable[str], link: Optional[tuple[str, str]], contact: str) -> str:
    out = list(blocks)
    if link:
        out.append(f"{_plain(link[0])}: {link[1]}")
    if contact:
        out.append(f"Questions? Write to {contact}.")
    out.append("This is an automatic notice from MKA USA.")
    return "\n\n".join(out) + "\n"


# --- the four messages -------------------------------------------------------------------------------------


def render_receipt(
    *, addressee: str, course_title: str, signed_at: datetime, cycle_label: str, remaining: Sequence[str],
    course_url: str, contact_email: Optional[str] = None,
) -> Rendered:
    """Acknowledgement for ONE sign-off. ``remaining``: titles of required courses still open (may be empty)."""
    who, course, cycle = _plain(addressee), _plain(course_title), _plain(cycle_label)
    when, link, contact = _when(signed_at), _url(course_url), _contact(contact_email)
    left = [_plain(r) for r in remaining if _plain(r)]
    line = (f"You still need to complete: {_join(left)}." if left
            else f"That completes everything required of you for {cycle}.")
    first = f"We have recorded your sign-off for \u201c{course}\u201d on {when}."
    link_label = ("Open your courses", link)
    return Rendered(
        subject=f"We have recorded your sign-off: {course}",
        html=_layout([_p(_greeting_text(who)), _p(first), _p(line)], link_label, contact),
        text=_text([_greeting_text(who), first, line], link_label, contact),
    )


def render_allset(
    *, addressee: str, cycle_label: str, url: str, contact_email: Optional[str] = None
) -> Rendered:
    """Final message once every required sign-off exists."""
    who, cycle, link, contact = _plain(addressee), _plain(cycle_label), _url(url), _contact(contact_email)
    first = f"You are all set for {cycle}. We have your sign-offs for every course required of you."
    second = "There is nothing more to do. Keep this email for your records."
    link_label = ("View your courses", link)
    return Rendered(
        subject=f"You are all set for {cycle}",
        html=_layout([_p(_greeting_text(who)), _p(first), _p(second)], link_label, contact),
        text=_text([_greeting_text(who), first, second], link_label, contact),
    )


def _deadline_line(deadline: date, today: date) -> str:
    days = (deadline - today).days
    if days < 0:
        return f"The deadline was {_day(deadline)}, so the items below are now overdue."
    if days == 0:
        return f"The deadline is today, {_day(deadline)}."
    return f"The deadline is {_day(deadline)} ({days} day{'s' if days != 1 else ''} left)."


def render_reminder(
    *, addressee: str, cycle_label: str, outstanding: Sequence[tuple[str, str]], deadline: date, today: date,
    url: str, contact_email: Optional[str] = None,
) -> Rendered:
    """Weekly nudge. ``outstanding``: (course title, status) pairs; status is one of ``STATUS_PHRASES``."""
    who, cycle, link, contact = _plain(addressee), _plain(cycle_label), _url(url), _contact(contact_email)
    if not outstanding:
        raise ValueError("a reminder needs at least one outstanding course")
    intro = f"A quick reminder about the {cycle} compliance training. {_deadline_line(deadline, today)}"
    items = [f"{_plain(title)}: {STATUS_PHRASES.get(status, 'not finished')}" for title, status in outstanding]
    heading = "Still to complete:"
    closing = "You can pick up where you left off here."
    link_label = ("Open your courses", link)
    subject = f"Overdue: {cycle} compliance training" if deadline < today else f"Reminder: {cycle} compliance training"
    return Rendered(
        subject=subject,
        html=_layout([_p(_greeting_text(who)), _p(intro), _p(heading, 4), _ul(items), _p(closing)], link_label, contact),
        text=_text(
            [_greeting_text(who), intro, heading + "\n" + "\n".join(f"- {i}" for i in items), closing],
            link_label, contact,
        ),
    )


def render_digest(
    *, addressee: str, cycle_label: str, scope_label: str, counts: dict, needs_nudge: Sequence[str],
    url: str, contact_email: Optional[str] = None,
) -> Rendered:
    """Weekly update for a Mohtamim / regional Qaid. Role titles only: never personal names."""
    who, cycle, scope = _plain(addressee), _plain(cycle_label), _plain(scope_label)
    link, contact = _url(url), _contact(contact_email)

    def n(key: str) -> int:
        try:
            return max(0, int(counts.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    total = sum(n(k) for k in ("attested", "in_progress", "not_started", "not_signed_in", "overdue"))
    intro = f"Here is this week's compliance update for {scope} ({cycle})."
    lines = [
        f"Signed off: {n('attested')} of {total}",
        f"In progress: {n('in_progress')}",
        f"Not started: {n('not_started')}",
        f"Not signed in yet: {n('not_signed_in')}",
        f"Overdue: {n('overdue')}",
    ]
    roles = [_plain(r) for r in needs_nudge if _plain(r)]
    shown, extra = roles[:MAX_DIGEST_ROLES], max(0, len(roles) - MAX_DIGEST_ROLES)
    nudge_items = shown + ([f"and {extra} more"] if extra else [])
    link_label = ("See the full list", link)

    text_blocks = [_greeting_text(who), intro, "\n".join(lines)]
    html_blocks = [_p(_greeting_text(who)), _p(intro), '<p style="margin:0 0 12px">' + "<br>".join(_esc(x) for x in lines) + "</p>"]
    if nudge_items:
        heading = "Still to follow up (by role):"
        text_blocks.append(heading + "\n" + "\n".join(f"- {i}" for i in nudge_items))
        html_blocks += [_p(heading, 4), _ul(nudge_items)]
    return Rendered(
        subject=f"Weekly compliance update: {scope}",
        html=_layout(html_blocks, link_label, contact),
        text=_text(text_blocks, link_label, contact),
    )
