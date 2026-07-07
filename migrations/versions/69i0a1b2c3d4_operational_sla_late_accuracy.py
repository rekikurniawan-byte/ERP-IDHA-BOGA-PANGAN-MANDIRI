"""PRODUCTION operational SLA and late accuracy

Revision ID: 69i0a1b2c3d4
Revises: 69e0a1b2c3d4
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "69i0a1b2c3d4"
down_revision = "69e0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.add_column(sa.Column("target_dispatch_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("target_arrival_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("actual_departure_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("late_tolerance_minutes", sa.Integer(), nullable=True))

    with op.batch_alter_table("delivery_details") as batch_op:
        batch_op.add_column(sa.Column("sla_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("sla_minutes_late", sa.Integer(), nullable=True))

    with op.batch_alter_table("productions") as batch_op:
        batch_op.add_column(sa.Column("target_ready_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("actual_completed_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("late_tolerance_minutes", sa.Integer(), nullable=True))

    bind = op.get_bind()
    dialect = bind.dialect.name

    op.execute("""
        UPDATE deliveries
        SET late_tolerance_minutes = COALESCE(late_tolerance_minutes, 15)
        WHERE late_tolerance_minutes IS NULL
    """)

    if dialect == "postgresql":
        op.execute("""
            UPDATE deliveries
            SET target_dispatch_time = CASE
                    WHEN notes LIKE '%delivery_type=DINNER%' THEN delivery_date + TIME '16:30:00'
                    ELSE delivery_date + TIME '10:30:00'
                END,
                target_arrival_time = CASE
                    WHEN notes LIKE '%delivery_type=DINNER%' THEN delivery_date + TIME '17:30:00'
                    ELSE delivery_date + TIME '11:30:00'
                END
            WHERE target_dispatch_time IS NULL OR target_arrival_time IS NULL
        """)
    else:
        op.execute("""
            UPDATE deliveries
            SET target_dispatch_time = CASE
                    WHEN notes LIKE '%delivery_type=DINNER%' THEN delivery_date || ' 16:30:00'
                    ELSE delivery_date || ' 10:30:00'
                END,
                target_arrival_time = CASE
                    WHEN notes LIKE '%delivery_type=DINNER%' THEN delivery_date || ' 17:30:00'
                    ELSE delivery_date || ' 11:30:00'
                END
            WHERE target_dispatch_time IS NULL OR target_arrival_time IS NULL
        """)

    op.execute("""
        UPDATE productions
        SET late_tolerance_minutes = COALESCE(late_tolerance_minutes, 0)
        WHERE late_tolerance_minutes IS NULL
    """)

    if dialect == "postgresql":
        op.execute("""
            UPDATE productions
            SET target_ready_time = CASE
                    WHEN production_type = 'DINNER' THEN production_date + TIME '16:00:00'
                    ELSE production_date + TIME '10:00:00'
                END
            WHERE target_ready_time IS NULL
        """)
    else:
        op.execute("""
            UPDATE productions
            SET target_ready_time = CASE
                    WHEN production_type = 'DINNER' THEN production_date || ' 16:00:00'
                    ELSE production_date || ' 10:00:00'
                END
            WHERE target_ready_time IS NULL
        """)

    op.execute("""
        UPDATE productions
        SET actual_completed_time = created_at
        WHERE status = 'COMPLETED' AND actual_completed_time IS NULL
    """)

    op.execute("""
        UPDATE delivery_details
        SET sla_status = 'PENDING', sla_minutes_late = 0
        WHERE sla_status IS NULL
    """)

    op.execute("""
        UPDATE delivery_details
        SET sla_status = 'CANCELLED'
        WHERE delivery_id IN (
            SELECT id FROM deliveries WHERE COALESCE(UPPER(status), '') IN ('CANCELLED', 'CANCELED')
        )
    """)

    op.execute("""
        UPDATE delivery_details
        SET sla_status = 'SHORTAGE'
        WHERE COALESCE(shortage_qty, 0) > 0
          AND id IN (SELECT delivery_detail_id FROM delivery_receipts)
          AND COALESCE(sla_status, '') != 'CANCELLED'
    """)

    if dialect == "postgresql":
        op.execute("""
            UPDATE delivery_details
            SET sla_status = 'ON_TIME'
            WHERE id IN (
                SELECT dd.id
                FROM delivery_details dd
                JOIN deliveries d ON d.id = dd.delivery_id
                JOIN delivery_receipts dr ON dr.delivery_detail_id = dd.id
                WHERE dr.receive_time <= d.target_arrival_time + (COALESCE(d.late_tolerance_minutes, 15) * INTERVAL '1 minute')
                  AND COALESCE(dd.shortage_qty, 0) <= 0
                  AND COALESCE(UPPER(d.status), '') NOT IN ('CANCELLED', 'CANCELED')
            )
        """)

        op.execute("""
            UPDATE delivery_details
            SET sla_status = 'LATE',
                sla_minutes_late = COALESCE((
                    SELECT CAST(EXTRACT(EPOCH FROM (dr.receive_time - (d.target_arrival_time + (COALESCE(d.late_tolerance_minutes, 15) * INTERVAL '1 minute')))) / 60 AS INTEGER)
                    FROM deliveries d
                    JOIN delivery_receipts dr ON dr.delivery_detail_id = delivery_details.id
                    WHERE d.id = delivery_details.delivery_id
                ), 0)
            WHERE id IN (
                SELECT dd.id
                FROM delivery_details dd
                JOIN deliveries d ON d.id = dd.delivery_id
                JOIN delivery_receipts dr ON dr.delivery_detail_id = dd.id
                WHERE dr.receive_time > d.target_arrival_time + (COALESCE(d.late_tolerance_minutes, 15) * INTERVAL '1 minute')
                  AND COALESCE(dd.shortage_qty, 0) <= 0
                  AND COALESCE(UPPER(d.status), '') NOT IN ('CANCELLED', 'CANCELED')
            )
        """)
    else:
        op.execute("""
            UPDATE delivery_details
            SET sla_status = 'ON_TIME'
            WHERE id IN (
                SELECT dd.id
                FROM delivery_details dd
                JOIN deliveries d ON d.id = dd.delivery_id
                JOIN delivery_receipts dr ON dr.delivery_detail_id = dd.id
                WHERE dr.receive_time <= datetime(d.target_arrival_time, '+' || COALESCE(d.late_tolerance_minutes, 15) || ' minutes')
                  AND COALESCE(dd.shortage_qty, 0) <= 0
                  AND COALESCE(UPPER(d.status), '') NOT IN ('CANCELLED', 'CANCELED')
            )
        """)

        op.execute("""
            UPDATE delivery_details
            SET sla_status = 'LATE',
                sla_minutes_late = COALESCE((
                    SELECT CAST((julianday(dr.receive_time) - julianday(datetime(d.target_arrival_time, '+' || COALESCE(d.late_tolerance_minutes, 15) || ' minutes'))) * 24 * 60 AS INTEGER)
                    FROM deliveries d
                    JOIN delivery_receipts dr ON dr.delivery_detail_id = delivery_details.id
                    WHERE d.id = delivery_details.delivery_id
                ), 0)
            WHERE id IN (
                SELECT dd.id
                FROM delivery_details dd
                JOIN deliveries d ON d.id = dd.delivery_id
                JOIN delivery_receipts dr ON dr.delivery_detail_id = dd.id
                WHERE dr.receive_time > datetime(d.target_arrival_time, '+' || COALESCE(d.late_tolerance_minutes, 15) || ' minutes')
                  AND COALESCE(dd.shortage_qty, 0) <= 0
                  AND COALESCE(UPPER(d.status), '') NOT IN ('CANCELLED', 'CANCELED')
            )
        """)


def downgrade():
    with op.batch_alter_table("productions") as batch_op:
        batch_op.drop_column("late_tolerance_minutes")
        batch_op.drop_column("actual_completed_time")
        batch_op.drop_column("target_ready_time")

    with op.batch_alter_table("delivery_details") as batch_op:
        batch_op.drop_column("sla_minutes_late")
        batch_op.drop_column("sla_status")

    with op.batch_alter_table("deliveries") as batch_op:
        batch_op.drop_column("late_tolerance_minutes")
        batch_op.drop_column("actual_departure_time")
        batch_op.drop_column("target_arrival_time")
        batch_op.drop_column("target_dispatch_time")
