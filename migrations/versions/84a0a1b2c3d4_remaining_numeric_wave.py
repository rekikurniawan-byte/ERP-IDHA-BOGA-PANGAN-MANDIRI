"""Convert remaining model floats to numeric.

Revision ID: 84a0a1b2c3d4
Revises: 83a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "84a0a1b2c3d4"
down_revision = "83a0a1b2c3d4"
branch_labels = None
depends_on = None


MONEY_COLUMNS = {
    "daily_order_details": ("price_per_portion",),
    "order_revisions": ("price_per_portion",),
    "order_hpp_snapshots": (
        "food_cost_total",
        "packaging_cost_total",
        "overhead_cost_total",
        "hpp_total",
        "hpp_per_portion",
        "revenue_total",
        "gross_margin_amount",
    ),
    "order_hpp_snapshot_lines": (
        "selling_price_per_portion",
        "food_cost_total",
        "packaging_cost_total",
        "overhead_cost_total",
        "hpp_total",
        "hpp_per_portion",
        "revenue_total",
        "gross_margin_amount",
    ),
    "order_hpp_snapshot_components": (
        "cost_per_base_unit_snapshot",
        "cost_per_portion",
        "cost_total",
    ),
    "order_hpp_snapshot_allocations": (
        "selling_price_per_portion",
        "revenue_total",
        "food_cost_allocated_total",
        "packaging_cost_allocated_total",
        "overhead_cost_allocated_total",
        "hpp_allocated_total",
        "hpp_per_portion_snapshot",
        "gross_margin_amount",
    ),
    "order_hpp_stock_consumptions": ("total_cost",),
    "order_hpp_stock_consumption_lines": ("estimated_cost_total",),
    "items": ("selling_price",),
    "item_cost_profiles": (
        "standard_purchase_price",
        "effective_cost_per_base_unit",
    ),
    "menus": ("default_selling_price",),
    "packaging_profiles": ("cost_per_portion",),
    "overhead_profiles": (
        "gas_cost_per_portion",
        "electricity_cost_per_portion",
        "water_cost_per_portion",
        "labor_cost_per_portion",
        "spices_cost_per_portion",
        "other_cost_per_portion",
    ),
    "procurements": ("total_amount",),
    "procurement_items": ("unit_price", "subtotal"),
    "payroll_details": (
        "base_salary",
        "bonus",
        "deduction",
        "final_salary",
    ),
    "employee_salary_history": ("salary_amount",),
    "field_transactions": ("amount",),
    "field_transaction_settlements": ("amount",),
    "manual_receivables": (
        "total_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "manual_receivable_payments": ("amount",),
    "manual_payables": (
        "total_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "manual_payable_payments": ("amount",),
    "canteen_sales": ("total_amount",),
    "canteen_sale_items": ("price", "subtotal"),
    "worker_debts": ("debt_amount",),
    "debt_payments": ("amount",),
    "canteen_external_receivables": (
        "receivable_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "canteen_external_receivable_payments": ("amount",),
    "cash_daily": (
        "opening_balance",
        "cash_sales",
        "debt_payments",
        "other_income",
        "expenses",
        "closing_balance",
        "actual_cash",
        "cash_difference",
    ),
    "cash_expenses": ("amount",),
}

QUANTITY_COLUMNS = {
    "production_details": ("planned_qty", "actual_qty"),
    "order_hpp_snapshots": ("total_portion",),
    "order_hpp_snapshot_lines": ("portion_qty",),
    "order_hpp_snapshot_components": (
        "qty_per_portion",
        "base_qty_per_portion",
        "base_qty_total",
    ),
    "order_hpp_snapshot_allocations": ("portion_qty",),
    "order_hpp_stock_consumptions": ("total_required_qty",),
    "order_hpp_stock_consumption_lines": (
        "required_stock_qty",
        "stock_before_qty",
        "stock_after_qty",
    ),
    "items": ("minimum_stock",),
    "item_cost_profiles": ("purchase_qty",),
    "recipe_headers": ("base_portion",),
    "recipe_items": ("qty_per_portion",),
    "recipe_versions": ("base_portion",),
    "recipe_version_items": ("qty_per_portion",),
    "procurement_items": ("qty",),
    "stock_movements": ("qty",),
    "damaged_items": ("qty",),
    "stock_adjustments": (
        "system_qty",
        "actual_qty",
        "difference_qty",
    ),
    "item_request_details": (
        "qty",
        "requested_qty",
        "approved_qty",
        "fulfilled_qty",
    ),
}

RATIO_COLUMNS = {
    "order_hpp_snapshots": (
        "gross_margin_percentage",
        "target_margin_percentage",
    ),
    "order_hpp_snapshot_lines": ("gross_margin_percentage",),
    "order_hpp_snapshot_components": ("conversion_multiplier",),
    "order_hpp_snapshot_allocations": (
        "allocation_ratio",
        "gross_margin_percentage",
    ),
    "unit_conversions": ("multiplier",),
    "item_cost_profiles": (
        "conversion_factor",
        "yield_percentage",
        "waste_percentage",
    ),
    "overhead_profiles": ("overhead_percentage",),
}

NULLABLE_COLUMNS = {
    ("order_revisions", "price_per_portion"),
    ("order_hpp_snapshot_components", "conversion_multiplier"),
}


ML_REALTIME_CATERING_VIEW = "v_ml_erp_realtime_catering"
ML_ACTIVE_CATERING_VIEW = "v_ml_erp_active_catering"
ML_TRAINING_SOURCE_VIEW = "v_ml_training_source"
ML_TRAINING_CLEAN_VIEW = "v_ml_training_clean"
DAILY_CATERING_VIEW = "daily_catering"


def _table_exists(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _drop_dependent_views():
    for view_name in (
        ML_TRAINING_CLEAN_VIEW,
        ML_TRAINING_SOURCE_VIEW,
        ML_ACTIVE_CATERING_VIEW,
        ML_REALTIME_CATERING_VIEW,
        DAILY_CATERING_VIEW,
    ):
        op.execute(f"DROP VIEW IF EXISTS {view_name}")


def _create_ml_realtime_catering_view():
    op.execute(
        f"""
        CREATE VIEW {ML_REALTIME_CATERING_VIEW} AS
        SELECT NULL::integer AS no,
            o.order_date AS tanggal,
            (('ERP-'::text || m.id))::character varying(50) AS kode_mandor,
            m.name AS nama_mandor,
            'SIANG'::character varying(30) AS waktu_makan,
            d.lunch_qty AS jumlah_bungkus,
            d.price_per_portion::numeric AS harga_per_bungkus,
            (d.lunch_qty::numeric * d.price_per_portion::numeric) AS total_makan,
            o.order_date AS periode_mulai,
            o.order_date AS periode_selesai,
            NULL::text AS sumber_file,
            d.notes AS catatan,
            (('ERP_ORDER_'::text || o.id))::character varying(80) AS batch,
            'ERP_ACTIVE'::character varying(30) AS sumber_data,
            o.id AS erp_daily_order_id,
            d.id AS erp_daily_order_detail_id,
            m.id AS erp_mandor_id,
            c.id AS erp_client_id,
            c.name AS client_name,
            'REALTIME'::character varying(30) AS data_source,
            'REALTIME'::character varying(30) AS input_source,
            o.status AS source_status,
            b.id AS branch_id,
            b.code AS branch_code,
            b.name AS branch_name,
            'MANDOR_EXISTING'::character varying(50) AS bill_to_type,
            (('ERP-'::text || m.id))::character varying(80) AS bill_to_entity_code,
            m.name AS bill_to_name
        FROM daily_orders o
            JOIN daily_order_details d ON d.daily_order_id = o.id
            JOIN mandors m ON m.id = d.mandor_id
            JOIN clients c ON c.id = m.client_id
            LEFT JOIN branches b ON b.id = o.branch_id
        WHERE o.is_locked = true
            AND COALESCE(d.lunch_qty, 0) > 0
            AND (upper(COALESCE(o.status, ''::character varying)::text) <> ALL (ARRAY['DRAFT'::text, 'VOID'::text, 'CANCELLED'::text, 'CANCELED'::text]))
        UNION ALL
        SELECT NULL::integer AS no,
            o.order_date AS tanggal,
            (('ERP-'::text || m.id))::character varying(50) AS kode_mandor,
            m.name AS nama_mandor,
            'SORE'::character varying(30) AS waktu_makan,
            d.dinner_qty AS jumlah_bungkus,
            d.price_per_portion::numeric AS harga_per_bungkus,
            (d.dinner_qty::numeric * d.price_per_portion::numeric) AS total_makan,
            o.order_date AS periode_mulai,
            o.order_date AS periode_selesai,
            NULL::text AS sumber_file,
            d.notes AS catatan,
            (('ERP_ORDER_'::text || o.id))::character varying(80) AS batch,
            'ERP_ACTIVE'::character varying(30) AS sumber_data,
            o.id AS erp_daily_order_id,
            d.id AS erp_daily_order_detail_id,
            m.id AS erp_mandor_id,
            c.id AS erp_client_id,
            c.name AS client_name,
            'REALTIME'::character varying(30) AS data_source,
            'REALTIME'::character varying(30) AS input_source,
            o.status AS source_status,
            b.id AS branch_id,
            b.code AS branch_code,
            b.name AS branch_name,
            'MANDOR_EXISTING'::character varying(50) AS bill_to_type,
            (('ERP-'::text || m.id))::character varying(80) AS bill_to_entity_code,
            m.name AS bill_to_name
        FROM daily_orders o
            JOIN daily_order_details d ON d.daily_order_id = o.id
            JOIN mandors m ON m.id = d.mandor_id
            JOIN clients c ON c.id = m.client_id
            LEFT JOIN branches b ON b.id = o.branch_id
        WHERE o.is_locked = true
            AND COALESCE(d.dinner_qty, 0) > 0
            AND (upper(COALESCE(o.status, ''::character varying)::text) <> ALL (ARRAY['DRAFT'::text, 'VOID'::text, 'CANCELLED'::text, 'CANCELED'::text]))
        """
    )


def _create_daily_catering_view():
    op.execute(
        f"""
        CREATE VIEW {DAILY_CATERING_VIEW} AS
        SELECT ml_catering_historical.kode_mandor,
            ml_catering_historical.tanggal,
            ml_catering_historical.waktu_makan,
            ml_catering_historical.jumlah_bungkus,
            ml_catering_historical.harga_per_bungkus,
            ml_catering_historical.sumber_data
        FROM ml_catering_historical
        UNION ALL
        SELECT mm.kode_mandor,
            do2.order_date AS tanggal,
            'siang'::character varying AS waktu_makan,
            dod.lunch_qty AS jumlah_bungkus,
            dod.price_per_portion::numeric(12, 2) AS harga_per_bungkus,
            'DETAIL_HARIAN_ASLI'::character varying AS sumber_data
        FROM daily_order_details dod
            JOIN daily_orders do2 ON do2.id = dod.daily_order_id
            JOIN ml_mandor mm ON mm.erp_mandor_id = dod.mandor_id
        WHERE do2.is_locked = true
            AND dod.lunch_qty > 0
        UNION ALL
        SELECT mm.kode_mandor,
            do2.order_date AS tanggal,
            'sore'::character varying AS waktu_makan,
            dod.dinner_qty AS jumlah_bungkus,
            dod.price_per_portion::numeric(12, 2) AS harga_per_bungkus,
            'DETAIL_HARIAN_ASLI'::character varying AS sumber_data
        FROM daily_order_details dod
            JOIN daily_orders do2 ON do2.id = dod.daily_order_id
            JOIN ml_mandor mm ON mm.erp_mandor_id = dod.mandor_id
        WHERE do2.is_locked = true
            AND dod.dinner_qty > 0
        """
    )


def _create_ml_active_catering_view():
    op.execute(
        f"""
        CREATE VIEW {ML_ACTIVE_CATERING_VIEW} AS
        SELECT *
        FROM v_ml_erp_realtime_catering
        UNION ALL
        SELECT *
        FROM v_ml_erp_manual_backfill_catering
        """
    )


def _create_ml_training_source_view():
    op.execute(
        f"""
        CREATE VIEW {ML_TRAINING_SOURCE_VIEW} AS
        SELECT ml_catering_historical.no,
            ml_catering_historical.tanggal,
            ml_catering_historical.kode_mandor,
            ml_catering_historical.nama_mandor,
            ml_catering_historical.waktu_makan,
            ml_catering_historical.jumlah_bungkus,
            ml_catering_historical.harga_per_bungkus,
            ml_catering_historical.total_makan,
            ml_catering_historical.periode_mulai,
            ml_catering_historical.periode_selesai,
            ml_catering_historical.sumber_file,
            ml_catering_historical.catatan,
            ml_catering_historical.batch,
            ml_catering_historical.sumber_data,
            NULL::integer AS erp_daily_order_id,
            NULL::integer AS erp_daily_order_detail_id,
            NULL::integer AS erp_mandor_id,
            NULL::integer AS erp_client_id,
            NULL::character varying(150) AS client_name,
            COALESCE(ml_catering_historical.sumber_data, 'HISTORICAL'::character varying)::character varying(30) AS data_source,
            'HISTORICAL'::character varying(30) AS input_source,
            'FINAL'::character varying(30) AS source_status,
            NULL::integer AS branch_id,
            NULL::character varying(50) AS branch_code,
            NULL::character varying(150) AS branch_name,
            'MANDOR_HISTORICAL'::character varying(50) AS bill_to_type,
            ml_catering_historical.kode_mandor::character varying(80) AS bill_to_entity_code,
            ml_catering_historical.nama_mandor::character varying(150) AS bill_to_name
        FROM ml_catering_historical
        UNION ALL
        SELECT *
        FROM v_ml_erp_active_catering
        """
    )


def _create_ml_training_clean_view():
    op.execute(
        f"""
        CREATE VIEW {ML_TRAINING_CLEAN_VIEW} AS
        WITH filtered AS (
            SELECT v_ml_training_source.*,
                upper(btrim(v_ml_training_source.waktu_makan::text)) AS waktu_makan_clean
            FROM v_ml_training_source
            WHERE v_ml_training_source.tanggal IS NOT NULL
                AND v_ml_training_source.kode_mandor IS NOT NULL
                AND v_ml_training_source.waktu_makan IS NOT NULL
                AND v_ml_training_source.jumlah_bungkus IS NOT NULL
                AND v_ml_training_source.jumlah_bungkus > 0
                AND (upper(btrim(v_ml_training_source.waktu_makan::text)) = ANY (ARRAY['SIANG'::text, 'SORE'::text, 'PAGI'::text, 'MALAM'::text]))
        ), ranked AS (
            SELECT filtered.*,
                row_number() OVER (PARTITION BY filtered.tanggal, filtered.kode_mandor, filtered.waktu_makan_clean ORDER BY filtered.jumlah_bungkus DESC, filtered.total_makan DESC NULLS LAST) AS rn
            FROM filtered
        )
        SELECT ranked.no,
            ranked.tanggal,
            ranked.kode_mandor,
            ranked.nama_mandor,
            ranked.waktu_makan_clean AS waktu_makan,
            ranked.jumlah_bungkus,
            ranked.harga_per_bungkus,
            ranked.total_makan,
            ranked.periode_mulai,
            ranked.periode_selesai,
            ranked.sumber_file,
            ranked.catatan,
            ranked.batch,
            ranked.sumber_data,
            ranked.erp_daily_order_id,
            ranked.erp_daily_order_detail_id,
            ranked.erp_mandor_id,
            ranked.erp_client_id,
            ranked.client_name,
            ranked.data_source,
            ranked.input_source,
            ranked.source_status,
            ranked.branch_id,
            ranked.branch_code,
            ranked.branch_name,
            ranked.bill_to_type,
            ranked.bill_to_entity_code,
            ranked.bill_to_name
        FROM ranked
        WHERE ranked.rn = 1
        """
    )


def _create_dependent_views():
    if _table_exists("ml_catering_historical") and _table_exists("ml_mandor"):
        _create_daily_catering_view()
    _create_ml_realtime_catering_view()
    _create_ml_active_catering_view()
    if _table_exists("ml_catering_historical"):
        _create_ml_training_source_view()
        _create_ml_training_clean_view()


def _is_nullable(table_name, column_name):
    return (table_name, column_name) in NULLABLE_COLUMNS


def _alter_to_numeric(table_name, column_name, precision, scale):
    if not _column_exists(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.Float(),
        type_=sa.Numeric(precision, scale),
        existing_nullable=_is_nullable(table_name, column_name),
        postgresql_using=f"round({column_name}::numeric, {scale})",
    )


def _alter_to_float(table_name, column_name, precision, scale):
    if not _column_exists(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.Numeric(precision, scale),
        type_=sa.Float(),
        existing_nullable=_is_nullable(table_name, column_name),
        postgresql_using=f"{column_name}::double precision",
    )


def upgrade():
    _drop_dependent_views()

    for table_name, column_names in MONEY_COLUMNS.items():
        for column_name in column_names:
            _alter_to_numeric(table_name, column_name, 18, 2)

    for table_name, column_names in QUANTITY_COLUMNS.items():
        for column_name in column_names:
            _alter_to_numeric(table_name, column_name, 18, 4)

    for table_name, column_names in RATIO_COLUMNS.items():
        for column_name in column_names:
            _alter_to_numeric(table_name, column_name, 8, 4)

    _create_dependent_views()


def downgrade():
    _drop_dependent_views()

    for table_name, column_names in RATIO_COLUMNS.items():
        for column_name in column_names:
            _alter_to_float(table_name, column_name, 8, 4)

    for table_name, column_names in QUANTITY_COLUMNS.items():
        for column_name in column_names:
            _alter_to_float(table_name, column_name, 18, 4)

    for table_name, column_names in MONEY_COLUMNS.items():
        for column_name in column_names:
            _alter_to_float(table_name, column_name, 18, 2)

    _create_dependent_views()
