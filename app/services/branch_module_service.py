"""Modul per cabang yang bisa dinyalakan/dimatikan OWNER: Warung dan Hutang Pekerja.

Keputusan owner 2026-09-27: sistem dipakai juga untuk katering di luar proyek
(sekolah, kantor, rumah sakit, event). Warung masih berguna di sana (kantin),
tapi pekerja yang ngutang di warung lalu ditagihkan ke sub client-nya khas
proyek. Tiap cabang memilih sendiri di Pengaturan Perusahaan -> Modul.

- Pengaturan yang tidak ada = MATI, jadi cabang baru mulai tanpa fitur
  proyek. Migrasi b3c4d5e6f7a8 menyalakan keduanya untuk cabang yang sudah
  ada, supaya tidak ada yang berubah bagi mereka.
- Hutang Pekerja hanya bisa nyala kalau Warung nyala.
- Modul tidak bisa dimatikan selama masih ada uang terbuka yang hanya
  terlihat di modul itu. Data tidak pernah dihapus; menyalakan lagi
  mengembalikan semuanya.
"""
from sqlalchemy import and_, exists

from app.extensions import db
from app.models.canteen import CanteenExternalReceivable, CashDaily, WorkerDebt
from app.models.finance import Invoice, InvoiceItem, ManualBillingBatch, ManualBillingBatchItem
from app.utils import terms as _terms
from app.utils.terms import L, T

WARUNG = "warung"
WORKER_DEBT = "worker_debt"
ON = "1"

MODULES = {
    WARUNG: {
        "key": "module_warung",
        "label": "Warung",
        "requires": None,
    },
    WORKER_DEBT: {
        "key": "module_worker_debt",
        "label": L("Hutang {worker}"),
        "requires": WARUNG,
    },
}
MODULE_SETTING_KEYS = [spec["key"] for spec in MODULES.values()]

# Sumber tagihan yang sama dengan period_invoice_routes dan manual_billing_service.
WORKER_DEBT_SOURCE = "WORKER_DEBT"
CANCELLED_INVOICE_STATUS = "CANCELLED"


class ModuleChangeError(ValueError):
    def __init__(self, errors):
        super().__init__(" ".join(errors))
        self.errors = list(errors)


def _is_on(settings, name):
    return str(settings.get(MODULES[name]["key"]) or "").strip() == ON


def _effective(settings, name):
    requires = MODULES[name]["requires"]
    return _is_on(settings, name) and (requires is None or _effective(settings, requires))


def module_enabled(name, branch_id=None):
    """Apakah modul aktif di cabang ini (default: cabang pengguna yang login)."""
    if branch_id is None:
        branch_id = _terms._current_branch_id()
    if not branch_id:
        return False
    # Cache pengaturan yang sama dengan istilah: simpan pengaturan langsung berlaku.
    return _effective(_terms._branch_settings(branch_id), name)


def module_label(name):
    return str(MODULES[name]["label"])


def module_off_message(name):
    return (
        f"Modul {module_label(name)} tidak aktif di cabang ini. "
        "OWNER bisa menyalakannya di Pengaturan Perusahaan → Modul."
    )


def unbilled_open_worker_debt_query(branch_id):
    """Hutang pekerja yang belum lunas DAN belum masuk invoice yang aktif.

    Hutang yang sudah ditagihkan tetap berstatus UNPAID: tagihannya pindah
    ke invoice sub client, dan invoice tetap terlihat di Finance walau modul
    ini mati. Yang tidak boleh hilang dari pandangan adalah yang belum
    ditagihkan ke siapa pun.
    """
    on_period_invoice = exists().where(
        and_(
            InvoiceItem.source_type == WORKER_DEBT_SOURCE,
            InvoiceItem.source_id == WorkerDebt.id,
            Invoice.id == InvoiceItem.invoice_id,
            Invoice.status != CANCELLED_INVOICE_STATUS,
        )
    )
    on_manual_billing_invoice = exists().where(
        and_(
            ManualBillingBatchItem.source_type == WORKER_DEBT_SOURCE,
            ManualBillingBatchItem.source_id == WorkerDebt.id,
            ManualBillingBatch.id == ManualBillingBatchItem.batch_id,
            Invoice.id == ManualBillingBatch.invoice_id,
            Invoice.status != CANCELLED_INVOICE_STATUS,
        )
    )
    return WorkerDebt.query.filter(
        WorkerDebt.branch_id == branch_id,
        WorkerDebt.status != "PAID",
        ~on_period_invoice,
        ~on_manual_billing_invoice,
    )


def module_blockers(name, branch_id):
    """Alasan modul ini belum boleh dimatikan. Kosong = boleh."""
    reasons = []
    if name == WORKER_DEBT:
        count = unbilled_open_worker_debt_query(branch_id).count()
        if count:
            reasons.append(
                f"Masih ada {count} hutang {T.worker_lower} yang belum lunas dan belum masuk invoice. "
                f"Tagihkan lewat invoice {T.sub_client_lower} atau lunasi dulu."
            )
    elif name == WARUNG:
        receivables = CanteenExternalReceivable.query.filter(
            CanteenExternalReceivable.branch_id == branch_id,
            CanteenExternalReceivable.status != "PAID",
            CanteenExternalReceivable.remaining_amount > 0,
        ).count()
        if receivables:
            reasons.append(
                f"Masih ada {receivables} piutang warung pembeli luar yang belum lunas. Lunasi dulu."
            )
        open_cash = CashDaily.query.filter(
            CashDaily.branch_id == branch_id,
            CashDaily.status == "OPEN",
        ).count()
        if open_cash:
            reasons.append(f"Masih ada {open_cash} kas harian warung berstatus OPEN. Tutup dulu.")
    return reasons


def build_module_status(branch_id):
    """Status tiap modul untuk halaman pengaturan: nyala/mati dan penghalang mematikan."""
    from app.services.company_settings_service import get_company_settings

    settings = get_company_settings(branch_id)
    return {
        name: {
            "enabled": _effective(settings, name),
            "blockers": module_blockers(name, branch_id) if _is_on(settings, name) else [],
        }
        for name in MODULES
    }


def module_change_errors(branch_id, values):
    """Periksa perubahan modul dari form. Kembalikan daftar alasan penolakan.

    Dibaca langsung dari database (bukan cache), karena ini keputusan simpan.
    Checkbox yang tidak dicentang tidak terkirim, jadi kunci yang hilang = mati.
    """
    from app.services.company_settings_service import get_company_settings

    current = get_company_settings(branch_id)
    wanted = {name: _is_on(values, name) for name in MODULES}
    errors = []
    if wanted[WORKER_DEBT] and not wanted[WARUNG]:
        errors.append(f"{module_label(WORKER_DEBT)} hanya bisa nyala kalau Warung juga nyala.")
    for name in MODULES:
        if _is_on(current, name) and not wanted[name]:
            errors.extend(module_blockers(name, branch_id))
    return errors


def module_changes(branch_id, values):
    """{key: [lama, baru]} untuk modul yang berubah -- dipakai audit log."""
    from app.services.company_settings_service import get_company_settings

    current = get_company_settings(branch_id)
    changes = {}
    for name, spec in MODULES.items():
        before, after = _is_on(current, name), _is_on(values, name)
        if before != after:
            changes[spec["key"]] = ["ON" if before else "OFF", "ON" if after else "OFF"]
    return changes


def enable_modules_for_branch(branch_id, names):
    """Nyalakan modul untuk satu cabang tanpa commit (pemanggil yang commit)."""
    from app.models.master import BranchSetting
    from app.services.ttl_cache_service import clear_cache

    for name in names:
        key = MODULES[name]["key"]
        row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).first()
        if row:
            row.setting_value = ON
        else:
            db.session.add(BranchSetting(branch_id=branch_id, setting_key=key, setting_value=ON))
    clear_cache("company_settings")
