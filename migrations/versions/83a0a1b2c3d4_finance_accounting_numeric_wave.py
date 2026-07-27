"""Convert finance and accounting monetary floats to numeric.

Revision ID: 83a0a1b2c3d4
Revises: 82a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "83a0a1b2c3d4"
down_revision = "82a0a1b2c3d4"
branch_labels = None
depends_on = None


MONEY_COLUMNS = {
    "journal_details": ("debit", "credit"),
    "fixed_assets": (
        "purchase_value",
        "residual_value",
        "accumulated_depreciation",
        "book_value",
    ),
    "fixed_asset_purchases": ("amount",),
    "fixed_asset_depreciation_configs": ("residual_value",),
    "fixed_asset_depreciations": (
        "amount",
        "accumulated_depreciation_after",
        "book_value_after",
    ),
    "asset_financing_contracts": (
        "principal_amount",
        "total_interest_amount",
        "total_admin_amount",
        "total_contract_amount",
    ),
    "asset_installment_schedules": (
        "principal_amount",
        "interest_amount",
        "admin_amount",
        "total_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "asset_installment_payments": (
        "amount",
        "principal_paid",
        "interest_paid",
        "admin_paid",
    ),
    "period_closings": (
        "revenue_total",
        "expense_total",
        "net_income",
    ),
    "invoices": (
        "total_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "invoice_items": ("unit_price", "subtotal"),
    "manual_billing_batches": ("total_amount",),
    "manual_billing_batch_items": ("unit_price", "subtotal"),
    "payments": ("amount",),
    "cash_bank_transactions": ("amount",),
    "cash_bank_opening_balances": ("amount",),
    "cash_bank_transfers": ("amount",),
    "cash_bank_adjustments": ("amount",),
    "supplier_bills": (
        "total_amount",
        "paid_amount",
        "remaining_amount",
    ),
    "supplier_payments": ("amount",),
    "advance_transactions": (
        "amount",
        "settled_amount",
        "remaining_amount",
    ),
    "advance_settlements": ("amount",),
    "transport_vehicle_expenses": ("amount",),
    "operational_expenses": ("amount",),
}

QUANTITY_COLUMNS = {
    "invoice_items": ("qty",),
    "manual_billing_batch_items": ("qty",),
}

RATIO_COLUMNS = {
    "invoices": ("expected_payment_percent",),
}


ML_MANUAL_BACKFILL_CATERING_VIEW = "v_ml_erp_manual_backfill_catering"
ML_REALTIME_CATERING_VIEW = "v_ml_erp_realtime_catering"
ML_ACTIVE_CATERING_VIEW = "v_ml_erp_active_catering"
ML_TRAINING_SOURCE_VIEW = "v_ml_training_source"
ML_TRAINING_CLEAN_VIEW = "v_ml_training_clean"


def _table_exists(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _drop_dependent_views():
    for view_name in (
        ML_TRAINING_CLEAN_VIEW,
        ML_TRAINING_SOURCE_VIEW,
        ML_ACTIVE_CATERING_VIEW,
        ML_MANUAL_BACKFILL_CATERING_VIEW,
    ):
        op.execute(f"DROP VIEW IF EXISTS {view_name}")


def _create_ml_manual_backfill_catering_view():
    op.execute(
        f"""
        CREATE VIEW {ML_MANUAL_BACKFILL_CATERING_VIEW} AS
        WITH source_rows AS (
            SELECT bi.id AS item_id,
                mb.id AS batch_id,
                mb.batch_number,
                mb.period_start,
                mb.period_end,
                mb.bill_to_type,
                mb.client_id,
                mb.mandor_id,
                mb.status,
                mb.input_source,
                mb.bill_to_name_snapshot,
                mb.notes AS batch_notes,
                mb.branch_id,
                bi.description,
                bi.source_date,
                bi.source_label,
                bi.unit_price,
                bi.source_type,
                bi.source_id,
                m.name AS mandor_name,
                c.name AS client_name,
                b.code AS branch_code,
                b.name AS branch_name,
                (regexp_match(bi.description, '(?i)(Sarapan|Pagi)\\s+([0-9]+(?:[\\.,][0-9]+)?)'::text))[2] AS pagi_qty_text,
                (regexp_match(bi.description, '(?i)Siang\\s+([0-9]+(?:[\\.,][0-9]+)?)'::text))[1] AS siang_qty_text,
                (regexp_match(bi.description, '(?i)Sore\\s+([0-9]+(?:[\\.,][0-9]+)?)'::text))[1] AS sore_qty_text
            FROM manual_billing_batches mb
                JOIN manual_billing_batch_items bi ON bi.batch_id = mb.id
                LEFT JOIN mandors m ON m.id = mb.mandor_id
                LEFT JOIN clients c ON c.id = mb.client_id
                LEFT JOIN branches b ON b.id = mb.branch_id
            WHERE upper(COALESCE(mb.input_source, ''::character varying)::text) = 'MANUAL_BACKFILL'::text
                AND upper(COALESCE(bi.input_source, ''::character varying)::text) = 'MANUAL_BACKFILL'::text
                AND upper(COALESCE(bi.item_type, ''::character varying)::text) = 'CATERING'::text
                AND upper(COALESCE(bi.source_type, ''::character varying)::text) = 'MANUAL_BOOK_CATERING'::text
                AND (upper(COALESCE(mb.status, ''::character varying)::text) = ANY (ARRAY['LOCKED'::text, 'INVOICED'::text, 'PARTIALLY_PAID'::text, 'PAID'::text]))
                AND mb.locked_at IS NOT NULL
                AND mb.invoice_id IS NOT NULL
                AND COALESCE(bi.description, ''::text) !~* 'warung|kasbon'::text
        ), meal_rows AS (
            SELECT source_rows.*,
                'PAGI'::character varying(30) AS waktu_makan,
                source_rows.pagi_qty_text AS qty_text
            FROM source_rows
            UNION ALL
            SELECT source_rows.*,
                'SIANG'::character varying(30) AS waktu_makan,
                source_rows.siang_qty_text AS qty_text
            FROM source_rows
            UNION ALL
            SELECT source_rows.*,
                'SORE'::character varying(30) AS waktu_makan,
                source_rows.sore_qty_text AS qty_text
            FROM source_rows
        )
        SELECT NULL::integer AS no,
            COALESCE(meal_rows.source_date, meal_rows.period_start) AS tanggal,
            CASE
                WHEN (upper(COALESCE(meal_rows.bill_to_type, ''::character varying)::text) = ANY (ARRAY['MANDOR'::text, 'MANDOR_EXISTING'::text])) AND meal_rows.mandor_id IS NOT NULL THEN (('ERP-'::text || meal_rows.mandor_id))::character varying(50)
                ELSE (((('MB-'::text || upper(COALESCE(NULLIF(btrim(meal_rows.bill_to_type::text), ''::text), 'UNKNOWN'::text))) || '-'::text) || COALESCE(NULLIF(btrim(regexp_replace(upper(COALESCE(meal_rows.bill_to_name_snapshot, meal_rows.client_name, ''::character varying)::text), '[^A-Z0-9]+'::text, '_'::text, 'g'::text), '_'::text), ''::text), meal_rows.batch_id::text)))::character varying(50)
            END AS kode_mandor,
            CASE
                WHEN (upper(COALESCE(meal_rows.bill_to_type, ''::character varying)::text) = ANY (ARRAY['MANDOR'::text, 'MANDOR_EXISTING'::text])) AND meal_rows.mandor_id IS NOT NULL THEN COALESCE(meal_rows.mandor_name, meal_rows.bill_to_name_snapshot, ('Mandor ERP-'::text || meal_rows.mandor_id)::character varying)
                ELSE COALESCE(meal_rows.bill_to_name_snapshot, meal_rows.client_name, ('Manual Backfill '::text || meal_rows.batch_id)::character varying)
            END::character varying(150) AS nama_mandor,
            meal_rows.waktu_makan,
            round(replace(meal_rows.qty_text, ','::text, '.'::text)::numeric)::integer AS jumlah_bungkus,
            COALESCE(meal_rows.unit_price, 0::numeric) AS harga_per_bungkus,
            (round(replace(meal_rows.qty_text, ','::text, '.'::text)::numeric) * COALESCE(meal_rows.unit_price, 0::numeric))::numeric AS total_makan,
            meal_rows.period_start AS periode_mulai,
            meal_rows.period_end AS periode_selesai,
            NULL::text AS sumber_file,
            meal_rows.description AS catatan,
            meal_rows.batch_number::character varying(80) AS batch,
            'MANUAL_BACKFILL'::character varying(30) AS sumber_data,
            NULL::integer AS erp_daily_order_id,
            meal_rows.item_id AS erp_daily_order_detail_id,
            meal_rows.mandor_id AS erp_mandor_id,
            meal_rows.client_id AS erp_client_id,
            meal_rows.client_name,
            'MANUAL_BACKFILL'::character varying(30) AS data_source,
            meal_rows.input_source,
            meal_rows.status AS source_status,
            meal_rows.branch_id,
            meal_rows.branch_code,
            meal_rows.branch_name,
            meal_rows.bill_to_type::character varying(50) AS bill_to_type,
            CASE
                WHEN (upper(COALESCE(meal_rows.bill_to_type, ''::character varying)::text) = ANY (ARRAY['MANDOR'::text, 'MANDOR_EXISTING'::text])) AND meal_rows.mandor_id IS NOT NULL THEN (('ERP-'::text || meal_rows.mandor_id))::character varying(80)
                ELSE (((('MB-'::text || upper(COALESCE(NULLIF(btrim(meal_rows.bill_to_type::text), ''::text), 'UNKNOWN'::text))) || '-'::text) || COALESCE(NULLIF(btrim(regexp_replace(upper(COALESCE(meal_rows.bill_to_name_snapshot, meal_rows.client_name, ''::character varying)::text), '[^A-Z0-9]+'::text, '_'::text, 'g'::text), '_'::text), ''::text), meal_rows.batch_id::text)))::character varying(80)
            END AS bill_to_entity_code,
            COALESCE(meal_rows.bill_to_name_snapshot, meal_rows.client_name, meal_rows.mandor_name) AS bill_to_name
        FROM meal_rows
        WHERE meal_rows.qty_text IS NOT NULL
            AND round(replace(meal_rows.qty_text, ','::text, '.'::text)::numeric) > 0::numeric
        """
    )


def _create_ml_realtime_catering_view():
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {ML_REALTIME_CATERING_VIEW} AS
        SELECT NULL::integer AS no,
            o.order_date AS tanggal,
            (('ERP-'::text || m.id))::character varying(50) AS kode_mandor,
            m.name AS nama_mandor,
            'SIANG'::character varying(30) AS waktu_makan,
            d.lunch_qty AS jumlah_bungkus,
            d.price_per_portion::numeric AS harga_per_bungkus,
            (d.lunch_qty::double precision * d.price_per_portion)::numeric AS total_makan,
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
            (d.dinner_qty::double precision * d.price_per_portion)::numeric AS total_makan,
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


def _create_ml_active_catering_view():
    op.execute(
        f"""
        CREATE VIEW {ML_ACTIVE_CATERING_VIEW} AS
        SELECT v_ml_erp_realtime_catering.no,
            v_ml_erp_realtime_catering.tanggal,
            v_ml_erp_realtime_catering.kode_mandor,
            v_ml_erp_realtime_catering.nama_mandor,
            v_ml_erp_realtime_catering.waktu_makan,
            v_ml_erp_realtime_catering.jumlah_bungkus,
            v_ml_erp_realtime_catering.harga_per_bungkus,
            v_ml_erp_realtime_catering.total_makan,
            v_ml_erp_realtime_catering.periode_mulai,
            v_ml_erp_realtime_catering.periode_selesai,
            v_ml_erp_realtime_catering.sumber_file,
            v_ml_erp_realtime_catering.catatan,
            v_ml_erp_realtime_catering.batch,
            v_ml_erp_realtime_catering.sumber_data,
            v_ml_erp_realtime_catering.erp_daily_order_id,
            v_ml_erp_realtime_catering.erp_daily_order_detail_id,
            v_ml_erp_realtime_catering.erp_mandor_id,
            v_ml_erp_realtime_catering.erp_client_id,
            v_ml_erp_realtime_catering.client_name,
            v_ml_erp_realtime_catering.data_source,
            v_ml_erp_realtime_catering.input_source,
            v_ml_erp_realtime_catering.source_status,
            v_ml_erp_realtime_catering.branch_id,
            v_ml_erp_realtime_catering.branch_code,
            v_ml_erp_realtime_catering.branch_name,
            v_ml_erp_realtime_catering.bill_to_type,
            v_ml_erp_realtime_catering.bill_to_entity_code,
            v_ml_erp_realtime_catering.bill_to_name
        FROM v_ml_erp_realtime_catering
        UNION ALL
        SELECT v_ml_erp_manual_backfill_catering.no,
            v_ml_erp_manual_backfill_catering.tanggal,
            v_ml_erp_manual_backfill_catering.kode_mandor,
            v_ml_erp_manual_backfill_catering.nama_mandor,
            v_ml_erp_manual_backfill_catering.waktu_makan,
            v_ml_erp_manual_backfill_catering.jumlah_bungkus,
            v_ml_erp_manual_backfill_catering.harga_per_bungkus,
            v_ml_erp_manual_backfill_catering.total_makan,
            v_ml_erp_manual_backfill_catering.periode_mulai,
            v_ml_erp_manual_backfill_catering.periode_selesai,
            v_ml_erp_manual_backfill_catering.sumber_file,
            v_ml_erp_manual_backfill_catering.catatan,
            v_ml_erp_manual_backfill_catering.batch,
            v_ml_erp_manual_backfill_catering.sumber_data,
            v_ml_erp_manual_backfill_catering.erp_daily_order_id,
            v_ml_erp_manual_backfill_catering.erp_daily_order_detail_id,
            v_ml_erp_manual_backfill_catering.erp_mandor_id,
            v_ml_erp_manual_backfill_catering.erp_client_id,
            v_ml_erp_manual_backfill_catering.client_name,
            v_ml_erp_manual_backfill_catering.data_source,
            v_ml_erp_manual_backfill_catering.input_source,
            v_ml_erp_manual_backfill_catering.source_status,
            v_ml_erp_manual_backfill_catering.branch_id,
            v_ml_erp_manual_backfill_catering.branch_code,
            v_ml_erp_manual_backfill_catering.branch_name,
            v_ml_erp_manual_backfill_catering.bill_to_type,
            v_ml_erp_manual_backfill_catering.bill_to_entity_code,
            v_ml_erp_manual_backfill_catering.bill_to_name
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
        SELECT v_ml_erp_active_catering.no,
            v_ml_erp_active_catering.tanggal,
            v_ml_erp_active_catering.kode_mandor,
            v_ml_erp_active_catering.nama_mandor,
            v_ml_erp_active_catering.waktu_makan,
            v_ml_erp_active_catering.jumlah_bungkus,
            v_ml_erp_active_catering.harga_per_bungkus,
            v_ml_erp_active_catering.total_makan,
            v_ml_erp_active_catering.periode_mulai,
            v_ml_erp_active_catering.periode_selesai,
            v_ml_erp_active_catering.sumber_file,
            v_ml_erp_active_catering.catatan,
            v_ml_erp_active_catering.batch,
            v_ml_erp_active_catering.sumber_data,
            v_ml_erp_active_catering.erp_daily_order_id,
            v_ml_erp_active_catering.erp_daily_order_detail_id,
            v_ml_erp_active_catering.erp_mandor_id,
            v_ml_erp_active_catering.erp_client_id,
            v_ml_erp_active_catering.client_name,
            v_ml_erp_active_catering.data_source,
            v_ml_erp_active_catering.input_source,
            v_ml_erp_active_catering.source_status,
            v_ml_erp_active_catering.branch_id,
            v_ml_erp_active_catering.branch_code,
            v_ml_erp_active_catering.branch_name,
            v_ml_erp_active_catering.bill_to_type,
            v_ml_erp_active_catering.bill_to_entity_code,
            v_ml_erp_active_catering.bill_to_name
        FROM v_ml_erp_active_catering
        """
    )


def _create_ml_training_clean_view():
    op.execute(
        f"""
        CREATE VIEW {ML_TRAINING_CLEAN_VIEW} AS
        WITH filtered AS (
            SELECT v_ml_training_source.no,
                v_ml_training_source.tanggal,
                v_ml_training_source.kode_mandor,
                v_ml_training_source.nama_mandor,
                v_ml_training_source.waktu_makan,
                v_ml_training_source.jumlah_bungkus,
                v_ml_training_source.harga_per_bungkus,
                v_ml_training_source.total_makan,
                v_ml_training_source.periode_mulai,
                v_ml_training_source.periode_selesai,
                v_ml_training_source.sumber_file,
                v_ml_training_source.catatan,
                v_ml_training_source.batch,
                v_ml_training_source.sumber_data,
                v_ml_training_source.erp_daily_order_id,
                v_ml_training_source.erp_daily_order_detail_id,
                v_ml_training_source.erp_mandor_id,
                v_ml_training_source.erp_client_id,
                v_ml_training_source.client_name,
                v_ml_training_source.data_source,
                v_ml_training_source.input_source,
                v_ml_training_source.source_status,
                v_ml_training_source.branch_id,
                v_ml_training_source.branch_code,
                v_ml_training_source.branch_name,
                v_ml_training_source.bill_to_type,
                v_ml_training_source.bill_to_entity_code,
                v_ml_training_source.bill_to_name,
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
    _create_ml_manual_backfill_catering_view()
    _create_ml_realtime_catering_view()
    _create_ml_active_catering_view()
    if _table_exists("ml_catering_historical"):
        _create_ml_training_source_view()
        _create_ml_training_clean_view()


def _alter_to_numeric(table_name, column_name, precision, scale):
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.Float(),
        type_=sa.Numeric(precision, scale),
        existing_nullable=False,
        postgresql_using=f"round({column_name}::numeric, {scale})",
    )


def _alter_to_float(table_name, column_name, precision, scale):
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.Numeric(precision, scale),
        type_=sa.Float(),
        existing_nullable=False,
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
