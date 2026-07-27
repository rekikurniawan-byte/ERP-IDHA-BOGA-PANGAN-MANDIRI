from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.logistics import StockMovement, StockOpeningBalance
from app.models.master import Item
from app.services.business_logic_guard_service import (
    STOCK_IN_TYPES as GUARDED_STOCK_IN_TYPES,
    STOCK_OUT_TYPES as GUARDED_STOCK_OUT_TYPES,
    BusinessRuleError,
    validate_stock_movement_guard,
)


STOCK_IN_TYPES = list(GUARDED_STOCK_IN_TYPES)
STOCK_OUT_TYPES = list(GUARDED_STOCK_OUT_TYPES)

INTEGER_UNIT_KEYWORDS = ["pcs", "pc", "tabung", "pak", "pack", "dus", "box", "unit", "karung", "sak"]


def _to_decimal(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return None


def is_integer_unit(unit):
    unit_text = (unit or "").strip().lower()
    return any(keyword in unit_text for keyword in INTEGER_UNIT_KEYWORDS)



def get_stock_items():
    return Item.query.filter(
        Item.is_active == True,
        Item.is_stock_tracked == True,
        Item.category != "MERCHANDISE"
    ).order_by(Item.item_name.asc()).all()


def get_stock_opening_balance(branch_id, item_id):
    return StockOpeningBalance.query.filter_by(
        branch_id=branch_id,
        item_id=item_id,
    ).first()


def save_stock_opening_balance(branch_id, item_id, opening_date, qty, notes, created_by):
    item = Item.query.get(item_id)
    if not item:
        return False, "Item tidak ditemukan.", None
    if not item.is_stock_tracked:
        return False, "Item ini tidak dilacak stoknya.", None

    qty = _to_decimal(qty)
    if qty is None:
        return False, "Saldo awal stok tidak valid.", None
    if qty < 0:
        return False, "Saldo awal stok tidak boleh negatif.", None

    opening = get_stock_opening_balance(branch_id, item_id)
    if opening:
        opening.opening_date = opening_date
        opening.qty = qty
        opening.notes = notes
    else:
        opening = StockOpeningBalance(
            branch_id=branch_id,
            item_id=item_id,
            opening_date=opening_date,
            qty=qty,
            notes=notes,
            created_by=created_by,
        )
        db.session.add(opening)

    db.session.commit()
    return True, "Saldo awal stok berhasil disimpan.", opening


def movement_sign(movement_type):
    if movement_type in STOCK_IN_TYPES:
        return 1

    if movement_type in STOCK_OUT_TYPES:
        return -1

    return 0


def get_item_stock(branch_id, item_id):
    opening = StockOpeningBalance.query.filter_by(
        branch_id=branch_id,
        item_id=item_id,
    ).first()
    query = StockMovement.query.filter_by(
        branch_id=branch_id,
        item_id=item_id
    )
    total = Decimal(opening.qty or 0) if opening else Decimal("0")

    if opening:
        query = query.filter(StockMovement.movement_date >= opening.opening_date)

    for movement in query.all():
        total += Decimal(movement_sign(movement.movement_type)) * Decimal(movement.qty or 0)

    return total


def get_item_stock_for_update(branch_id, item_id):
    """Get item stock with row-level lock to prevent concurrent stock OUT race condition.

    Use this instead of get_item_stock() when creating stock OUT movements
    to ensure no two concurrent transactions can overdraw the same item.
    """
    opening = StockOpeningBalance.query.filter_by(
        branch_id=branch_id,
        item_id=item_id,
    ).with_for_update().first()
    opening_qty = Decimal(opening.qty or 0) if opening else Decimal("0")
    query = StockMovement.query.filter_by(branch_id=branch_id, item_id=item_id)
    if opening:
        query = query.filter(StockMovement.movement_date >= opening.opening_date)

    total = opening_qty
    for movement in query.with_for_update().all():
        total += Decimal(movement_sign(movement.movement_type)) * Decimal(movement.qty or 0)

    return total


def get_stock_summary(branch_id):
    items = get_stock_items()
    rows = []

    total_items = 0
    low_stock_count = 0
    out_stock_count = 0

    for item in items:
        stock_qty = get_item_stock(branch_id, item.id)

        if stock_qty <= Decimal("0"):
            stock_status = "OUT"
            out_stock_count += 1
        elif stock_qty <= Decimal(item.minimum_stock or 0):
            stock_status = "LOW"
            low_stock_count += 1
        else:
            stock_status = "SAFE"

        rows.append({
            "item": item,
            "stock_qty": stock_qty,
            "stock_status": stock_status
        })

        total_items += 1

    return {
        "rows": rows,
        "total_items": total_items,
        "low_stock_count": low_stock_count,
        "out_stock_count": out_stock_count
    }


def create_stock_movement(
    branch_id,
    item_id,
    movement_date,
    movement_type,
    reference_type,
    qty,
    notes,
    created_by
):
    item = Item.query.get(item_id)

    if not item:
        return False, "Item tidak ditemukan.", None

    if not item.is_active:
        return False, "Item tidak aktif, tidak bisa digunakan untuk transaksi stok.", None

    if not item.is_stock_tracked:
        return False, "Item ini tidak dilacak stoknya.", None

    qty = float(qty or 0)

    # Use locked read for OUT movements to prevent concurrent overdraw
    if movement_type in ("OUT", "ADJUSTMENT_OUT"):
        current_stock = get_item_stock_for_update(branch_id, item_id)
    else:
        current_stock = get_item_stock(branch_id, item_id)

    try:
        qty = validate_stock_movement_guard(
            movement_type,
            qty,
            current_stock=current_stock,
            item_unit=item.unit,
            is_integer_unit=is_integer_unit(item.unit),
        )
    except BusinessRuleError as error:
        return False, str(error), None

    movement = StockMovement(
        branch_id=branch_id,
        item_id=item_id,
        movement_date=movement_date,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=None,
        qty=qty,
        notes=notes,
        created_by=created_by
    )

    db.session.add(movement)
    db.session.commit()

    return True, "Pergerakan stok berhasil disimpan.", movement


def get_recent_movements(branch_id, limit=20):
    return StockMovement.query.filter_by(
        branch_id=branch_id
    ).order_by(
        StockMovement.movement_date.desc(),
        StockMovement.id.desc()
    ).limit(limit).all()


def get_item_movements(branch_id, item_id):
    return StockMovement.query.filter_by(
        branch_id=branch_id,
        item_id=item_id
    ).order_by(
        StockMovement.movement_date.desc(),
        StockMovement.id.desc()
    ).all()
