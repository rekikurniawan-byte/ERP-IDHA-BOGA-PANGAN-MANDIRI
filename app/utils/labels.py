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
    # metode bayar dan saluran
    "CASH": "Tunai",
    "TRANSFER": "Transfer",
    "BANK": "Bank",
    "QRIS": "QRIS",
    "DEBT": "Hutang",
    "CREDIT": "Kredit",
    "WHATSAPP": "WhatsApp",
    "PHONE": "Telepon",
    "MANUAL": "Manual",
    # pihak dan dokumen transaksi lapangan
    "PEMBELI_UMUM": "Pembeli Umum",
    "PEKERJA_LAPANGAN": "Pekerja Lapangan",
    "MANDOR_NON_PT": "Mandor Non-PT",
    "VENDOR_NONFORMAL": "Vendor Nonformal",
    "BUYER_EKSTERNAL": "Pembeli Eksternal",
    "LAINNYA": "Lainnya",
    "SUPPORTING_DOC": "Dokumen Pendukung",
    "RECEIPT": "Kuitansi",
    "EVIDENCE": "Bukti",
    # jenis akun COA
    "ASSET": "Aset",
    "CONTRA_ASSET": "Kontra Aset",
    "LIABILITY": "Kewajiban",
    "EQUITY": "Modal",
    "REVENUE": "Pendapatan",
    "EXPENSE": "Beban",
    # sumber jurnal / buku kas-bank
    "PAYMENT": "Pembayaran",
    "INVOICE": "Invoice",
    "PROCUREMENT": "Pembelian",
    "SUPPLIER_PAYMENT": "Bayar Supplier",
    "PAYROLL": "Gaji",
    "PAYROLL_PAYMENT": "Bayar Gaji",
    "OPERATIONAL_EXPENSE": "Biaya Operasional",
    "TRANSPORT_VEHICLE_EXPENSE": "Biaya Kendaraan",
    "OWNER_CAPITAL": "Modal/Prive Pemilik",
    "CASH_BANK_ADJUSTMENT": "Penyesuaian Kas/Bank",
    "CASH_BANK_TRANSFER": "Pindah Kas/Bank",
    "ADVANCE_TRANSACTION": "Uang Muka",
    "ADVANCE_SETTLEMENT": "Penyelesaian Uang Muka",
    "FIXED_ASSET_PURCHASE": "Beli Aset Tetap",
    "FIXED_ASSET_DEPRECIATION": "Penyusutan Aset",
    "ASSET_FINANCING_CONTRACT": "Kontrak Cicilan Aset",
    "ASSET_INSTALLMENT_PAYMENT": "Bayar Cicilan Aset",
    "STOCK_MOVEMENT": "Pergerakan Stok",
    "SALDO_AWAL": "Saldo Awal",
    "OPENING_BALANCE": "Saldo Awal",
    "POTONG_DP": "Potong Uang Muka/DP",
    "POTONG_DEPOSIT": "Potong Deposit Jaminan",
    "TAZIR": "Tagihan Ta'zir (Dana Sosial)",
    "TAWIDH": "Tagihan Ta'widh (Biaya Penagihan)",
    "SOCIAL_FUND_DISBURSEMENT": "Penyaluran Dana Sosial",
    "CANTEEN_SALE": "Penjualan Warung",
    "CANTEEN_WORKER_DEBT_PAYMENT": "Bayar Hutang Warung",
    "WARUNG_DIRECT_SALE": "Penjualan Warung",
    "WARUNG_DEBT_ACCRUAL": "Hutang Warung",
    "WARUNG_DEBT_PAYMENT": "Bayar Hutang Warung",
    "PEMBELIAN_BARANG": "Pembelian Barang",
    "PEMAKAIAN_PRODUKSI": "Pemakaian Produksi",
    "MANUAL_RECEIVABLE_PAYMENT": "Bayar Piutang Manual",
    "MANUAL_PAYABLE_PAYMENT": "Bayar Hutang Manual",
    "VENDOR_PAYABLE_PAYMENT": "Bayar Hutang Vendor",
    "MANDOR_ADVANCE_SETTLEMENT": "Penyelesaian Kasbon Mandor",
    "RECEIVABLE_PAYMENT": "Bayar Piutang",
    "PAYABLE_PAYMENT": "Bayar Hutang",
    # invoice dan sumber tagihan
    "CATERING": "Katering",
    "ONGKIR": "Ongkos Kirim",
    "WARUNG": "Warung",
    "WARUNG_DEBT": "Hutang Warung",
    "REVISION_INCREASE": "Tambahan Revisi",
    "DAILY_ORDER": "Order Harian",
    "DAILY_ORDER_DETAIL": "Detail Order",
    "ORDER_DETAIL": "Detail Order",
    "ORDER_REVISION": "Revisi Order",
    "PERIOD_INVOICE": "Tagihan Periode",
    "WORKER_DEBT": "Hutang Pekerja",
    "DELIVERY_FEE_LUNCH": "Ongkir Siang",
    "DELIVERY_FEE_DINNER": "Ongkir Sore",
    "REALTIME": "Langsung",
    "MANUAL_BACKFILL": "Input Manual",
    "CLIENT": "PT",
    "MANDOR": "Mandor",
    "DELEGATE": "Delegasi",
    "KONTRAK": "Kontrak",
    "UMUM": "Umum",
    "STANDAR": "Standar",
    "STANDARD": "Standar",
    "DRAFT_ORDER": "Buat Draf Order",
    "CLIENT_DP_RECEIVED": "DP dari PT",
    "CLIENT_INVOICE": "Potong Invoice PT",
    "AFTER_LOCK_NEW_DETAIL": "Tambah Setelah Dikunci",
    "AFTER_LOCK_PRICE_REVISION": "Revisi Harga Setelah Dikunci",
    # penagihan
    "FOLLOW_UP": "Ditindaklanjuti",
    "STATEMENT_SENT": "Rekap Terkirim",
    "PIC_CLIENT": "PIC PT",
    "CLIENT_PHONE_FALLBACK": "Telepon PT",
    "NO_PHONE": "Tanpa Nomor",
    "SYSTEM": "Sistem",
    # kas/bank
    "INCREASE": "Penambahan",
    "DECREASE": "Pengurangan",
    "BIAYA_BANK": "Biaya Bank",
    "BUNGA_BANK": "Bunga Bank",
    "SELISIH": "Selisih",
    "LABA": "Laba",
    "RUGI": "Rugi",
    "IMPAS": "Impas",
    "AMAN": "Aman",
    "RISIKO": "Risiko",
    # biaya
    "ELECTRICITY": "Listrik",
    "WATER": "Air",
    "VEHICLE_FUEL": "BBM Kendaraan",
    # aset
    "KITCHEN_EQUIPMENT": "Peralatan Dapur",
    "VEHICLE": "Kendaraan",
    "OFFICE_EQUIPMENT": "Peralatan Kantor",
    "BUILDING": "Bangunan",
    "STRAIGHT_LINE": "Garis Lurus",
    "CONFIGURED": "Sudah Diatur",
    "MONTHLY": "Bulanan",
    # barang, menu, HPP
    "RAW_MATERIAL": "Bahan Baku",
    "MERCHANDISE": "Barang Dagang",
    "PACKAGING": "Kemasan",
    "GAS": "Gas",
    "FOOD": "Bahan Makanan",
    "OVERHEAD": "Overhead",
    "BOX": "Box",
    "SNACK": "Snack",
    "CUSTOM": "Khusus",
    "COMPLETE": "Lengkap",
    "PORTION_RATIO": "Rasio Porsi",
    # warung
    "GENERAL_BUYER": "Pembeli Umum",
    "REGISTERED_WORKER": "Pekerja Terdaftar",
    # lampiran dan notifikasi
    "FILE": "Berkas",
    "PAYMENT_PROOF": "Bukti Bayar",
    "CONTRACT_DOCUMENT": "Dokumen Kontrak",
    "COMPLAINT_EVIDENCE": "Bukti Komplain",
    "COMPLAINT_RESOLUTION_EVIDENCE": "Bukti Penyelesaian",
    "DELIVERY_PROOF": "Bukti Terima",
    "CUSTOMER_CONTRACT_EXPIRY": "Kontrak Akan Habis",
    "PORTAL_CUSTOMER_COMPLAINT": "Komplain Pelanggan",
    "PORTAL_DRAFT_PAYMENT_PROOF": "Bukti Bayar Draf",
    "PORTAL_ORDER_DECISION": "Keputusan Order Portal",
    "PORTAL_ORDER_DRAFT": "Draf Order Portal",
    "PORTAL_PAYMENT_PROOF_DECISION": "Keputusan Bukti Bayar",
    "PORTAL_PAYMENT": "Pembayaran Portal",
    # log audit
    "CREATE": "Buat",
    "UPDATE": "Ubah",
    "DELETE": "Hapus",
    "POST": "Jurnal",
    "STATUS_CHANGE": "Ubah Status",
    "ATTACHMENT_LINKED": "Lampiran Ditautkan",
    "ATTACHMENT_VERIFIED": "Lampiran Diverifikasi",
    "DRAFT_UPDATED": "Draf Diubah",
    "SYSTEM_AUTO_POSTED": "Dijurnal Otomatis",
    # pemeriksaan transaksi lapangan
    "RECORDED": "Tercatat",
    "WAITING_EVIDENCE": "Menunggu Bukti",
    "WAITING_CLASSIFICATION": "Menunggu Klasifikasi",
    "WAITING_APPROVAL": "Menunggu Persetujuan",
    "READY_TO_POST": "Siap Dijurnal",
    "RECONCILED": "Sudah Rekonsiliasi",
    "NOT_POSTED": "Belum Dijurnal",
    "UNSPECIFIED": "Belum Ditentukan",
    "NONE": "Tidak Ada",
    "FULFILLED_PARTIAL": "Dipenuhi Sebagian",
}

# Konteks yang maknanya berbeda dari umum.
CONTEXT_LABELS = {
    # Invoice DRAFT = sudah terbit tapi belum ada pembayaran.
    "invoice": {"DRAFT": "Belum Dibayar", "OPEN": "Belum Dibayar"},
    "supplier_bill": {"OPEN": "Belum Dibayar"},
    # Uang muka/kasbon: PARTIAL = sebagian sudah dipertanggungjawabkan.
    "advance": {"PARTIAL": "Sebagian Diselesaikan", "SETTLED": "Selesai"},
    # Jenis akun kas/bank (bukan metode bayar).
    "account": {"CASH": "Kas", "BANK": "Bank"},
}


def role_label(role):
    """Nama peran untuk tampilan (OWNER -> Owner, PORTAL_CLIENT -> Portal PT, ...)."""
    from app.services.user_management_service import ROLE_LABELS

    if not role:
        return "-"
    return ROLE_LABELS.get(str(role), str(role).replace("_", " ").title())


def event_label(value):
    """Nama jenis transaksi lapangan (FIELD_EVENT_POLICIES), lalu label umum."""
    from app.services.field_transaction_policy_service import FIELD_EVENT_POLICIES

    policy = FIELD_EVENT_POLICIES.get(str(value or "").strip().upper())
    return str(policy["label"]) if policy and policy.get("label") else status_label(value)


def status_label(value, context=None):
    if value is None or value == "":
        return "-"
    key = str(value).strip().upper()
    if context and key in CONTEXT_LABELS.get(context, {}):
        return CONTEXT_LABELS[context][key]
    if key in STATUS_LABELS:
        return STATUS_LABELS[key]
    return str(value).replace("_", " ").strip().title()
