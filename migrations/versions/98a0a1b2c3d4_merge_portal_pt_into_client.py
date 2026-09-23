"""Merge the PORTAL_PT role into PORTAL_CLIENT.

Blueprint V2 leaves three external roles: CLIENT / PT, SUB CLIENT / MANDOR,
and CUSTOMER UMUM. Client and PT were never two things -- the scope resolver
put both through the same branch, with the same expected principals, and
produced the same client and mandor ids. Only the label and the set of pages
differed.

The merged role keeps the PT experience, which is the one the business
describes: the company sees every sub client under its contract, plus
contracts, invoices, receivables and payments. The narrower client_dashboard
page still exists and still renders; it is simply no longer a landing.

Revision ID: 98a0a1b2c3d4
Revises: 97a0a1b2c3d4
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa


revision = "98a0a1b2c3d4"
down_revision = "97a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        sa.text("UPDATE users SET role = 'PORTAL_CLIENT' WHERE role = 'PORTAL_PT'")
    )


def downgrade():
    # Not reversible: once merged there is nothing recorded to say which
    # accounts were PT. Both names resolved to the same data scope, so an
    # account left as PORTAL_CLIENT after a downgrade sees what it always saw.
    pass
