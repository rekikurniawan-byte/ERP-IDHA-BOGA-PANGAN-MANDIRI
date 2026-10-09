from app.extensions import db
from app.models.production import Production, ProductionDetail
from app.models.master import Item
from app.utils.terms import T


PRODUCTION_ITEM_CODE = "PROD-CATERING-PORSI"


def get_or_create_production_item():
    item = Item.query.filter_by(item_code=PRODUCTION_ITEM_CODE).first()

    if item:
        return item

    item = Item(
        item_code=PRODUCTION_ITEM_CODE,
        item_name="Porsi Catering Proyek",
        category="OTHER",
        unit="PORSI",
        minimum_stock=0,
        is_stock_tracked=False,
        is_active=True
    )

    db.session.add(item)
    db.session.flush()

    return item


def calculate_order_total(daily_order):
    lunch_total = 0
    dinner_total = 0

    for detail in daily_order.details:
        lunch_total += detail.lunch_qty
        dinner_total += detail.dinner_qty

    return lunch_total, dinner_total


def sync_single_production(daily_order, production_type, planned_qty, created_by):
    item = get_or_create_production_item()

    production = Production.query.filter_by(
        branch_id=daily_order.branch_id,
        production_date=daily_order.order_date,
        production_type=production_type
    ).first()

    if not production:
        production = Production(
            branch_id=daily_order.branch_id,
            production_date=daily_order.order_date,
            production_type=production_type,
            status="DRAFT",
            notes=f"Rencana produksi {production_type} dari order {daily_order.order_number}",
            created_by=created_by
        )

        db.session.add(production)
        db.session.flush()

        detail = ProductionDetail(
            production_id=production.id,
            item_id=item.id,
            planned_qty=planned_qty,
            actual_qty=0,
            unit="PORSI",
            notes=f"Total porsi {production_type} dari order locked"
        )

        db.session.add(detail)

        return "CREATED"

    detail = production.details[0] if production.details else None

    if not detail:
        detail = ProductionDetail(
            production_id=production.id,
            item_id=item.id,
            planned_qty=planned_qty,
            actual_qty=0,
            unit="PORSI",
            notes=f"Total porsi {production_type} dari order locked"
        )

        db.session.add(detail)

        if production.status == "COMPLETED":
            production.status = "IN_PROGRESS"

        return "DETAIL_CREATED"

    old_planned_qty = detail.planned_qty
    detail.planned_qty = planned_qty
    detail.notes = f"Total porsi {production_type} dari order {daily_order.order_number}"

    if planned_qty != old_planned_qty:
        production.notes = f"Rencana produksi {production_type} dari order {daily_order.order_number}"

        if detail.actual_qty < planned_qty:
            production.status = "IN_PROGRESS"
            return "UPDATED_NEED_ADDITIONAL"

        return "UPDATED"

    if detail.actual_qty < detail.planned_qty and production.status == "COMPLETED":
        production.status = "IN_PROGRESS"
        return "STATUS_FINALED"

    return "SYNCED"


def generate_production_from_order(daily_order, created_by, commit=True):
    if not daily_order.is_locked:
        return False, "Produksi hanya bisa dibuat dari order yang sudah LOCKED."

    if not daily_order.details:
        return False, f"Order belum memiliki detail {T.sub_client_lower}/lokasi."

    lunch_total, dinner_total = calculate_order_total(daily_order)

    results = []

    if lunch_total > 0:
        lunch_result = sync_single_production(
            daily_order=daily_order,
            production_type="LUNCH",
            planned_qty=lunch_total,
            created_by=created_by
        )
        results.append(f"LUNCH {lunch_total} porsi ({lunch_result})")

    if dinner_total > 0:
        dinner_result = sync_single_production(
            daily_order=daily_order,
            production_type="DINNER",
            planned_qty=dinner_total,
            created_by=created_by
        )
        results.append(f"DINNER {dinner_total} porsi ({dinner_result})")

    if not results:
        return False, "Tidak ada porsi siang atau sore untuk dibuat produksi."

    # commit=False: pemanggil (mis. ubah porsi Fase 5) menyimpan semuanya dalam
    # satu transaksi, supaya produksi tidak tersimpan sendiri kalau langkah lain gagal.
    if commit:
        db.session.commit()
    else:
        db.session.flush()

    return True, "Produksi berhasil disinkronkan: " + ", ".join(results)
