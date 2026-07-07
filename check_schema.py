from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    rows = db.session.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'invoices'
          AND column_name = 'input_source'
    """)).fetchall()

    print(rows)

    if rows:
        print("OK: invoices.input_source sudah ada")
    else:
        print("ERROR: invoices.input_source belum ada")
