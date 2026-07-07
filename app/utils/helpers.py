def format_rupiah(value):
    try:
        value = float(value or 0)
    except (ValueError, TypeError):
        value = 0

    value = int(value)
    return "Rp {:,}".format(value).replace(",", ".")
