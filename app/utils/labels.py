"""Label Bahasa Indonesia untuk kode status yang tampil di layar.

Kode di database tetap bahasa Inggris (LOCKED, PAID, ...) karena dipakai logika
dan laporan; yang diterjemahkan hanya tampilannya, lewat filter template
`status_label` (keputusan owner 2026-09-29: semua label berbahasa Indonesia).

    {{ order.status|status_label }}
    {{ invoice.status|status_label('invoice') }}

Kode yang tidak dikenal ditampilkan apa adanya dengan huruf kapital awal,
jadi status baru tidak pernah hilang dari layar.
"""

STATUS_LABELS = {
    # umum
    "DRAFT": "Konsep",
    "ACTIVE": "Aktif",
    "INACTIVE": "Nonaktif",
    "OPEN": "Terbuka",
    "CLOSED": "Ditutup",
    "LOCKED": "Terkunci",
    "UNLOCKED": "Belum Dikunci",
    "PENDING": "Menunggu",
    "SUBMITTED": "Diajukan",
    "APPROVED": "Disetujui",
    "REJECTED": "Ditolak",
    "CONFIRMED": "Dikonfirmasi",
    "CANCELLED": "Dibatalkan",
    "CANCELED": "Dibatalkan",
    "VOID": "Dibatalkan",
    "VOIDED": "Dibatalkan",
    "COMPLETED": "Selesai",
    "DONE": "Selesai",
    "IN_PROGRESS": "Sedang Berjalan",
    "PROGRESS": "Sedang Berjalan",
    "FAILED": "Gagal",
    "SUCCESS": "Berhasil",
    "PASS": "Lolos",
    "FAIL": "Gagal",
    "WARN": "Perlu Dicek",
    "WARNING": "Perlu Dicek",
    "UNKNOWN": "Belum Diketahui",
    "EXPIRED": "Kedaluwarsa",
    "TERMINATED": "Dihentikan",
    "SUPERSEDED": "Diganti",
    "RETIRED": "Tidak Dipakai",
    "SOLD": "Terjual",
    # uang
    "PAID": "Lunas",
    "UNPAID": "Belum Dibayar",
    "PARTIAL": "Dibayar Sebagian",
    "PARTIAL_PAID": "Dibayar Sebagian",
    "OVERDUE": "Lewat Jatuh Tempo",
    "POSTED": "Sudah Dijurnal",
    "UNPOSTED": "Belum Dijurnal",
    "VERIFIED": "Terverifikasi",
    "UNVERIFIED": "Belum Diverifikasi",
    "SETTLED": "Selesai",
    "REFUNDED": "Dikembalikan",
    # operasional
    "LUNCH": "Siang",
    "DINNER": "Sore",
    "PRODUCTION": "Produksi",
    "PRODUCTION_DONE": "Produksi Selesai",
    "DELIVERY": "Pengiriman",
    "DELIVERED": "Terkirim",
    "RECEIVED": "Diterima",
    "ON_THE_WAY": "Dalam Perjalanan",
    "READY": "Siap",
    "FULFILLED": "Dipenuhi",
    "WAITING_ADMIN": "Menunggu Admin",
    "PENDING_ADMIN_CONFIRMATION": "Menunggu Admin",
    # kategori komplain
    "FOOD_SHORTAGE": "Makanan Kurang",
    "DAMAGED_FOOD": "Makanan Rusak",
    "WRONG_MENU": "Menu Salah",
    "LATE_DELIVERY": "Pengiriman Terlambat",
    "PORTION_SHORTAGE": "Porsi Kurang",
    "OTHER": "Lainnya",
    # pergerakan stok
    "IN": "Masuk",
    "OUT": "Keluar",
    "DAMAGED": "Rusak",
    "ADJUSTMENT_IN": "Koreksi Tambah",
    "ADJUSTMENT_OUT": "Koreksi Kurang",
    "PREPARING": "Disiapkan",
    "ON_TIME": "Tepat Waktu",
    "LATE": "Terlambat",
    "SHORTAGE": "Kurang Kirim",
    "INVOICED": "Sudah Ditagih",
    "PARTIALLY_PAID": "Dibayar Sebagian",
    # penagihan, bukti, notifikasi, komplain
    "SENT": "Terkirim",
    "PROMISED": "Dijanjikan",
    "ATTACHED": "Terlampir",
    "MISSING": "Belum Ada",
    "READ": "Dibaca",
    "UNREAD": "Belum Dibaca",
    "DISMISSED": "Ditutup",
    "NEW": "Baru",
    "IN_REVIEW": "Diperiksa",
    "RESOLVED": "Selesai",
    "ESCALATED": "Dieskalasi",
    "BALANCE": "Seimbang",
    "BALANCED": "Seimbang",
    "UNBALANCED": "Tidak Seimbang",
    # gerbang dan pemeriksaan
    "OK": "Aman",
    "BLOCKED": "Tertahan",
    "NOT_REQUIRED": "Tidak Perlu",
    "APPROVAL_REQUIRED": "Perlu Persetujuan",
    "OVERRIDE": "Diloloskan",
    "WAITING_FINANCE": "Menunggu Keuangan",
    # risiko
    "CRITICAL": "Kritis",
    "HIGH": "Tinggi",
    "MEDIUM": "Sedang",
    "LOW": "Rendah",
    "INFO": "Info",
    "CHANGED": "Berubah",
    "UNCHANGED": "Tidak Berubah",
}

# Konteks yang maknanya berbeda dari umum.
CONTEXT_LABELS = {
    # Invoice DRAFT = sudah terbit tapi belum ada pembayaran.
    "invoice": {"DRAFT": "Belum Dibayar", "OPEN": "Belum Dibayar"},
    "supplier_bill": {"OPEN": "Belum Dibayar"},
}


def role_label(role):
    """Nama peran untuk tampilan (OWNER -> Owner, PORTAL_CLIENT -> Portal PT, ...)."""
    from app.services.user_management_service import ROLE_LABELS

    if not role:
        return "-"
    return ROLE_LABELS.get(str(role), str(role).replace("_", " ").title())


def status_label(value, context=None):
    if value is None or value == "":
        return "-"
    key = str(value).strip().upper()
    if context and key in CONTEXT_LABELS.get(context, {}):
        return CONTEXT_LABELS[context][key]
    if key in STATUS_LABELS:
        return STATUS_LABELS[key]
    return str(value).replace("_", " ").strip().title()
