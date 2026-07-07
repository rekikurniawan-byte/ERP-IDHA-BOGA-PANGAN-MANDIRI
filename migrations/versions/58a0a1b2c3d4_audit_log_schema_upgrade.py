"""audit log schema upgrade

Revision ID: 58a0a1b2c3d4
Revises: 57a0f1a2b3c4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "58a0a1b2c3d4"
down_revision = "57a0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("username_snapshot", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("user_role_snapshot", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("module", sa.String(length=80), nullable=False, server_default="SYSTEM"))
        batch_op.add_column(sa.Column("event_type", sa.String(length=100), nullable=False, server_default="GENERAL"))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("old_value", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("new_value", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("metadata_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ip_address", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("user_agent", sa.String(length=255), nullable=True))
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("table_name", existing_type=sa.String(length=100), nullable=True)
        batch_op.alter_column("record_id", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("action", existing_type=sa.String(length=30), type_=sa.String(length=50), nullable=False, server_default="INFO")
        batch_op.create_foreign_key("fk_audit_logs_branch_id", "branches", ["branch_id"], ["id"])
        batch_op.create_index(op.f("ix_audit_logs_branch_id"), ["branch_id"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_user_id"), ["user_id"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_module"), ["module"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_event_type"), ["event_type"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_table_name"), ["table_name"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_record_id"), ["record_id"], unique=False)
        batch_op.create_index(op.f("ix_audit_logs_action"), ["action"], unique=False)


def downgrade():
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_audit_logs_action"))
        batch_op.drop_index(op.f("ix_audit_logs_record_id"))
        batch_op.drop_index(op.f("ix_audit_logs_table_name"))
        batch_op.drop_index(op.f("ix_audit_logs_event_type"))
        batch_op.drop_index(op.f("ix_audit_logs_module"))
        batch_op.drop_index(op.f("ix_audit_logs_user_id"))
        batch_op.drop_index(op.f("ix_audit_logs_branch_id"))
        batch_op.drop_constraint("fk_audit_logs_branch_id", type_="foreignkey")
        batch_op.alter_column("action", existing_type=sa.String(length=50), type_=sa.String(length=30), nullable=False)
        batch_op.alter_column("record_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("table_name", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("user_agent")
        batch_op.drop_column("ip_address")
        batch_op.drop_column("metadata_json")
        batch_op.drop_column("new_value")
        batch_op.drop_column("old_value")
        batch_op.drop_column("description")
        batch_op.drop_column("event_type")
        batch_op.drop_column("module")
        batch_op.drop_column("user_role_snapshot")
        batch_op.drop_column("username_snapshot")
        batch_op.drop_column("branch_id")
