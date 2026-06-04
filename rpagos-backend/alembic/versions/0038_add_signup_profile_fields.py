"""Add signup profile fields to users (first/last name, DOB, country, newsletter).

All columns are NULLABLE with no default and no backfill: existing accounts
predate these fields and legitimately have no DOB/country/etc. New signups are
required (enforced at the SignupRequest schema layer, not the DB) to provide
first_name, last_name, date_of_birth, country_of_residence; newsletter_opt_in is
optional. display_name is left as-is (derived from first+last for new signups;
existing users keep their original value).

batch_alter_table per SQLite test compat (convention 0033-0037).

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("first_name", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("date_of_birth", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("country_of_residence", sa.String(2), nullable=True))
        batch_op.add_column(sa.Column("newsletter_opt_in", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("newsletter_opt_in")
        batch_op.drop_column("country_of_residence")
        batch_op.drop_column("date_of_birth")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
