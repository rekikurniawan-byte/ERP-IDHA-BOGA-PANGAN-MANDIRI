"""Rename the PORTAL_MANDOR role to PORTAL_SUBCLIENT.

Blueprint V2 names the external roles after the contract hierarchy:
CLIENT / PT, SUB CLIENT / MANDOR, and CUSTOMER UMUM. This is a rename of the
role only. The domain entity is still Mandor, the mandors table is untouched,
and the /portal/mandor/* URLs keep working -- so nothing about what a sub
client may see changes here.

app/utils/roles.py maps the old name to the new one, so a row that still
says PORTAL_MANDOR keeps working either way; this migration just stops the
data from claiming a role the system no longer assigns.

Revision ID: 97a0a1b2c3d4
Revises: 96a0a1b2c3d4
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa


revision = "97a0a1b2c3d4"
down_revision = "96a0a1b2c3d4"
branch_labels = None
depends_on = None

OLD_ROLE = "PORTAL_MANDOR"
NEW_ROLE = "PORTAL_SUBCLIENT"


def _rename(bind, source, target):
    bind.execute(
        sa.text("UPDATE users SET role = :target WHERE role = :source"),
        {"source": source, "target": target},
    )


def upgrade():
    _rename(op.get_bind(), OLD_ROLE, NEW_ROLE)


def downgrade():
    # Reversible, unlike the internal consolidation: this is a pure rename,
    # so the old name can be put back exactly.
    _rename(op.get_bind(), NEW_ROLE, OLD_ROLE)
