"""Satu penilai kredit, dibaca semua jalur order.

Sebelum ini gerbang kredit cuma ada di draft order portal, dan gerbang itu pun
tidak memblokir apa-apa. Jalur order internal ADMIN sama sekali tidak punya
gerbang. Akibatnya kasus paling berisiko -- mandor ditagih langsung karena PT
pemilik proyek tidak mau menjamin -- justru yang paling tidak terlindungi.

Polanya sengaja meniru app/utils/roles.py: satu tabel kebenaran, dibaca route
dan template sekaligus, supaya gerbang portal dan gerbang internal tidak bisa
lagi berbeda pendapat.

Alur lengkapnya di BLUEPRINT_V2_KONTROL_KREDIT.md.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import re

from app.extensions import db
from app.models.credit import (
    BILLING_CASH,
    BILLING_DIRECT,
    BILLING_VIA_CLIENT,
    CREDIT_STATUS_ORDER,
    PARTY_CLIENT,
    PARTY_MANDOR,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_HOLD,
    STATUS_WATCH,
    STATUS_WRITE_OFF,
    CreditAccount,
)
from app.models.finance import Invoice, InvoiceCollectionLog, Payment
from app.models.master import BranchSetting
from app.models.operational import DailyOrder, DailyOrderDetail
from app.utils.terms import T


ZERO = Decimal("0")

# Invoice yang sudah tidak menagih apa-apa lagi.
SETTLED_INVOICE_STATUSES = ("CANCELLED", "PAID", "CLOSED")

# Siklus order harian di operational_service hanya DRAFT -> LOCKED, plus
# CANCELLED. Order DRAFT ikut dihitung: itu makanan yang sebentar lagi dimasak
# dan diantar, dan untuk kredit lebih aman menghitungnya terlalu awal daripada
# terlambat. Konvensi != "CANCELLED" sama dengan yang dipakai portal.
CANCELLED_ORDER_STATUS = "CANCELLED"

# Satu-satunya tempat nilai bawaan. Baris branch_settings dengan key yang sama
# hanya menimpa nilai ini untuk satu cabang; cabang tanpa baris memakai ini.
DEFAULT_THRESHOLDS = {
    # Keputusan owner 2026-10-06 (Fase 3): tempo bawaan kredit langsung 7 hari, menggantikan 14 hari lama.
    "credit.terms_days_direct": 7,
    # Keputusan owner 2026-09-25: limit dari kebutuhan order (termin + 7 hari
    # cadangan), deposit 20% dari limit.
    "credit.limit_buffer_days": 7,
    "credit.deposit_percent": 20,
    "credit.watch_exposure_pct": 75,
    "credit.watch_days_overdue": 1,
    "credit.hold_days_overdue": 8,
    "credit.blocked_days_overdue": 22,
    "credit.write_off_days_overdue": 61,
    "credit.broken_promise_hold": 1,
    "credit.broken_promise_blocked": 2,
}

# Jatuh tempo lama waktu tidak ada termin sama sekali. Sengaja sama dengan
# angka yang selama ini di-hardcode di period_invoice_routes.py, supaya
# mengaktifkan termin tidak mengubah perilaku invoice yang belum diatur.
LEGACY_FALLBACK_TERMS_DAYS = 7

AGING_BUCKETS = ("belum_jatuh_tempo", "1_7", "8_21", "22_60", "60_plus")


def _money(value):
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def parse_terms_days(value):
    """Ambil angka hari dari termin teks bebas seperti "net 30" atau "NET 14".

    payment_terms di customer_contracts tidak pernah divalidasi, jadi isinya
    beda-beda kapitalisasi dan formatnya. Kembalikan None kalau tidak ada angka
    yang bisa dipercaya, jangan menebak.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    days = int(match.group())
    return days if 0 <= days <= 365 else None


def get_thresholds(branch_id):
    """Ambang eskalasi cabang ini, dengan default kalau settingnya belum ada."""
    values = dict(DEFAULT_THRESHOLDS)
    if not branch_id:
        return values

    rows = BranchSetting.query.filter(
        BranchSetting.branch_id == branch_id,
        BranchSetting.setting_key.in_(tuple(DEFAULT_THRESHOLDS)),
    ).all()
    for row in rows:
        parsed = parse_terms_days(row.setting_value)
        if parsed is not None:
            values[row.setting_key] = parsed
    return values


def get_credit_account(branch_id, party_type, party_id):
    """Akun kredit pihak ini, atau None kalau owner belum pernah menyetelnya.

    None bukan kesalahan: itu berarti ditagih lewat PT, limit 0, AKTIF -- nilai
    netral yang dipakai semua fungsi di sini lewat getattr(..., default).
    """
    if not branch_id or not party_type or not party_id:
        return None
    return CreditAccount.query.filter_by(
        branch_id=branch_id, party_type=party_type, party_id=party_id
    ).first()


def get_or_create_credit_account(branch_id, party_type, party_id):
    """Akun kredit yang siap disetel owner. Baris baru selalu mulai netral.

    Tidak commit: pemanggil yang menyetel limit/termin/deposit sekalian
    menyimpannya dalam satu transaksi.
    """
    account = get_credit_account(branch_id, party_type, party_id)
    if account is None:
        account = CreditAccount(
            branch_id=branch_id,
            party_type=party_type,
            party_id=party_id,
            billing_mode=BILLING_VIA_CLIENT,
            credit_limit=ZERO,
            payment_terms_days=0,
            deposit_percent=Decimal(get_thresholds(branch_id)["credit.deposit_percent"]),
            status=STATUS_ACTIVE,
        )
        db.session.add(account)
        db.session.flush()
    return account


def resolve_billing_party(branch_id, client_id=None, mandor_id=None):
    """Siapa yang sebenarnya ditagih untuk order ini.

    Mandor hanya jadi pihak tertagih kalau akun kreditnya memang disetel DIRECT
    atau CASH. Mandor tanpa akun, atau dengan akun VIA_CLIENT, tetap ditagih
    ke PT pemilik proyek, persis seperti sebelum kontrol kredit ini ada.
    """
    if mandor_id:
        account = get_credit_account(branch_id, PARTY_MANDOR, mandor_id)
        mode = getattr(account, "billing_mode", BILLING_VIA_CLIENT)
        if mode in (BILLING_DIRECT, BILLING_CASH):
            return PARTY_MANDOR, mandor_id, account

    if client_id:
        return PARTY_CLIENT, client_id, get_credit_account(branch_id, PARTY_CLIENT, client_id)

    return None, None, None


def _invoice_query(branch_id, party_type, party_id):
    from app.services.accounting_service import CREDIT_CHARGE_INVOICE_SOURCES

    query = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.status.notin_(SETTLED_INVOICE_STATUSES),
        # Tagihan ta'zir/ta'widh tidak ikut menaikkan status kredit: telat
        # membayar ta'zir tidak boleh melahirkan ta'zir baru (denda atas denda).
        db.or_(Invoice.source_type.is_(None), Invoice.source_type.notin_(CREDIT_CHARGE_INVOICE_SOURCES)),
    )
    if party_type == PARTY_MANDOR:
        return query.filter(Invoice.mandor_id == party_id)
    # Invoice yang ditagih langsung ke sub client bukan hutang client-nya.
    return query.filter(
        Invoice.client_id == party_id,
        db.or_(Invoice.bill_to_type.is_(None), Invoice.bill_to_type.notlike("MANDOR%")),
    )


def outstanding_and_aging(branch_id, party_type, party_id, today=None):
    """Sisa tagihan pihak ini, beserta umurnya.

    Umur tunggakan ini yang selama ini tidak pernah dilihat gerbang: mandor
    yang masih di bawah limit tapi telat 90 hari selalu lolos.
    """
    today = today or date.today()
    aging = {bucket: ZERO for bucket in AGING_BUCKETS}
    total = ZERO
    oldest_days = 0

    if not branch_id or not party_type or not party_id:
        return total, oldest_days, aging

    rows = _invoice_query(branch_id, party_type, party_id).with_entities(
        Invoice.remaining_amount, Invoice.due_date
    ).all()

    for remaining_amount, due_date in rows:
        amount = _money(remaining_amount)
        if amount <= ZERO:
            continue
        total += amount

        days_overdue = (today - due_date).days if due_date else 0
        if days_overdue <= 0:
            aging["belum_jatuh_tempo"] += amount
            continue

        oldest_days = max(oldest_days, days_overdue)
        if days_overdue <= 7:
            aging["1_7"] += amount
        elif days_overdue <= 21:
            aging["8_21"] += amount
        elif days_overdue <= 60:
            aging["22_60"] += amount
        else:
            aging["60_plus"] += amount

    return total, oldest_days, aging


def _billed_coverage(branch_id, mandor_id):
    """Tanggal dan order mana saja yang sudah masuk invoice mandor ini.

    Kedua jenis invoice dari order sama-sama menandai cakupan tanggalnya:
    invoice periode mengisi period_start..period_end dengan source_order_id
    kosong, dan invoice per order mengisi period_start = period_end =
    order_date. Jadi satu aturan rentang tanggal mencakup keduanya.
    source_order_id tetap dicocokkan sebagai jaring pengaman untuk invoice
    lama yang tidak mengisi periode.
    """
    ranges = []
    order_ids = set()
    rows = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.mandor_id == mandor_id,
        Invoice.status != "CANCELLED",
    ).with_entities(
        Invoice.period_start, Invoice.period_end, Invoice.source_order_id
    ).all()
    for period_start, period_end, source_order_id in rows:
        if period_start and period_end:
            ranges.append((period_start, period_end))
        if source_order_id:
            order_ids.add(source_order_id)
    return ranges, order_ids


def unbilled_delivered(branch_id, party_type, party_id):
    """Order yang sudah jalan tapi invoicenya belum terbit.

    Ini lubang yang paling besar sebelumnya: gerbang lama cuma menjumlah
    invoice. Invoice periode terbit belakangan, jadi mandor bisa menumpuk satu
    periode penuh sebelum gerbang sadar ada apa-apa.

    Order yang dikonfirmasi dari portal masuk dengan harga 0 sampai admin
    mengisinya, jadi order itu belum menambah angka di sini. Nilai order yang
    sedang diminta dihitung terpisah lewat estimate_order_amount().
    """
    if not branch_id or not party_id:
        return ZERO
    if party_type == PARTY_CLIENT:
        # Satu order bisa menyentuh banyak mandor sekaligus; untuk client,
        # jumlahkan lewat mandor-mandor di bawahnya.
        return _unbilled_delivered_for_client(branch_id, party_id)
    if party_type != PARTY_MANDOR:
        return ZERO

    billed_ranges, billed_order_ids = _billed_coverage(branch_id, party_id)

    rows = (
        db.session.query(
            DailyOrder.id,
            DailyOrder.order_date,
            DailyOrderDetail.price_per_portion,
            DailyOrderDetail.total_qty,
            DailyOrderDetail.lunch_delivery_fee,
            DailyOrderDetail.dinner_delivery_fee,
        )
        .join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.status != CANCELLED_ORDER_STATUS,
            DailyOrderDetail.mandor_id == party_id,
        )
        .all()
    )

    total = ZERO
    for order_id, order_date, price, qty, lunch_fee, dinner_fee in rows:
        if is_billed(order_id, order_date, billed_ranges, billed_order_ids):
            continue
        # Ongkir ikut ditagihkan bersama order, jadi ikut dihitung sebagai hutang.
        total += _money(price) * Decimal(int(qty or 0)) + _money(lunch_fee) + _money(dinner_fee)
    return total


def is_billed(order_id, order_date, billed_ranges, billed_order_ids):
    """Order ini sudah masuk invoice? Murni, supaya aturannya bisa diuji."""
    if order_id in billed_order_ids:
        return True
    return any(start <= order_date <= end for start, end in billed_ranges)


def estimate_order_amount(branch_id, mandor_id, portion_qty, delivery_location_id=None):
    """Perkiraan nilai order yang sedang diminta, dari harga terakhir mandor ini.

    Order portal belum punya harga saat gerbang dinilai -- harganya baru diisi
    admin setelah konfirmasi. Harga per porsi terakhir di lokasi yang sama
    dipakai lebih dulu, lalu harga terakhir mandor itu di lokasi mana pun.
    Kembalikan 0 kalau mandor belum pernah punya order berharga.
    """
    qty = int(portion_qty or 0)
    if not branch_id or not mandor_id or qty <= 0:
        return ZERO

    base = (
        db.session.query(DailyOrderDetail.price_per_portion)
        .join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.status != CANCELLED_ORDER_STATUS,
            DailyOrderDetail.mandor_id == mandor_id,
            DailyOrderDetail.price_per_portion > 0,
        )
        .order_by(DailyOrder.order_date.desc(), DailyOrderDetail.id.desc())
    )

    price = None
    if delivery_location_id:
        price = base.filter(
            DailyOrderDetail.delivery_location_id == delivery_location_id
        ).limit(1).scalar()
    if price is None:
        price = base.limit(1).scalar()

    return _money(price) * Decimal(qty) if price is not None else ZERO


def _unbilled_delivered_for_client(branch_id, client_id):
    from app.models.master import Mandor

    mandor_ids = [
        row.id for row in Mandor.query.filter(
            Mandor.branch_id == branch_id, Mandor.client_id == client_id
        ).with_entities(Mandor.id).all()
    ]
    total = ZERO
    for mandor_id in mandor_ids:
        total += unbilled_delivered(branch_id, PARTY_MANDOR, mandor_id)
    return total


def is_promise_kept(made_on, promised_for, payment_dates):
    """Janji bayar ditepati kalau ada pembayaran di antara dibuat dan jatuhnya.

    Log penagihan tidak mencatat nominal yang dijanjikan, jadi pembayaran
    berapa pun di rentang itu dihitung menepati. Murni, supaya bisa diuji.
    """
    start = made_on or promised_for
    return any(start <= paid_on <= promised_for for paid_on in payment_dates)


def broken_promise_count(branch_id, party_type, party_id, today=None):
    """Berapa janji bayar yang lewat tanggalnya tanpa pembayaran masuk."""
    return len(broken_promises(branch_id, party_type, party_id, today))


def broken_promises(branch_id, party_type, party_id, today=None):
    """Daftar janji bayar yang meleset: [(invoice_id, tanggal janji)], terurut.

    Tiap pasangan adalah satu kejadian; dipakai juga sebagai kunci usulan
    ta'zir supaya satu janji meleset hanya diusulkan sekali.

    Sinyal paling awal dan paling akurat dari niat kabur -- jauh lebih cepat
    ketahuan daripada menunggu umur tunggakan menua.

    Sumbernya tabel payments, bukan status log penagihan: log PARTIAL/PAID
    otomatis hanya dibuat oleh satu route pembayaran, jadi pembayaran lewat
    jalur lain tidak akan terlihat kalau yang dibaca statusnya. Janji yang sama
    (invoice dan tanggal yang sama) dicatat dua kali dihitung sekali --
    kalau tidak, admin yang rajin mencatat follow up justru membuat mandor
    langsung terblokir karena "ingkar dua kali".
    """
    today = today or date.today()
    if not branch_id or not party_type or not party_id:
        return []

    invoice_ids = [
        row.id for row in _invoice_query(branch_id, party_type, party_id)
        .with_entities(Invoice.id).all()
    ]
    if not invoice_ids:
        return []

    promises = {}
    rows = InvoiceCollectionLog.query.filter(
        InvoiceCollectionLog.invoice_id.in_(invoice_ids),
        InvoiceCollectionLog.promise_date.isnot(None),
        InvoiceCollectionLog.promise_date < today,
    ).with_entities(
        InvoiceCollectionLog.invoice_id,
        InvoiceCollectionLog.follow_up_date,
        InvoiceCollectionLog.promise_date,
    ).all()
    for invoice_id, made_on, promised_for in rows:
        key = (invoice_id, promised_for)
        # Kalau janji yang sama dicatat berkali-kali, pakai catatan paling
        # awal: rentang tepat waktunya jadi paling lebar.
        if key not in promises or (made_on and made_on < promises[key]):
            promises[key] = made_on
    if not promises:
        return []

    # Pelunasan lewat potong DP/deposit juga menepati janji, bukan hanya kas/bank.
    from app.services.invoice_payment_history_service import payment_dates_by_invoice

    payment_dates = payment_dates_by_invoice(invoice_ids)

    return sorted(
        (invoice_id, promised_for)
        for (invoice_id, promised_for), made_on in promises.items()
        if not is_promise_kept(made_on, promised_for, payment_dates.get(invoice_id, ()))
    )


def derive_status(exposure, credit_limit, oldest_days_overdue, broken_promises, thresholds):
    """Status yang seharusnya, murni dari angka. Tanpa DB, tanpa efek samping.

    Dipisah supaya bisa diuji sendiri: ini aturan bisnisnya, dan aturan bisnis
    yang tidak bisa diuji cepat adalah aturan yang pelan-pelan akan salah.
    """
    if oldest_days_overdue >= thresholds["credit.write_off_days_overdue"]:
        return STATUS_WRITE_OFF, f"Tunggakan tertua {oldest_days_overdue} hari."

    if oldest_days_overdue >= thresholds["credit.blocked_days_overdue"]:
        return STATUS_BLOCKED, f"Tunggakan tertua {oldest_days_overdue} hari."
    if broken_promises >= thresholds["credit.broken_promise_blocked"]:
        return STATUS_BLOCKED, f"Janji bayar meleset {broken_promises} kali."

    if oldest_days_overdue >= thresholds["credit.hold_days_overdue"]:
        return STATUS_HOLD, f"Tunggakan tertua {oldest_days_overdue} hari."
    if credit_limit > ZERO and exposure > credit_limit:
        return STATUS_HOLD, "Exposure sudah melewati limit kredit."
    if broken_promises >= thresholds["credit.broken_promise_hold"]:
        return STATUS_HOLD, f"Janji bayar meleset {broken_promises} kali."

    if oldest_days_overdue >= thresholds["credit.watch_days_overdue"]:
        return STATUS_WATCH, f"Tunggakan tertua {oldest_days_overdue} hari."
    if credit_limit > ZERO:
        watch_at = credit_limit * Decimal(thresholds["credit.watch_exposure_pct"]) / Decimal(100)
        if exposure >= watch_at:
            return STATUS_WATCH, (
                f"Exposure sudah {thresholds['credit.watch_exposure_pct']}% dari limit."
            )

    return STATUS_ACTIVE, "Lancar."


def stricter_status(left, right):
    """Yang lebih ketat di antara dua status.

    Gerbang selalu memakai ini terhadap status tersimpan dan status hitungan
    langsung. Konsekuensinya: penyapu harian yang gagal jalan tidak bisa
    membuka lubang, dan BLOKIR yang dipasang OWNER secara manual tidak bisa
    hilang sendiri hanya karena angkanya kebetulan membaik hari ini.
    """
    order = CREDIT_STATUS_ORDER
    left_rank = order.index(left) if left in order else 0
    right_rank = order.index(right) if right in order else 0
    return order[max(left_rank, right_rank)]


@dataclass
class CreditDecision:
    allowed: bool
    requires_approval: bool
    status: str
    billing_mode: str
    party_type: str = None
    party_id: int = None
    credit_limit: Decimal = ZERO
    deposit_amount: Decimal = ZERO
    required_deposit: Decimal = ZERO
    outstanding_invoiced: Decimal = ZERO
    unbilled_delivered: Decimal = ZERO
    pending_amount: Decimal = ZERO
    exposure: Decimal = ZERO
    available: Decimal = ZERO
    oldest_days_overdue: int = 0
    broken_promises: int = 0
    aging: dict = field(default_factory=dict)
    stored_status: str = STATUS_ACTIVE
    derived_status: str = STATUS_ACTIVE
    # False kalau owner belum pernah menyetel kredit pihak ini: angkanya tetap
    # dihitung sebagai informasi, tapi tidak ada yang ditahan atau diblokir.
    enforced: bool = False
    # Order jalan, tapi ada yang harus dilihat admin (status PANTAU, atau
    # kredit berjalan tanpa deposit karena owner menyetel syaratnya 0%).
    warning: bool = False
    reason: str = ""
    message: str = ""


def is_enforced(branch_id, party_type, party_id, account):
    """Tangga eskalasi berlaku untuk pihak ini?

    Pihak yang kreditnya disetel OWNER (punya akun), dan -- sejak Fase 7 --
    client yang punya kontrak aktif: aturan kontrak (tempo dari kontrak)
    berlaku untuk semua client kontrak, bukan hanya sub client kredit.
    """
    if account is not None:
        return True
    return party_type == PARTY_CLIENT and active_contract(branch_id, party_id) is not None


def evaluate_credit(branch_id, client_id=None, mandor_id=None, pending_amount=0, today=None):
    """Keputusan kredit untuk satu order yang mau masuk.

    Dipanggil jalur portal maupun jalur internal ADMIN dengan argumen yang sama.
    """
    party_type, party_id, account = resolve_billing_party(branch_id, client_id, mandor_id)
    return evaluate_party(branch_id, party_type, party_id, account, pending_amount, today)


def evaluate_party(branch_id, party_type, party_id, account, pending_amount=0, today=None):
    """Keputusan kredit untuk satu pihak tertagih yang sudah diketahui.

    Dipakai evaluate_credit (lewat order) dan penyapu harian (lewat akun).
    """
    today = today or date.today()
    pending = _money(pending_amount)

    if not party_type:
        return CreditDecision(
            allowed=True, requires_approval=False, status=STATUS_ACTIVE,
            billing_mode=BILLING_VIA_CLIENT, pending_amount=pending,
            reason="NO_PARTY",
            message="Pihak tertagih belum bisa ditentukan; kredit tidak dinilai.",
        )

    billing_mode = getattr(account, "billing_mode", BILLING_VIA_CLIENT)
    credit_limit = _money(getattr(account, "credit_limit", 0))
    deposit = deposit_balance(branch_id, party_id) if party_type == PARTY_MANDOR else ZERO
    required_deposit = (
        credit_limit * _money(getattr(account, "deposit_percent", 0)) / Decimal(100)
        if account is not None else ZERO
    )
    stored_status = getattr(account, "status", STATUS_ACTIVE) or STATUS_ACTIVE
    thresholds = get_thresholds(branch_id)

    outstanding, oldest_days, aging = outstanding_and_aging(branch_id, party_type, party_id, today)
    unbilled = unbilled_delivered(branch_id, party_type, party_id)
    promises = broken_promise_count(branch_id, party_type, party_id, today)

    # Deposit itu uang mandor yang sudah ada di tangan perusahaan, jadi
    # mengurangi yang benar-benar berisiko hilang.
    exposure = outstanding + unbilled + pending - deposit
    if exposure < ZERO:
        exposure = ZERO
    available = credit_limit - exposure if credit_limit > ZERO else ZERO

    derived_status, derived_reason = derive_status(
        exposure, credit_limit, oldest_days, promises, thresholds
    )
    release_until = getattr(account, "release_until", None)
    if release_until and today <= release_until:
        # OWNER melepas sementara, misalnya sampai tanggal komitmen tertulis.
        # Selama itu status yang disetel OWNER berlaku walaupun angkanya
        # masih buruk; sesudahnya hitungan otomatis berlaku lagi.
        status = stored_status
        reason = (
            f"Dilepas sementara oleh OWNER sampai {release_until.strftime('%d-%m-%Y')}. "
            f"{getattr(account, 'status_reason', None) or ''}"
        ).strip()
    else:
        status = stricter_status(stored_status, derived_status)
        reason = derived_reason if status == derived_status else (
            getattr(account, "status_reason", None) or derived_reason
        )
        grace_until = getattr(account, "grace_until", None)
        if grace_until and today <= grace_until and status != STATUS_WRITE_OFF:
            # Kelonggaran (QS 2:280): utang lama ditangguhkan, status tidak naik
            # melewati TAHAN; pesanan baru tetap wajib bayar di muka (TAHAN).
            status = STATUS_HOLD
            reason = (
                f"Kelonggaran sampai {grace_until.strftime('%d-%m-%Y')}: utang lama ditangguhkan, "
                f"pesanan baru wajib bayar di muka. {getattr(account, 'grace_reason', None) or ''}"
            ).strip()

    decision = CreditDecision(
        allowed=True, requires_approval=False, status=status, billing_mode=billing_mode,
        party_type=party_type, party_id=party_id,
        credit_limit=credit_limit, deposit_amount=deposit, required_deposit=required_deposit,
        outstanding_invoiced=outstanding, unbilled_delivered=unbilled,
        pending_amount=pending, exposure=exposure, available=available,
        oldest_days_overdue=oldest_days, broken_promises=promises, aging=aging,
        stored_status=stored_status, derived_status=derived_status,
        enforced=is_enforced(branch_id, party_type, party_id, account), reason=reason,
    )

    # Tangga eskalasi hanya ditegakkan untuk pihak yang kreditnya disetel
    # owner. Untuk pihak lain angka di atas bisa menyesatkan: jatuh tempo
    # invoice lama di-hardcode 7 hari, jadi client kontrak "net 30" yang
    # membayar tepat waktu tampak telat 23 hari dan akan terblokir padahal
    # tidak melanggar apa pun.
    if not decision.enforced:
        decision.reason = "NOT_CONFIGURED"
        decision.message = (
            "Kontrol kredit belum disetel untuk pihak ini; "
            "angka di atas hanya informasi, order tidak ditahan."
        )
        return decision

    if billing_mode == BILLING_CASH:
        decision.allowed = pending <= ZERO or exposure <= ZERO
        decision.message = (
            "Pihak ini bayar di muka. Order baru hanya jalan setelah pembayaran diterima."
        )
        if not decision.allowed:
            decision.reason = "CASH_ONLY"
        return decision

    if status in (STATUS_BLOCKED, STATUS_WRITE_OFF):
        decision.allowed = False
        decision.message = (
            f"Order baru diblokir. {reason} "
            "Hanya OWNER yang bisa membuka setelah ada pembayaran masuk "
            "atau komitmen tertulis yang tercatat."
        )
        return decision

    # Deposit dulu, kredit belakangan. Selama deposit yang benar-benar
    # diterima (dari buku besar) belum mencapai syaratnya, pihak ini belum
    # boleh berhutang sama sekali.
    if billing_mode == BILLING_DIRECT and deposit < required_deposit:
        decision.allowed = False
        decision.reason = "DEPOSIT_SHORT"
        decision.message = (
            f"Deposit jaminan belum memenuhi syarat: diterima {_rupiah(deposit)} "
            f"dari {_rupiah(required_deposit)}. Kredit menyala setelah deposit diterima."
        )
        return decision

    if billing_mode == BILLING_DIRECT and credit_limit <= ZERO:
        # Ditagih langsung tanpa limit = belum ada plafon yang disetujui owner.
        decision.allowed = False
        decision.reason = "NO_LIMIT"
        decision.message = "Limit kredit pihak ini belum disetel OWNER."
        return decision

    if status == STATUS_HOLD:
        decision.requires_approval = True
        decision.message = (
            f"Order ditahan dan butuh persetujuan OWNER. {reason}"
        )
        return decision

    if status == STATUS_WATCH:
        decision.warning = True
        decision.message = (
            f"Order jalan, tapi wajib dipantau dan log penagihan harus diisi. {reason}"
        )
        return decision

    # Owner boleh menyetel syarat deposit 0%. Itu sah, tapi seluruh limit
    # jadi kerugian maksimum kalau pihak ini kabur, jadi harus kelihatan.
    if billing_mode == BILLING_DIRECT and deposit <= ZERO:
        decision.warning = True
        decision.message = (
            "Lancar, tapi pihak ini ditagih langsung tanpa deposit: "
            "seluruh limit jadi kerugian maksimum kalau kabur."
        )
        return decision

    decision.message = "Lancar."
    return decision


def deposit_balance(branch_id, mandor_id):
    """Deposit jaminan mandor yang masih ditahan, langsung dari buku besar.

    Sumbernya transaksi deposit (advance_transactions jenis
    MANDOR_SECURITY_DEPOSIT, akun 2007): sisa yang belum dipotong ke invoice
    atau dikembalikan. Tidak ada angka deposit yang diketik manual.
    """
    if not branch_id or not mandor_id:
        return ZERO
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import MANDOR_SECURITY_DEPOSIT

    total = ZERO
    for (remaining,) in AdvanceTransaction.query.filter(
        AdvanceTransaction.branch_id == branch_id,
        AdvanceTransaction.mandor_id == mandor_id,
        AdvanceTransaction.advance_type == MANDOR_SECURITY_DEPOSIT,
        AdvanceTransaction.status.in_(("OPEN", "PARTIAL")),
    ).with_entities(AdvanceTransaction.remaining_amount).all():
        total += _money(remaining)
    return total


def suggest_credit_limit(branch_id, mandor_id, terms_days, today=None, lookback_days=30):
    """Usulan limit: nilai order harian rata-rata x (termin + cadangan).

    Keputusan owner 2026-09-25: limit dihitung dari kebutuhan order, bukan dari
    deposit -- pengali deposit x2 membuat mandor 50 porsi sudah tertahan di
    hari ke-5 padahal belum telat apa pun. Rata-rata per hari kalender
    (bukan per hari order), dibulatkan ke atas ke Rp 100.000. Ini usulan;
    OWNER yang menetapkan angkanya.
    """
    from datetime import timedelta
    from decimal import ROUND_CEILING

    today = today or date.today()
    if not branch_id or not mandor_id:
        return ZERO

    rows = (
        db.session.query(DailyOrderDetail.price_per_portion, DailyOrderDetail.total_qty)
        .join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
        .filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.status != CANCELLED_ORDER_STATUS,
            DailyOrder.order_date >= today - timedelta(days=lookback_days),
            DailyOrder.order_date < today,
            DailyOrderDetail.mandor_id == mandor_id,
        )
        .all()
    )
    total = sum((_money(price) * Decimal(int(qty or 0)) for price, qty in rows), ZERO)
    if total <= ZERO:
        return ZERO

    buffer_days = get_thresholds(branch_id)["credit.limit_buffer_days"]
    days = int(terms_days or 0) + int(buffer_days)
    raw = total / Decimal(lookback_days) * Decimal(days)
    step = Decimal(100_000)
    return (raw / step).to_integral_value(rounding=ROUND_CEILING) * step


def _rupiah(value):
    return "Rp " + f"{_money(value):,.0f}".replace(",", ".")


STATUS_LABELS = {
    STATUS_ACTIVE: "Lancar",
    STATUS_WATCH: "Pantau",
    STATUS_HOLD: "Ditahan",
    STATUS_BLOCKED: "Diblokir",
    STATUS_WRITE_OFF: "Hapus Buku",
}


def credit_gate_from_decision(decision, *, approved=False):
    """Keputusan kredit dalam bentuk gerbang order.

    Bentuknya sama dengan gerbang lain di portal_order_draft_service: status
    BLOCKED menghalangi konfirmasi, needs_approval membuat permintaan
    persetujuan. Persetujuan hanya bisa melepas TAHAN. BLOKIR tidak punya
    jalan pintas lewat approval: OWNER harus menurunkan status akunnya.
    """
    gate = {
        "key": "CREDIT",
        "title": "Kredit",
        "status": "OK",
        "label": STATUS_LABELS.get(decision.status, decision.status),
        "tone": "green",
        "message": decision.message,
        "needs_approval": False,
        "approved": False,
        "amount": decision.exposure,
        "limit": decision.credit_limit,
        "credit_status": decision.status,
        "oldest_days_overdue": decision.oldest_days_overdue,
        "estimated_order_amount": decision.pending_amount,
    }

    if not decision.allowed:
        gate.update(status="BLOCKED", tone="red")
        gate["label"] = {
            "CASH_ONLY": "Wajib Bayar Dulu",
            "DEPOSIT_SHORT": "Deposit Kurang",
            "NO_LIMIT": "Limit Belum Disetel",
        }.get(decision.reason, gate["label"])
        return gate

    if decision.requires_approval:
        if approved:
            gate.update(
                status="APPROVED", tone="orange", approved=True,
                label="Disetujui OWNER",
                message=f"{decision.message} Persetujuan OWNER sudah ada untuk order ini.",
            )
        else:
            gate.update(status="APPROVAL_REQUIRED", tone="red", needs_approval=True)
        return gate

    if decision.warning:
        gate.update(status="WARNING", tone="orange")
    return gate


def check_internal_order_credit(*, branch_id, mandor_id, amount, actor_role=None):
    """Gerbang kredit jalur order internal. Kembalikan (boleh, pesan, keputusan).

    Portal memakai mesin approval per draft. Order internal belum punya id
    sebelum dibuat, dan satu approval per mandor akan membuka semua order
    mandor itu selamanya -- jadi TAHAN di sini berarti: hanya OWNER yang boleh
    menginput order untuk pihak ini, dan tindakan OWNER itu sendiri adalah
    keputusannya. Tanpa actor_role, pemanggil diperlakukan sebagai bukan OWNER.

    Kontrak client yang sudah berakhir dan belum diperpanjang juga TAHAN
    (keputusan owner 2026-09-28), dengan aturan OWNER yang sama.
    """
    from app.services.contract_lifecycle_service import lapsed_contract, lapsed_contract_message
    from app.models.master import Mandor
    from app.utils.roles import effective_role

    if not branch_id or not mandor_id:
        # Tanpa cabang atau mandor tidak ada pihak yang bisa dinilai; akun
        # kredit selalu terikat cabang, jadi tidak ada yang perlu ditegakkan.
        return True, None, None

    mandor = db.session.get(Mandor, mandor_id)
    is_owner = effective_role(actor_role) == "OWNER"
    lapsed = lapsed_contract(branch_id, getattr(mandor, "client_id", None))
    if lapsed is not None and not is_owner:
        return False, (
            f"{lapsed_contract_message(lapsed)} Hanya OWNER yang bisa menginput order "
            f"untuk {T.client_lower} ini sampai kontraknya diperpanjang."
        ), None

    ok, message, decision = _internal_credit_decision(branch_id, mandor, mandor_id, amount, is_owner)
    if ok and lapsed is not None:
        note = f"{lapsed_contract_message(lapsed)} Order diteruskan atas keputusan OWNER."
        message = f"{note} {message}" if message else note
    return ok, message, decision


def _internal_credit_decision(branch_id, mandor, mandor_id, amount, is_owner):
    decision = evaluate_credit(
        branch_id,
        client_id=getattr(mandor, "client_id", None),
        mandor_id=mandor_id,
        pending_amount=amount,
    )

    if not decision.enforced:
        return _contract_limit_check(branch_id, decision, is_owner)

    if not decision.allowed:
        return False, decision.message, decision

    if decision.requires_approval:
        if is_owner:
            return True, (
                f"Kredit pihak ini berstatus {STATUS_LABELS[decision.status]}; "
                "order diteruskan atas keputusan OWNER."
            ), decision
        return False, (
            f"{decision.message} Hanya OWNER yang bisa menginput order untuk pihak ini."
        ), decision

    if decision.warning:
        return True, decision.message, decision
    return True, None, decision


def _contract_limit_check(branch_id, decision, is_owner):
    """Rem limit kontrak untuk order yang ditagih ke client, di jalur internal.

    Keputusan owner 2026-09-25. Sebelumnya limit kontrak hanya dicek di draft
    portal; order yang diinput admin untuk client (lewat mandornya atau unit
    order langsungnya) tidak direm sama sekali. Aturannya sama dengan portal:
    lewat limit berarti keputusan OWNER. Di sini exposure-nya lengkap --
    invoice belum lunas ditambah order sudah jalan tapi belum ditagih --
    karena invoice periode terbit belakangan. Client tanpa kontrak atau
    tanpa limit tidak direm, seperti di portal.
    """
    if decision.party_type != PARTY_CLIENT:
        return True, None, decision
    contract_limit = active_contract_limit(branch_id, decision.party_id)
    if contract_limit <= ZERO or decision.exposure <= contract_limit:
        return True, None, decision

    message = (
        f"Tagihan {T.client_lower} ini {_rupiah(decision.exposure)} (termasuk order ini) "
        f"melewati limit kontrak {_rupiah(contract_limit)}."
    )
    if is_owner:
        return True, f"{message} Order diteruskan atas keputusan OWNER.", decision
    return False, f"{message} Hanya OWNER yang bisa menginput order untuk {T.client_lower} ini.", decision


def resolve_due_date(invoice_date, branch_id=None, client_id=None, mandor_id=None,
                     contract_payment_terms=None):
    """Jatuh tempo dari termin pihak tertagih, bukan dari angka tetap 7 hari.

    Urutannya: bayar di muka = hari itu juga; lalu termin akun kredit; lalu
    termin kontrak aktif client kalau angkanya bisa diurai ("net 30" = 30
    hari, keputusan owner 2026-09-25); terakhir 7 hari seperti perilaku lama,
    supaya client tanpa kontrak dan tanpa akun kredit tidak berubah.
    """
    from datetime import timedelta

    _, _, account = resolve_billing_party(branch_id, client_id, mandor_id)
    if getattr(account, "billing_mode", None) == BILLING_CASH:
        return invoice_date

    days = int(getattr(account, "payment_terms_days", 0) or 0)
    if days <= 0:
        from app.services.contract_rules_service import active_contract_for

        act_contract = active_contract_for(client_id, on_date=invoice_date, branch_id=branch_id)
        if act_contract and act_contract.due_days and act_contract.due_days >= 1:
            days = int(act_contract.due_days)
        else:
            if contract_payment_terms is None:
                contract_payment_terms = active_contract_terms(branch_id, client_id)
            parsed = parse_terms_days(contract_payment_terms)
            days = parsed if parsed else LEGACY_FALLBACK_TERMS_DAYS

    return invoice_date + timedelta(days=days)


def active_contract(branch_id, client_id):
    """Kontrak aktif client ini di cabang ini, atau None."""
    if not branch_id or not client_id:
        return None
    from app.models.contract import CustomerContract

    return (
        CustomerContract.query.filter(
            CustomerContract.branch_id == branch_id,
            CustomerContract.client_id == client_id,
            CustomerContract.status == "ACTIVE",
        )
        .order_by(CustomerContract.end_date.desc(), CustomerContract.id.desc())
        .first()
    )


def active_contract_terms(branch_id, client_id):
    """Termin (teks) kontrak aktif client ini, atau None."""
    return getattr(active_contract(branch_id, client_id), "payment_terms", None)


def active_contract_limit(branch_id, client_id):
    """Limit kredit kontrak aktif client ini; 0 kalau tidak ada kontrak/limit."""
    return _money(getattr(active_contract(branch_id, client_id), "credit_limit", 0))


def invoice_billing_terms(invoice_date, branch_id, client, mandor):
    """Tertagih dan jatuh tempo untuk invoice yang dibuat otomatis dari order.

    Dipakai invoice periode dan invoice per order supaya keduanya memakai
    aturan yang sama. Mandor yang ditagih langsung mendapat invoice atas
    namanya sendiri (bill_to_type MANDOR, nilai yang sudah dikenali laporan
    piutang dan cetak invoice); mandor lain tetap ditagih ke PT pemilik
    proyek seperti sebelumnya.
    """
    party_type, _, _ = resolve_billing_party(
        branch_id, getattr(client, "id", None), getattr(mandor, "id", None)
    )
    direct = party_type == PARTY_MANDOR
    return {
        "bill_to_type": "MANDOR" if direct else "CLIENT",
        "bill_to_name": mandor.name if direct else client.name,
        "due_date": resolve_due_date(
            invoice_date, branch_id, getattr(client, "id", None), getattr(mandor, "id", None)
        ),
    }
