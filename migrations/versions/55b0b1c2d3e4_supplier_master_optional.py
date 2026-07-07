"""supplier master optional

Revision ID: 55b0b1c2d3e4
Revises: 7e141fc5adf3
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "55b0b1c2d3e4"
down_revision = "7e141fc5adf3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppliers",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("supplier_code", sa.String(length=50), nullable=False),
        sa.Column("supplier_name", sa.String(length=150), nullable=False),
        sa.Column("supplier_type", sa.String(length=50), nullable=False, server_default="GENERAL"),
        sa.Column("contact_person", sa.String(length=150), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("whatsapp", sa.String(length=30), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("default_payment_terms_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bank_name", sa.String(length=100), nullable=True),
        sa.Column("bank_account_number", sa.String(length=100), nullable=True),
        sa.Column("bank_account_holder", sa.String(length=150), nullable=True),
        sa.Column("npwp", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "supplier_name", name="uq_suppliers_branch_name"),
        sa.UniqueConstraint("supplier_code")
    )
    op.create_index(op.f("ix_suppliers_branch_id"), "suppliers", ["branch_id"], unique=False)
    op.create_index(op.f("ix_suppliers_supplier_name"), "suppliers", ["supplier_name"], unique=False)

    with op.batch_alter_table("procurements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("supplier_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_procurements_supplier_id"), ["supplier_id"], unique=False)
        batch_op.create_foreign_key("fk_procurements_supplier_id_suppliers", "suppliers", ["supplier_id"], ["id"])


def downgrade():
    with op.batch_alter_table("procurements", schema=None) as batch_op:
        batch_op.drop_constraint("fk_procurements_supplier_id_suppliers", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_procurements_supplier_id"))
        batch_op.drop_column("supplier_id")

    op.drop_index(op.f("ix_suppliers_supplier_name"), table_name="suppliers")
    op.drop_index(op.f("ix_suppliers_branch_id"), table_name="suppliers")
    op.drop_table("suppliers")
