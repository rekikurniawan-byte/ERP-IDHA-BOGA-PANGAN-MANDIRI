from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

statements = [
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS input_source VARCHAR(30) NOT NULL DEFAULT 'REALTIME'",
    "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS input_source VARCHAR(30) NOT NULL DEFAULT 'REALTIME'",
    "ALTER TABLE manual_billing_batches ADD COLUMN IF NOT EXISTS input_source VARCHAR(30) NOT NULL DEFAULT 'REALTIME'",
    "ALTER TABLE manual_billing_batch_items ADD COLUMN IF NOT EXISTS input_source VARCHAR(30) NOT NULL DEFAULT 'REALTIME'",

    "CREATE INDEX IF NOT EXISTS ix_invoices_input_source ON invoices (input_source)",
    "CREATE INDEX IF NOT EXISTS ix_invoice_items_input_source ON invoice_items (input_source)",
    "CREATE INDEX IF NOT EXISTS ix_manual_billing_batches_input_source ON manual_billing_batches (input_source)",
    "CREATE INDEX IF NOT EXISTS ix_manual_billing_batch_items_input_source ON manual_billing_batch_items (input_source)",

    "ALTER TABLE manual_billing_batches ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP NULL",
    "ALTER TABLE manual_billing_batches ADD COLUMN IF NOT EXISTS locked_by INTEGER NULL",
    "CREATE INDEX IF NOT EXISTS ix_manual_billing_batches_locked_at ON manual_billing_batches (locked_at)",

    "UPDATE invoices SET input_source = 'REALTIME' WHERE input_source IS NULL",
    "UPDATE invoice_items SET input_source = 'REALTIME' WHERE input_source IS NULL",
    "UPDATE manual_billing_batches SET input_source = 'REALTIME' WHERE input_source IS NULL",
    "UPDATE manual_billing_batch_items SET input_source = 'REALTIME' WHERE input_source IS NULL",
]

with app.app_context():
    with db.engine.begin() as conn:
        for sql in statements:
            print(sql)
            conn.execute(text(sql))

    print("SCHEMA REPAIR DONE")
