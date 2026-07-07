"""order default hpp menu profile

Revision ID: 56k0d1e2f3a4
Revises: 56j0c1d2e3f4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "56k0d1e2f3a4"
down_revision = "56j0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("daily_orders") as batch_op:
        batch_op.add_column(sa.Column("lunch_menu_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("dinner_menu_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("packaging_profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("overhead_profile_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_daily_orders_lunch_menu_id_menus", "menus", ["lunch_menu_id"], ["id"])
        batch_op.create_foreign_key("fk_daily_orders_dinner_menu_id_menus", "menus", ["dinner_menu_id"], ["id"])
        batch_op.create_foreign_key("fk_daily_orders_packaging_profile_id_packaging_profiles", "packaging_profiles", ["packaging_profile_id"], ["id"])
        batch_op.create_foreign_key("fk_daily_orders_overhead_profile_id_overhead_profiles", "overhead_profiles", ["overhead_profile_id"], ["id"])

    op.create_index(op.f("ix_daily_orders_lunch_menu_id"), "daily_orders", ["lunch_menu_id"], unique=False)
    op.create_index(op.f("ix_daily_orders_dinner_menu_id"), "daily_orders", ["dinner_menu_id"], unique=False)
    op.create_index(op.f("ix_daily_orders_packaging_profile_id"), "daily_orders", ["packaging_profile_id"], unique=False)
    op.create_index(op.f("ix_daily_orders_overhead_profile_id"), "daily_orders", ["overhead_profile_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_daily_orders_overhead_profile_id"), table_name="daily_orders")
    op.drop_index(op.f("ix_daily_orders_packaging_profile_id"), table_name="daily_orders")
    op.drop_index(op.f("ix_daily_orders_dinner_menu_id"), table_name="daily_orders")
    op.drop_index(op.f("ix_daily_orders_lunch_menu_id"), table_name="daily_orders")

    with op.batch_alter_table("daily_orders") as batch_op:
        batch_op.drop_constraint("fk_daily_orders_overhead_profile_id_overhead_profiles", type_="foreignkey")
        batch_op.drop_constraint("fk_daily_orders_packaging_profile_id_packaging_profiles", type_="foreignkey")
        batch_op.drop_constraint("fk_daily_orders_dinner_menu_id_menus", type_="foreignkey")
        batch_op.drop_constraint("fk_daily_orders_lunch_menu_id_menus", type_="foreignkey")
        batch_op.drop_column("overhead_profile_id")
        batch_op.drop_column("packaging_profile_id")
        batch_op.drop_column("dinner_menu_id")
        batch_op.drop_column("lunch_menu_id")
