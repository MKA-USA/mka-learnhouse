"""Advisory AI content moderation (log + record flags for staff review).

Text only; never blocks, hides or grades. See the Jev section of ``docs/content/self-hosting/configuration/environment-variables.mdx``.
"""

from src.services.moderation_ai.extractors import (  # noqa: F401
    assignment_submission_text,
    forum_text,
    profile_text,
)
from src.services.moderation_ai.scheduler import schedule_moderation  # noqa: F401
from src.services.moderation_ai.settings import moderation_enabled  # noqa: F401
