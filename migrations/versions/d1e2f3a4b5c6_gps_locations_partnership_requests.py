"""Titik GPS lokasi antar + pengajuan kerja sama proyek.

Keputusan owner 2026-10-04:
- Lokasi antar menyimpan titik GPS (peta/GPS HP) sejak pendaftaran; dipakai
  untuk ongkir per km dan petunjuk arah pengantar.
- Pengajuan kerja sama katering proyek dari halaman publik masuk ke OWNER/ADMIN
  untuk ditindaklanjuti.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None

# Dibaca tes cakupan Numeric dan optimistic locking. Koordinat GPS punya
# kategori sendiri: Numeric(10, 7) = derajat dengan presisi ~1 cm.
MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
COORDINATE_COLUMNS = {
    "delivery_locations": ["latitude", "longitude"],
    "partnership_requests": ["latitude", "longitude"],
}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("partnership_requests",)


def upgrade():
    with op.batch_alter_table("delivery_locations") as batch:
        batch.add_column(sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
        batch.add_column(sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
        batch.add_column(sa.Column("gps_accuracy_m", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("gps_updated_at", sa.DateTime(), nullable=True))

    op.create_table(
        "partnership_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("request_number", sa.String(length=30), nullable=False),
        sa.Column("company_name", sa.String(length=150), nullable=False),
        sa.Column("contact_name", sa.String(length=150), nullable=False),
        sa.Column("contact_role", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("project_name", sa.String(length=150), nullable=False),
        sa.Column("project_address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("workers_count", sa.Integer(), nullable=True),
        sa.Column("portions_per_day", sa.Integer(), nullable=True),
        sa.Column("meals", sa.String(length=20), nullable=False, server_default="LUNCH"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("payment_preference", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="NEW"),
        sa.Column("handled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("follow_up_notes", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_partnership_requests_request_number", "partnership_requests", ["request_number"], unique=True)
    op.create_index("ix_partnership_requests_status", "partnership_requests", ["status"])
    op.create_index("ix_partnership_requests_branch_id", "partnership_requests", ["branch_id"])


def downgrade():
    op.drop_index("ix_partnership_requests_branch_id", table_name="partnership_requests")
    op.drop_index("ix_partnership_requests_status", table_name="partnership_requests")
    op.drop_index("ix_partnership_requests_request_number", table_name="partnership_requests")
    op.drop_table("partnership_requests")
    with op.batch_alter_table("delivery_locations") as batch:
        batch.drop_column("gps_updated_at")
        batch.drop_column("gps_accuracy_m")
        batch.drop_column("longitude")
        batch.drop_column("latitude")
