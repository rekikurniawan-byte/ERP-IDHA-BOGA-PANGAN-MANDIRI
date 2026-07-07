"""PRODUCTION official invoice identity, client code, and PIC lock

Revision ID: 69e0a1b2c3d4
Revises: 69d0a1b2c3d4
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "69e0a1b2c3d4"
down_revision = "69d0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("client_code", sa.String(length=50), nullable=True))
        batch_op.create_index("ix_clients_client_code", ["client_code"], unique=True)

    op.execute("""
        UPDATE clients
        SET client_code = 'CL-' || substr('0000' || id, -4, 4)
        WHERE client_code IS NULL OR client_code = ''
    """)

    with op.batch_alter_table("client_pics") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=150), nullable=True))

    with op.batch_alter_table("invoices") as batch_op:
        batch_op.add_column(sa.Column("client_pic_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("client_name_snapshot", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("client_code_snapshot", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("client_pic_name_snapshot", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("client_pic_position_snapshot", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("client_pic_phone_snapshot", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("client_pic_email_snapshot", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("company_bank_name_snapshot", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("company_bank_account_number_snapshot", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("company_bank_account_name_snapshot", sa.String(length=150), nullable=True))
        batch_op.create_foreign_key("fk_invoices_client_pic", "client_pics", ["client_pic_id"], ["id"])

    op.create_index("ix_invoices_client_pic_id", "invoices", ["client_pic_id"])

    op.execute("""
        UPDATE invoices
        SET client_name_snapshot = (SELECT name FROM clients WHERE clients.id = invoices.client_id),
            client_code_snapshot = (SELECT client_code FROM clients WHERE clients.id = invoices.client_id)
        WHERE client_id IS NOT NULL
    """)

    op.execute("""
        UPDATE invoices
        SET client_pic_id = (
                SELECT cp.id
                FROM client_pics cp
                WHERE cp.client_id = invoices.client_id AND cp.is_active IS TRUE
                ORDER BY CASE WHEN cp.phone IS NOT NULL AND cp.phone != '' THEN 0 ELSE 1 END, cp.id ASC
                LIMIT 1
            )
        WHERE client_id IS NOT NULL AND client_pic_id IS NULL
    """)

    op.execute("""
        UPDATE invoices
        SET client_pic_name_snapshot = (SELECT name FROM client_pics WHERE client_pics.id = invoices.client_pic_id),
            client_pic_position_snapshot = (SELECT position FROM client_pics WHERE client_pics.id = invoices.client_pic_id),
            client_pic_phone_snapshot = (SELECT phone FROM client_pics WHERE client_pics.id = invoices.client_pic_id),
            client_pic_email_snapshot = (SELECT email FROM client_pics WHERE client_pics.id = invoices.client_pic_id)
        WHERE client_pic_id IS NOT NULL
    """)


def downgrade():
    op.drop_index("ix_invoices_client_pic_id", table_name="invoices")
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_constraint("fk_invoices_client_pic", type_="foreignkey")
        batch_op.drop_column("company_bank_account_name_snapshot")
        batch_op.drop_column("company_bank_account_number_snapshot")
        batch_op.drop_column("company_bank_name_snapshot")
        batch_op.drop_column("client_pic_email_snapshot")
        batch_op.drop_column("client_pic_phone_snapshot")
        batch_op.drop_column("client_pic_position_snapshot")
        batch_op.drop_column("client_pic_name_snapshot")
        batch_op.drop_column("client_code_snapshot")
        batch_op.drop_column("client_name_snapshot")
        batch_op.drop_column("client_pic_id")

    with op.batch_alter_table("client_pics") as batch_op:
        batch_op.drop_column("email")

    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_index("ix_clients_client_code")
        batch_op.drop_column("client_code")
