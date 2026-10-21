"""Role row class: the class each character played in each raid, on the healer, tank and dps rows.

Characters are stored by name, so two characters sharing a name (a priest of one era and a shaman of the next) share
a row in ``characters``; the class on each role row keeps their raids apart. Nullable: a row stored before this
revision has no class until ``RaidService.backfill_classes()`` reads it from Warcraft Logs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("healer_performance", "tank_performance", "dps_performance")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("player_class", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "player_class")
