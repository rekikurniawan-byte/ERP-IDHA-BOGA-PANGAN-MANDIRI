"""Unit order langsung untuk client kontrak tanpa sub client.

Setiap order terikat ke sub client (mandor) di enam tabel, jadi client yang
memesan sendiri tidak bisa order sama sekali. Keputusan owner 2026-09-25:
client seperti itu mendapat satu sub client khusus "PT X — Langsung", ditandai
kolom ini, alih-alih membongkar kewajiban mandor di 62 file.

Data lama tidak diubah: semua mandor yang ada tetap is_direct_unit = false.

Revision ID: a1b2c3d4e5f6
Revises: a0b1c2d3e4f5
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mandors",
        sa.Column("is_direct_unit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Satu unit langsung per client per cabang, dijaga database -- dua klik
    # "Aktifkan" yang bersamaan tidak bisa membuat dua unit.
    op.create_index(
        "uq_mandors_direct_unit_per_client",
        "mandors",
        ["branch_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("is_direct_unit"),
    )


def downgrade():
    op.drop_index("uq_mandors_direct_unit_per_client", table_name="mandors")
    op.drop_column("mandors", "is_direct_unit")
