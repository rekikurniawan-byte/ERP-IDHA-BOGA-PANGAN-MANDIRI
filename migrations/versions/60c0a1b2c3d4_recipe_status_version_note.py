"""recipe status version note

Revision ID: 60c0a1b2c3d4
Revises: 58a0a1b2c3d4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "60c0a1b2c3d4"
down_revision = "58a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recipe_headers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("recipe_status", sa.String(length=20), nullable=False, server_default="DRAFT"))
        batch_op.add_column(sa.Column("version_label", sa.String(length=50), nullable=False, server_default="v1"))
        batch_op.add_column(sa.Column("version_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("finalized_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("finalized_by", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_recipe_headers_recipe_status"), ["recipe_status"], unique=False)


def downgrade():
    with op.batch_alter_table("recipe_headers", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_recipe_headers_recipe_status"))
        batch_op.drop_column("finalized_by")
        batch_op.drop_column("finalized_at")
        batch_op.drop_column("version_note")
        batch_op.drop_column("version_label")
        batch_op.drop_column("recipe_status")
