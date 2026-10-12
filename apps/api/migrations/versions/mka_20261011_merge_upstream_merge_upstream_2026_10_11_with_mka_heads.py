"""merge upstream 2026-10-11 with mka heads

Revision ID: mka_20261011_merge_upstream
Revises: b6e199d023f8, mka_20261008_course_audience
Create Date: 2026-10-11 21:43:30.239769

"""
from typing import Sequence, Union

import sqlalchemy as sa # noqa: F401
import sqlmodel # noqa: F401


# revision identifiers, used by Alembic.
revision: str = 'mka_20261011_merge_upstream'
down_revision: Union[str, None] = ('b6e199d023f8', 'mka_20261008_course_audience')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
