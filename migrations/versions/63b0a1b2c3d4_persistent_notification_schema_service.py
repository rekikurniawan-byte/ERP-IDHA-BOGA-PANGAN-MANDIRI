"""persistent notification schema service

Revision ID: 63b0a1b2c3d4
Revises: 62b0a1b2c3d4
Create Date: 2026-06-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "63b0a1b2c3d4"
down_revision = "62b0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.alter_column("branch_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("notification_type", existing_type=sa.String(length=50), nullable=False)
        batch_op.alter_column("status", existing_type=sa.String(length=30), nullable=False)
        batch_op.add_column(sa.Column("target_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("target_role", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.String(length=20), nullable=False, server_default="INFO"))
        batch_op.add_column(sa.Column("reference_type", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("reference_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("action_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("read_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("dismissed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("generated_key", sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_notifications_target_user_id_users", "users", ["target_user_id"], ["id"])

    op.create_index("ix_notifications_branch_id", "notifications", ["branch_id"], unique=False)
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"], unique=False)
    op.create_index("ix_notifications_status", "notifications", ["status"], unique=False)
    op.create_index("ix_notifications_target_user_id", "notifications", ["target_user_id"], unique=False)
    op.create_index("ix_notifications_target_role", "notifications", ["target_role"], unique=False)
    op.create_index("ix_notifications_priority", "notifications", ["priority"], unique=False)
    op.create_index("ix_notifications_reference_type", "notifications", ["reference_type"], unique=False)
    op.create_index("ix_notifications_reference_id", "notifications", ["reference_id"], unique=False)
    op.create_index("ix_notifications_due_date", "notifications", ["due_date"], unique=False)
    op.create_index("ix_notifications_generated_key", "notifications", ["generated_key"], unique=True)

    # Remove server default after backfilling existing rows.
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.alter_column("priority", server_default=None)


def downgrade():
    op.drop_index("ix_notifications_generated_key", table_name="notifications")
    op.drop_index("ix_notifications_due_date", table_name="notifications")
    op.drop_index("ix_notifications_reference_id", table_name="notifications")
    op.drop_index("ix_notifications_reference_type", table_name="notifications")
    op.drop_index("ix_notifications_priority", table_name="notifications")
    op.drop_index("ix_notifications_target_role", table_name="notifications")
    op.drop_index("ix_notifications_target_user_id", table_name="notifications")
    op.drop_index("ix_notifications_status", table_name="notifications")
    op.drop_index("ix_notifications_notification_type", table_name="notifications")
    op.drop_index("ix_notifications_branch_id", table_name="notifications")

    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint("fk_notifications_target_user_id_users", type_="foreignkey")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("generated_key")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("dismissed_at")
        batch_op.drop_column("read_at")
        batch_op.drop_column("due_date")
        batch_op.drop_column("action_url")
        batch_op.drop_column("reference_id")
        batch_op.drop_column("reference_type")
        batch_op.drop_column("priority")
        batch_op.drop_column("target_role")
        batch_op.drop_column("target_user_id")
