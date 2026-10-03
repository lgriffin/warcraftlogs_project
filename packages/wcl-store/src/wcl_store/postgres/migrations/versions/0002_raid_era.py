"""Raid era: which Warcraft Logs site a raid is on and the expansion of its zone.

Both nullable: a raid stored before this revision has no era until ``ProfileService.backfill_eras()`` fills
it, and a NULL matches every ``RaidScope`` so the raid stays visible in every profile.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raids", sa.Column("game_version", sa.Text(), nullable=True))
    op.add_column("raids", sa.Column("expansion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("raids", "expansion")
    op.drop_column("raids", "game_version")
