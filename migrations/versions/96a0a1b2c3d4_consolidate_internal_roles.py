"""Consolidate retired internal roles into ADMIN.

Blueprint V2 collapses the internal roles to OWNER, ADMIN, DAPUR and
PENGANTAR. FINANCE, ACCOUNTING, LOGISTICS, HR and CUSTOMER_SUCCESS were
prepared for departments that do not exist; ADMIN does that work. See
BLUEPRINT_V2_AUDIT_FITUR.md and app/utils/roles.py.

The application already treats those roles as ADMIN, so this migration is
about keeping stored data honest: a user row should not claim a role the
system no longer assigns, and the user form would otherwise refuse to save
such a user.

Downgrade is a deliberate no-op. Restoring each user's former role would mean
keeping a record of it somewhere, and every row in this database is demo
data (confirmed by the owner). Leaving users as ADMIN after a downgrade is
safe: ADMIN predates this revision and can do everything those roles could.

Revision ID: 96a0a1b2c3d4
Revises: 95a0a1b2c3d4
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa


revision = "96a0a1b2c3d4"
down_revision = "95a0a1b2c3d4"
branch_labels = None
depends_on = None

RETIRED_ROLES = ("FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "CUSTOMER_SUCCESS")
SUCCESSOR = "ADMIN"


def upgrade():
    bind = op.get_bind()
    params = {"successor": SUCCESSOR, "retired": list(RETIRED_ROLES)}
    retired = sa.bindparam("retired", expanding=True)

    bind.execute(
        sa.text("UPDATE users SET role = :successor WHERE role IN :retired")
        .bindparams(retired),
        params,
    )

    # Notifications addressed to a retired role would otherwise be visible to
    # no one. The table is empty today; this keeps the migration correct for
    # any database where it is not.
    bind.execute(
        sa.text("UPDATE notifications SET target_role = :successor WHERE target_role IN :retired")
        .bindparams(retired),
        params,
    )


def downgrade():
    # Intentional no-op -- see the module docstring.
    pass
