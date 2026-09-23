"""Retire the PORTAL_DELEGATE role.

Blueprint V2 leaves three external roles: CLIENT / PT, SUB CLIENT / MANDOR,
CUSTOMER UMUM. The owner confirmed nobody logs in as a delegate.

The two rows holding it are demo accounts. They are moved to PORTAL_CLIENT so
the data names a role the system still assigns, and deactivated in the same
step so the move grants nobody anything: a delegate saw less than a client,
and promoting an account nobody uses would be a silent widening. Reactivate
them from the user screen if either is ever wanted.

Revision ID: 99a0a1b2c3d4
Revises: 98a0a1b2c3d4
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa


revision = "99a0a1b2c3d4"
down_revision = "98a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        sa.text(
            "UPDATE users SET role = 'PORTAL_CLIENT', is_active = false "
            "WHERE role = 'PORTAL_DELEGATE'"
        )
    )


def downgrade():
    # Not reversible: nothing records which accounts were delegates, and they
    # are left deactivated either way, so no access is restored by guessing.
    pass
