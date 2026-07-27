"""Add portal user ownership mappings.

Revision ID: 91a0a1b2c3d4
Revises: 90a0a1b2c3d4
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "91a0a1b2c3d4"
down_revision = "90a0a1b2c3d4"
branch_labels = None
depends_on = None
VERSIONED_TABLES = ("portal_user_mappings",)


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def upgrade():
    if _table_exists("portal_user_mappings"):
        return

    op.create_table(
        "portal_user_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("principal_type", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("mandor_id", sa.Integer(), nullable=True),
        sa.Column("client_pic_id", sa.Integer(), nullable=True),
        sa.Column("delivery_location_id", sa.Integer(), nullable=True),
        sa.Column("access_level", sa.String(length=30), nullable=False, server_default="READ_ONLY"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "principal_type IN ('CLIENT', 'MANDOR', 'CLIENT_PIC', 'DELEGATE')",
            name="ck_portal_user_mappings_principal_type",
        ),
        sa.CheckConstraint(
            "access_level IN ('READ_ONLY', 'DRAFT_ORDER')",
            name="ck_portal_user_mappings_access_level",
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["client_pic_id"], ["client_pics.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["delivery_location_id"], ["delivery_locations.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column_name in (
        "user_id",
        "principal_type",
        "client_id",
        "mandor_id",
        "client_pic_id",
        "delivery_location_id",
        "access_level",
        "is_active",
        "created_by",
        "updated_by",
    ):
        op.create_index(op.f(f"ix_portal_user_mappings_{column_name}"), "portal_user_mappings", [column_name], unique=False)
    op.create_index(
        "ix_portal_user_mappings_user_active",
        "portal_user_mappings",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_portal_user_mappings_principal_active",
        "portal_user_mappings",
        ["principal_type", "is_active"],
        unique=False,
    )


def downgrade():
    if not _table_exists("portal_user_mappings"):
        return

    op.drop_index("ix_portal_user_mappings_principal_active", table_name="portal_user_mappings")
    op.drop_index("ix_portal_user_mappings_user_active", table_name="portal_user_mappings")
    for column_name in (
        "updated_by",
        "created_by",
        "is_active",
        "access_level",
        "delivery_location_id",
        "client_pic_id",
        "mandor_id",
        "client_id",
        "principal_type",
        "user_id",
    ):
        op.drop_index(op.f(f"ix_portal_user_mappings_{column_name}"), table_name="portal_user_mappings")
    op.drop_table("portal_user_mappings")
