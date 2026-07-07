from app.models.master import Worker, Item, Client


ITEM_PREFINAL = {
    "RAW_MATERIAL": "BB",
    "MERCHANDISE": "WRG",
    "PACKAGING": "KMS",
    "GAS": "GAS",
    "OTHER": "OTH",
}


def generate_worker_code():
    number = Worker.query.count() + 1

    while True:
        code = f"PKJ-{number:04d}"
        existing = Worker.query.filter_by(worker_code=code).first()

        if not existing:
            return code

        number += 1


def generate_item_code(category):
    prefix = ITEM_PREFINAL.get(category, "ITM")
    number = Item.query.filter(Item.item_code.like(f"{prefix}-%")).count() + 1

    while True:
        code = f"{prefix}-{number:04d}"
        existing = Item.query.filter_by(item_code=code).first()

        if not existing:
            return code

        number += 1


def generate_client_code():
    if not hasattr(Client, "client_code"):
        return None

    number = Client.query.filter(Client.client_code.like("CL-%")).count() + 1

    while True:
        code = f"CL-{number:04d}"
        existing = Client.query.filter_by(client_code=code).first()

        if not existing:
            return code

        number += 1
