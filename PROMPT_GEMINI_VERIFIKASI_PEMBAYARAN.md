# TUGAS: Percepat & amankan verifikasi pembayaran pesanan portal

Kamu bekerja di repo Flask ERP **PT Idha Boga Pangan Mandiri** (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL 11, Windows + PowerShell, virtualenv di `venv\`).
Baca SELURUH prompt ini sebelum menulis kode. Kerjakan **per fase, berurutan**. Di akhir setiap fase jalankan test yang disebut, lalu tulis laporan singkat (file yang diubah + hasil test). Jangan lompat fase.

---

## 0. LATAR BELAKANG (kondisi sekarang)

Saat pelanggan portal membayar pesanan (draft), admin harus melakukan 3 langkah di 2 halaman:

1. `/finance/portal-payment-proofs` (route `finance.portal_payment_proofs`, file `app/routes/finance/payment_routes.py`, template `app/templates/finance/portal_payment_proofs.html`) → klik **Verifikasi** (`decide_portal_payment_proof` → `decide_payment_proof()` di `app/services/portal_payment_verification_queue_service.py`).
2. Halaman yang sama, tab Diverifikasi → isi form **Catat uang muka** (`record_prepayment_from_portal_proof` → `create_prepayment_from_verified_draft_proof()` di `app/services/portal_payment_creation_service.py` → `record_draft_prepayment()` di `app/services/prepaid_order_service.py`).
3. `/portal/admin/order-drafts` (`portal.admin_order_drafts`, template `app/templates/portal/admin_order_drafts.html`) → cari draft yang sama → **Konfirmasi** (`confirm_portal_order_draft()` di `app/services/portal_order_draft_service.py`).

Masalah: lambat, dan rawan ketukar karena bukti ditampilkan sebagai "Lampiran #ID" + "User ID 12", foto harus dibuka di tab lain, nominal diketik ulang tanpa pembanding, dan bukti yang sama bisa diunggah dua kali.

Fakta kode yang WAJIB kamu pakai (sudah dicek, jangan diubah perilakunya kecuali disebut):

- Bukti bayar = baris `DigitalAttachment` (`app/models/system.py`) dengan `module="PORTAL_PAYMENT"`, `reference_type="PORTAL_ORDER_DRAFT"` (draft) atau `"INVOICE"` (invoice), `reference_id` = id draft/invoice. Status bukti disimpan di `attachment_type`: `PAYMENT_PROOF_PENDING` → `PAYMENT_PROOF_VERIFIED` / `PAYMENT_PROOF_REJECTED` → `PAYMENT_PROOF_PAYMENT_CREATED`. Kolom `sha256_hash` (64 char) SUDAH ada dan terisi otomatis oleh `stage_digital_attachment()`.
- Upload bukti draft oleh pelanggan: route `portal.upload_draft_payment_proof` (`app/routes/portal_routes.py`, ±baris 1025) → `upload_portal_order_draft_payment_proof()` di `app/services/portal_payment_proof_service.py`. Nominal dari pelanggan sekarang hanya ditulis ke `notes` sebagai teks. Form-nya ada di `app/templates/portal/draft_order.html` (blok `{% if pay_rows %}`, ±baris 74–101). `pay_rows` dibangun di `portal_order_draft_service.py` ±baris 886 (`amount_due`, `paid_amount`, `total_amount`).
- `draft_total_amount(draft)` = `price_per_portion × portion_qty + delivery_fee` (Decimal, atau `None` untuk draft lama tanpa harga).
- `draft_prepaid_amount(draft)` = uang muka yang sudah tercatat. Sisa = `total - prepaid`.
- `record_draft_prepayment(...)` TIDAK commit, menolak nominal > sisa, membuat `AdvanceTransaction` (akun 2008 Uang Muka Pelanggan) + `CashBankTransaction` + jurnal otomatis.
- `confirm_portal_order_draft(draft_id, admin_user, review_note=None, owner_override=False)` mengunci draft (`with_for_update`), mengevaluasi gate (`evaluate_portal_order_draft_gate`), membuat/menggabung `DailyOrderDetail`, lalu memanggil `_commit_or_rollback()` (COMMIT SENDIRI) di 2 tempat. Gate `PAYMENT` baru lolos kalau prepaid ≥ total.
- `decide_payment_proof(..., commit=False)` sudah mendukung mode tanpa commit dan mengirim notifikasi ke pelanggan.
- `atomic_business_action(...)` (`app/services/atomic_transaction_service.py`) adalah context manager transaksi; bisa bersarang (hanya yang paling luar yang commit/rollback/audit). `boundary.track_attachment(att)` menghapus file kalau transaksi gagal.
- `reserve_idempotency_key()` / `mark_idempotency_completed(..., commit=False)` di `app/services/idempotency_service.py` hanya flush.
- `create_cash_bank_adjustment(..., commit=False)` di `app/services/cash_bank_service.py` membuat `CashBankAdjustment` + `CashBankTransaction` + jurnal (Dr kas/bank, Cr akun lawan dari `ADJUSTMENT_CATEGORIES`). Akun `4004` = Pendapatan Lain-Lain.
- Role: `role_required("OWNER", "ADMIN", "FINANCE")` (FINANCE otomatis dipetakan ke ADMIN).
- Waktu: pakai `today_wib()` / `now_wib()` dari `app/utils/clock.py` (zona WIB), filter Jinja `|wib`, `|rupiah`, `|status_label`.
- Sidebar: `app/templates/layouts/sidebar.html` ±baris 175–177 (link "Pesanan Portal" & "Bukti Bayar Masuk").
- Alembic head saat ini: `d1e2f3a4b5c6`.

---

## 1. KEPUTUSAN OWNER (FINAL, jangan diubah)

1. **Satu halaman, satu klik.** Verifikasi bukti + catat uang muka + konfirmasi pesanan digabung menjadi satu tombol **"Terima & Konfirmasi"** dalam SATU transaksi database (gagal satu → batal semua).
2. **Kurang bayar = DITAHAN.** Uang yang benar-benar masuk tetap dicatat sebagai uang muka, tetapi pesanan TIDAK dikonfirmasi; pelanggan diberi notifikasi sisa yang harus dibayar.
3. **Lebih bayar** (di luar kode unik) = DIBLOK. Admin harus menolak bukti atau menghubungi pelanggan; sistem tidak boleh mencatat otomatis.
4. **Kode unik transfer dipakai**: 3 digit (1–999) ditambahkan ke nominal transfer pesanan prabayar. Selisih kode unik dicatat otomatis sebagai Pendapatan Lain-Lain (4004).
5. **Yang boleh menyetujui**: OWNER dan ADMIN (termasuk role lama FINANCE).
6. Semua keputusan tercatat di audit log dan pelanggan menerima notifikasi.

---

## 2. ATURAN WAJIB (pelanggaran = tugas gagal)

1. **Jangan** menghapus/mengganti route lama `decide_portal_payment_proof`, `record_prepayment_from_portal_proof`, `create_payment_from_portal_proof`, `confirm_order_draft`, `reject_order_draft`. Test lama memakainya. Kamu hanya MENAMBAH.
2. **Tidak ada `db.session.commit()` / `db.session.rollback()` di file route.** Semua commit lewat `atomic_business_action` di service. Test `tests/test_db_commit_audit_tool.py` mengecek ini (termasuk "Service call ke fungsi ber-commit = 0"): setiap service yang memanggil fungsi publik ber-commit HARUS mengirim `commit=False` secara eksplisit.
3. **Tidak ada `except Exception: pass`** atau except luas yang diam. Tangkap error spesifik; kalau terpaksa except luas, `logger.exception(...)` lalu raise ulang / ubah ke error domain. Test `tests/test_exception_hygiene.py` mengecek ini.
4. Semua uang pakai `Decimal`, dibulatkan 2 desimal (`decimal_money` dari `business_logic_guard_service` atau `_money` yang sudah ada). **Jangan pakai float untuk perhitungan.** Float hanya boleh untuk tampilan.
5. Semua query dibatasi `branch_id` user yang login.
6. Jangan menyentuh: folder `storage/`, `instance/`, `.env`, `app.zip`, `tools/reset_staging_demo.py`, `RINCIAN_AUDIT_COMMIT_TRANSACTION_ERP_IDHA_BOGA.md`, tabel `ml_*` / `research_dataset_*` (sistem prediksi ML — JANGAN diganggu), dan jangan DROP/TRUNCATE tabel apa pun.
7. **Jangan `git add -A`, jangan commit, jangan push.** Owner yang memutuskan commit.
8. Jangan menjalankan atau mematikan server dev milik user.
9. Pertahankan encoding & line ending file yang kamu edit (banyak file memakai CRLF). Jangan reformat seluruh file; ubah hanya bagian yang perlu.
10. Semua teks UI dalam **Bahasa Indonesia** yang sederhana (pengguna bukan orang IT).
11. CSS ditulis di `app/static/css/app/*.css` (sumber), lalu WAJIB jalankan `venv\Scripts\python.exe tools\build_css.py` untuk membangun `style.css` (ada test yang membandingkan). Jangan edit `style.css` langsung.
12. Ikuti gaya UI yang ada: kelas `app-btn-primary`, `app-btn-secondary`, `status-badge`, `form-control`, `form-select`; aksi tombol berjajar horizontal; tanpa garis bawah saat hover; kartu bergaya dashboard. Tidak ada dark mode.
13. Kalau ada fakta di prompt ini yang ternyata tidak cocok dengan kode, BERHENTI dan laporkan — jangan menebak.

---

## FASE 1 — Database (migrasi)

### 1a. Model baru `PortalPaymentProofClaim` di `app/models/system.py`
Tabel `portal_payment_proof_claims` — data yang diisi pelanggan saat unggah bukti:

| kolom | tipe | catatan |
|---|---|---|
| id | Integer PK | |
| attachment_id | Integer FK `digital_attachments.id` | NOT NULL, UNIQUE, index |
| branch_id | Integer FK `branches.id` | NOT NULL, index |
| claimed_amount | Numeric(18,2) | NOT NULL — nominal yang ditransfer menurut pelanggan |
| sender_name | String(120) | NOT NULL — nama pemilik rekening pengirim |
| transfer_reference | String(80) | NULL, index — no. referensi dari aplikasi bank (opsional) |
| created_at | DateTime | default `datetime.utcnow` |

Tambahkan relationship `attachment = db.relationship("DigitalAttachment", lazy="joined")`. Ekspor model di `app/models/__init__.py` seperti model lain.

### 1b. Kolom baru di `PortalOrderDraft`
`payment_unique_code = db.Column(db.Integer, nullable=True)` — kode unik 1–999. `NULL` = draft lama / tidak prabayar (dianggap 0).

### 1c. File migrasi
`migrations/versions/a7b8c9d0e1f2_payment_proof_claims_unique_code.py`, `revision = "a7b8c9d0e1f2"`, `down_revision = "d1e2f3a4b5c6"`. `upgrade()` membuat tabel + kolom; `downgrade()` menghapusnya. Ikuti gaya file migrasi lain di folder itu. Tidak ada backfill data.

### Verifikasi Fase 1 (PowerShell)
```powershell
$env:DATABASE_URL = "postgresql+psycopg://idha_boga_user:<password dari .env>@localhost:5432/test_db"
venv\Scripts\python.exe -m flask db upgrade
venv\Scripts\python.exe -m flask db downgrade d1e2f3a4b5c6
venv\Scripts\python.exe -m flask db upgrade
Remove-Item Env:DATABASE_URL
```
Ketiganya harus sukses. Ambil password dari `.env` tapi JANGAN menulis password ke file mana pun.

---

## FASE 2 — Kode unik transfer

### 2a. Pembuatan kode
Di `create_portal_order_draft()` (`portal_order_draft_service.py`), setelah `db.session.flush()` dan sebelum notifikasi:
- Jika `draft_requires_prepayment(draft)` bernilai True (import dari `prepaid_order_service` di dalam fungsi untuk hindari import melingkar), isi `draft.payment_unique_code` dengan fungsi baru `_pick_unique_code(branch_id)`.
- `_pick_unique_code`: ambil semua `payment_unique_code` dari draft status `PENDING_ADMIN_CONFIRMATION` di cabang yang sama; pilih angka acak 1–999 (`secrets.randbelow(999) + 1`) yang belum dipakai; coba maksimal 50 kali; kalau tetap bentrok, pakai angka terkecil yang belum dipakai; kalau 1–999 penuh semua, `None`.

### 2b. Helper perhitungan (taruh di `prepaid_order_service.py`)
```python
def draft_unique_code_amount(draft) -> Decimal:
    """Kode unik hanya berlaku untuk transfer PERTAMA (belum ada uang muka)."""
    code = int(getattr(draft, "payment_unique_code", None) or 0)
    if code <= 0 or draft_prepaid_amount(draft) > ZERO:
        return ZERO
    return Decimal(code).quantize(Decimal("0.01"))

def draft_transfer_amount(draft) -> Decimal | None:
    """Nominal yang harus ditransfer pelanggan = sisa + kode unik."""
    total = draft_total_amount(draft)  # import di dalam fungsi
    if total is None:
        return None
    outstanding = max(total - draft_prepaid_amount(draft), ZERO)
    if outstanding <= ZERO:
        return ZERO
    return outstanding + draft_unique_code_amount(draft)
```

### 2c. Tampilan pelanggan (`draft_order.html` blok `pay_rows`)
- Tambahkan `transfer_amount` dan `unique_code` ke dict `pay_rows` (±baris 886).
- Tampilkan besar: **"Transfer TEPAT Rp150.237"**, dengan 3 digit terakhir diberi warna/tebal, dan teks kecil: "3 angka terakhir adalah kode unik pesanan Anda agar pembayaran cepat dicocokkan. Mohon jangan dibulatkan."
- Prefill input `paid_amount` dengan `transfer_amount` (bukan `amount_due`).
- Kalau `unique_code` kosong, tampilan sama seperti sekarang (sisa bayar).

### 2d. Kategori penyesuaian sistem
Di `cash_bank_service.py`:
- Tambahkan ke `ADJUSTMENT_CATEGORIES`: `"KODE_UNIK": {"label": "Kode unik transfer pelanggan", "INCREASE": "4004", "bank_only": False, "system_only": True}`.
- Tambahkan parameter `allow_system_category=False` ke `create_cash_bank_adjustment` (dan `create_cash_bank_adjustment_record` kalau meneruskan argumen). Jika kategori punya `system_only` dan `allow_system_category` False → raise `Exception("Jenis penyesuaian ini hanya dibuat otomatis oleh sistem.")`.
- Di `app/routes/finance/cash_bank_routes.py` ±baris 582–588, kirim ke template hanya kategori yang TIDAK `system_only`, supaya KODE_UNIK tidak muncul di form manual.

### Test Fase 2 — buat `tests/test_payment_unique_code.py`
- Draft pelanggan umum baru mendapat kode 1–999; draft mandor/PT (tidak prabayar) kode `None`.
- Dua draft pending di cabang sama tidak pernah berkode sama (buat 30 draft, cek unik).
- `draft_transfer_amount` = total + kode saat belum ada uang muka; = sisa (tanpa kode) setelah ada uang muka parsial.
- Kategori KODE_UNIK ditolak dari jalur manual dan tidak muncul di halaman penyesuaian kas/bank.

Gunakan pola fixture & pembuat data dari `tests/test_prepaid_orders.py` dan `tests/test_portal_payment_creation_service.py` (jangan buat fixture database baru dari nol).

---

## FASE 3 — Upload bukti oleh pelanggan (data klaim + anti dobel)

### 3a. Form (`draft_order.html` blok `pay_rows`)
Tambah field:
- `sender_name` — label "Nama pemilik rekening pengirim", WAJIB.
- `transfer_reference` — label "No. referensi transfer (opsional)", maxlength 80.
Field `paid_amount` tetap WAJIB.

### 3b. Route `upload_draft_payment_proof` (`portal_routes.py`)
Baca `paid_amount`, `sender_name`, `transfer_reference` dari form dan teruskan ke service sebagai argumen keyword baru. Tetap pertahankan penulisan teks "Nominal dibayar pelanggan: Rp ..." di notes (kompatibilitas).

### 3c. Service `upload_portal_order_draft_payment_proof` (`portal_payment_proof_service.py`)
Tambah parameter keyword opsional `claimed_amount=None, sender_name=None, transfer_reference=None` (opsional agar test lama tetap jalan). Di dalam blok transaksi yang sama, SETELAH attachment di-flush:
1. **Satu bukti aktif per draft**: kalau draft ini sudah punya attachment draft-proof `PAYMENT_PROOF_PENDING` atau `PAYMENT_PROOF_VERIFIED` yang belum dihapus → raise `PortalPaymentProofError("Bukti sebelumnya masih diperiksa admin. Tunggu hasilnya dulu.")`.
2. **Duplikat file**: kalau ada attachment lain `module="PORTAL_PAYMENT"`, cabang sama, `is_deleted=False`, `sha256_hash` sama, dan `attachment_type != PAYMENT_PROOF_REJECTED` → raise `PortalPaymentProofError("File bukti ini sudah pernah diunggah sebelumnya. Unggah bukti transfer yang benar.")`.
3. **Duplikat no. referensi**: kalau `transfer_reference` diisi (di-strip & di-uppercase) dan sudah ada di `PortalPaymentProofClaim` cabang sama yang attachment-nya bukan REJECTED → raise error serupa ("No. referensi ini sudah dipakai untuk bukti lain.").
4. Jika `claimed_amount` diberikan: validasi > 0 (Decimal), `sender_name` wajib tidak kosong (maks 120), lalu buat `PortalPaymentProofClaim`.

Karena error di-raise di dalam `atomic_business_action` dengan `boundary.track_attachment(...)`, file yang sudah tersimpan otomatis dibersihkan. Pastikan itu benar (cek di test: file tidak tertinggal di folder upload).

### Test Fase 3 — tambahkan ke `tests/test_portal_payment_proof_service.py`
- Upload dengan klaim → baris `PortalPaymentProofClaim` tersimpan dengan nilai yang benar.
- Upload file identik kedua kali (draft lain) → ditolak, tidak ada attachment baru, file tidak tertinggal.
- Upload saat bukti sebelumnya masih PENDING → ditolak.
- Setelah bukti sebelumnya REJECTED → upload baru diterima.
- Referensi transfer dobel → ditolak.
- Test lama di file itu tetap lulus tanpa diubah.

---

## FASE 4 — Service gabungan "Terima & Konfirmasi"

### 4a. Ubah `confirm_portal_order_draft`
Tambah parameter `commit=True`. Ganti kedua panggilan `_commit_or_rollback()` di fungsi ini menjadi:
```python
if commit:
    _commit_or_rollback()
else:
    db.session.flush()
```
Perilaku default (commit=True) TIDAK boleh berubah.

### 4b. File baru `app/services/portal_payment_approval_service.py`

```python
class PaymentApprovalError(ValueError):
    pass
```

**Fungsi 1 — `build_draft_payment_review(attachment) -> dict`** (read-only, tidak menulis DB). Kembalikan:
- `attachment_id`, `draft_id`, `status_key`, `uploaded_at`, `is_image` (mime diawali `image/`), `view_url` (`url_for("finance.view_portal_payment_proof_attachment", attachment_id=...)`).
- Pelanggan: `customer_name` (User uploader `full_name`), `client_name`, `mandor_name`, `phone` (dari model terkait yang punya kolom `phone`; cek `app/models/master.py`, tampilkan "-" kalau kosong), `location_name`.
- Pesanan: `order_date`, `meal_label`, `portion_qty`, `draft_status`, `is_today` (order_date == `today_wib()`).
- Uang (Decimal): `total`, `prepaid`, `outstanding`, `unique_code`, `expected_transfer` (= `draft_transfer_amount`), `claimed_amount`, `sender_name`, `transfer_reference` (dari claim; untuk bukti lama tanpa claim → None).
- `match` salah satu: `"EXACT"` (klaim == expected_transfer atau klaim == outstanding), `"SHORT"` (klaim < outstanding), `"OVER"` (klaim > expected_transfer), `"UNKNOWN"` (tidak ada klaim / total None). Plus `match_label` Indonesia: "Cocok", "Kurang Rp X", "Lebih Rp X", "Nominal tidak diisi pelanggan".
- `warnings` (list string Indonesia), isi bila:
  - ada attachment lain (cabang sama, bukan REJECTED, bukan dirinya) dengan `sha256_hash` sama → "File sama persis dengan bukti draft #N."
  - `transfer_reference` dipakai claim lain (bukan REJECTED) → "No. referensi sama dengan bukti draft #N."
  - draft status bukan `PENDING_ADMIN_CONFIRMATION` → "Pesanan sudah tidak menunggu (status: ...)."
  - `order_date` < hari ini (WIB) → "Tanggal pesanan sudah lewat."
- `blockers`: hasil `evaluate_portal_order_draft_gate(draft, request_approval=False)` — ambil pesan gate berstatus BLOCKED **kecuali gate `PAYMENT`** (pembayaran memang sedang diproses di sini).
- `can_approve` = draft PENDING, tidak ada warning duplikat, `blockers` kosong.

**Fungsi 2 — `approve_draft_payment(user, *, attachment_id, draft_id, received_amount, payment_method, bank_account_id, payment_date, reference_number, checked_mutation, note, idempotency_key) -> dict`**

Urutan WAJIB, semuanya di dalam SATU `with atomic_business_action(module="FINANCE", action="PORTAL_DRAFT_PAYMENT_APPROVED", reference_type="PORTAL_ORDER_DRAFT", reference_id=draft_id, user_id=user.id, branch_id=user.branch_id, severity="HIGH", metadata={...}):`

1. Validasi input dasar (raise `PaymentApprovalError` dengan pesan Indonesia):
   - `checked_mutation` harus True → "Centang dulu bahwa Anda sudah mengecek mutasi rekening."
   - `idempotency_key` wajib.
   - `received_amount` → Decimal > 0.
   - `payment_date` tidak boleh di masa depan (bandingkan dengan `today_wib()`).
   - Metode TRANSFER/QRIS → `bank_account_id` WAJIB dan harus `BankAccount` aktif di cabang user.
2. Kunci draft: `PortalOrderDraft.query.filter_by(id=draft_id, branch_id=user.branch_id).with_for_update().first()`. Tidak ada → error.
3. Ambil attachment: `id=attachment_id`, cabang sama, `module="PORTAL_PAYMENT"`, `reference_type="PORTAL_ORDER_DRAFT"`, `is_deleted=False`. **Wajib `attachment.reference_id == draft.id`**, kalau tidak → "Bukti ini bukan milik pesanan tersebut. Muat ulang halaman." (ini pengaman anti-ketukar).
4. Status attachment harus PENDING atau VERIFIED. Kalau `PAYMENT_PROOF_PAYMENT_CREATED` → "Bukti ini sudah diproses." Kalau REJECTED → "Bukti ini sudah ditolak."
5. Draft harus `PENDING_ADMIN_CONFIRMATION`.
6. Cek duplikat ulang (hash & referensi seperti Fase 4b). Ada → error, jangan lanjut.
7. Kalau `reference_number` diisi: tolak bila sudah dipakai `AdvanceTransaction.reference_number` atau `Payment.reference_number` di cabang yang sama (bandingkan setelah strip + upper).
8. `reserve_idempotency_key(scope="PORTAL_DRAFT_PAYMENT_APPROVE", key=..., branch_id=..., user_id=..., request_payload={...})`. Kalau tidak `reserved` → "Pembayaran ini sedang atau sudah diproses." `IdempotencyConflictError` → ubah ke `PaymentApprovalError`.
9. Hitung (semua Decimal):
   ```
   total       = draft_total_amount(draft)            # None → error "Pesanan belum punya harga terkunci."
   outstanding = total - draft_prepaid_amount(draft)  # <= 0 → error "Pesanan ini sudah lunas."
   code_amount = draft_unique_code_amount(draft)
   if received <= outstanding:
       prepay, extra = received, 0
   elif received - outstanding <= code_amount:
       prepay, extra = outstanding, received - outstanding
   else:
       raise PaymentApprovalError("Nominal lebih besar dari tagihan + kode unik. Tolak bukti atau hubungi pelanggan.")
   ```
   Kalau `received != draft_transfer_amount(draft)` dan `received != outstanding` → `note` WAJIB diisi (min 5 karakter) → "Nominal berbeda dari tagihan. Tulis catatan alasannya."
10. Jika attachment masih PENDING → `decide_payment_proof(user, attachment_id=..., decision="VERIFIED", notes="Diterima lewat Antrean Pembayaran.", commit=False)`.
11. `advance = record_draft_prepayment(draft=draft, amount=prepay, payment_method=payment_method, created_by=user.id, payment_date=payment_date, bank_account_id=bank_account_id, reference_number=..., notes=...)`. Bungkus `PrepaymentError` → `PaymentApprovalError`.
12. Jika `extra > 0`: `create_cash_bank_adjustment(adjustment_date=payment_date, account_type="BANK" bila ada bank_account_id else "CASH", bank_account_id=bank_account_id, adjustment_type="INCREASE", amount=extra, reason=f"Kode unik transfer pesanan portal #{draft.id} ({advance.advance_number})", created_by=user.id, branch_id=draft.branch_id, category="KODE_UNIK", allow_system_category=True, commit=False)`. Bungkus error-nya → `PaymentApprovalError`.
13. Ubah attachment: `attachment_type = "PAYMENT_PROOF_PAYMENT_CREATED"`, tambahkan baris catatan "PAYMENT_CREATED <advance_number> by user_id=<id>" (pakai pola `_append_payment_created_note` yang sudah ada).
14. Jika sekarang `draft_prepaid_amount(draft) >= total`:
    - `_, converted, error = confirm_portal_order_draft(draft.id, user, review_note=note or "Pembayaran diterima & dikonfirmasi.", commit=False)`.
    - Kalau `error` → raise `PaymentApprovalError(error)` (SEMUA batal, termasuk uang muka).
    - `outcome = "CONFIRMED"`.
    Jika belum lunas:
    - `outcome = "HELD_SHORT"`; buat notifikasi ke pelanggan (`create_or_update_notification(..., target_user_id=attachment.uploaded_by, priority="WARNING", title="Pembayaran kurang", message=f"Pembayaran Rp... sudah diterima. Sisa yang harus dibayar Rp.... Unggah bukti transfer sisa di halaman Pesan.", action_url="/portal/orders/status", generated_key=f"portal-draft-short-{attachment.id}", commit=False)`).
15. `mark_idempotency_completed(record, reference_type="ADVANCE_TRANSACTION", reference_id=advance.id, response_payload=..., commit=False)` dan `record_audit_log(..., event_type="PORTAL_DRAFT_PAYMENT_APPROVED", commit=False)` berisi: draft_id, attachment_id, received, prepay, extra, outcome, sender_name, reference_number.
16. Return `{"outcome", "draft_id", "advance_number", "prepay", "extra", "remaining"}`.

**Fungsi 3 — `reject_draft_payment(user, *, attachment_id, draft_id, reason_code, note)`**
- `reason_code` ∈ `{"NOT_RECEIVED": "Dana tidak masuk ke rekening", "UNREADABLE": "Bukti tidak jelas/terbaca", "WRONG_ORDER": "Bukti untuk pesanan lain", "WRONG_AMOUNT": "Nominal tidak sesuai", "OTHER": "Lainnya"}`. `OTHER` → `note` wajib.
- Cek kepemilikan attachment ↔ draft sama seperti langkah 3.
- `decide_payment_proof(user, ..., decision="REJECTED", notes=f"{label}. {note}", commit=False)` di dalam `atomic_business_action`. Draft TIDAK ditolak — pelanggan bisa unggah ulang.

### Test Fase 4 — buat `tests/test_portal_payment_approval_service.py`
Wajib ada (dan lulus):
1. Bayar pas (tanpa kode) → outcome CONFIRMED, 1 AdvanceTransaction = total, draft CONFIRMED, `converted_daily_order_id` terisi, attachment `PAYMENT_PROOF_PAYMENT_CREATED`, jurnal seimbang (total debit = total kredit).
2. Bayar total + kode unik → advance = total, `CashBankAdjustment` kategori KODE_UNIK = kode, jurnal Dr bank / Cr 4004 = kode, saldo bank naik sebesar total + kode.
3. Bayar kurang → outcome HELD_SHORT, advance = nominal diterima, draft tetap PENDING, notifikasi "Pembayaran kurang" terkirim.
4. Bayar lebih dari total + kode → error, TIDAK ada advance/adjustment/jurnal baru (cek jumlah baris sebelum & sesudah).
5. `draft_id` tidak cocok dengan attachment → error, tidak ada perubahan.
6. `checked_mutation=False` → error.
7. Nominal berbeda tanpa catatan → error.
8. Idempotency key sama dikirim dua kali → kedua kalinya error, hanya 1 advance.
9. Gate lain BLOCKED (mis. kontrak berakhir) → error, SEMUA batal (tidak ada advance, attachment tetap status awal).
10. Referensi bank sudah dipakai → error.
11. Tolak dengan alasan → attachment REJECTED, draft tetap PENDING, pelanggan dapat notifikasi.
12. `confirm_portal_order_draft` default (commit=True) tetap lulus test lama.

---

## FASE 5 — Halaman "Antrean Pembayaran Masuk"

### 5a. Route (di `app/routes/finance/payment_routes.py`, blueprint `finance_bp`)
- `GET /finance/payment-inbox` → `payment_inbox()`, `@role_required("OWNER", "ADMIN", "FINANCE")`. Query param `tab` ∈ `waiting` (default), `invoice`, `history`.
  - `waiting`: attachment draft-proof status PENDING/VERIFIED, cabang user, urut `order_date` naik lalu `created_at` naik. Bangun tiap baris dengan `build_draft_payment_review`. Batasi 100. Hindari N+1: load draft, user, lokasi, client, mandor, claim secara batch (`selectinload` / satu query `IN`), jangan query per baris di loop.
  - `invoice`: tampilkan ulang konten lama untuk bukti invoice (pakai `list_payment_proof_verification_queue` + form lama). Jangan ubah logika invoice.
  - `history`: bukti draft yang `PAYMENT_CREATED` / `REJECTED` 30 hari terakhir, maks 100, read-only.
  - Kirim juga: daftar `BankAccount` aktif cabang, `today_wib()`, `uuid4().hex` per baris sebagai idempotency key.
- `POST /finance/payment-inbox/<int:attachment_id>/approve` → baca form (`draft_id`, `received_amount`, `payment_method`, `bank_account_id`, `payment_date` format `%Y-%m-%d`, `reference_number`, `checked_mutation == "1"`, `note`, `idempotency_key`), panggil `approve_draft_payment`. Flash:
  - CONFIRMED → success "Pembayaran {nama} diterima. Pesanan {tanggal} {sesi} {porsi} porsi masuk ke Operasional."
  - HELD_SHORT → warning "Pembayaran dicatat, tapi masih kurang Rp X. Pesanan ditahan sampai lunas."
  - `PaymentApprovalError` → danger berisi pesannya.
  - Redirect kembali ke `payment_inbox` tab `waiting`, dengan anchor `#proof-<attachment_id berikutnya>` kalau ada (agar admin langsung lanjut ke berikutnya).
- `POST /finance/payment-inbox/<int:attachment_id>/reject` → `reject_draft_payment`.
- Tidak ada commit/rollback di route (lihat Aturan 2).

### 5b. Template baru `app/templates/finance/payment_inbox.html`
Extends layout yang dipakai `finance/portal_payment_proofs.html`. Isi:
- Header: judul "Pembayaran Masuk", subjudul "Cocokkan bukti dengan mutasi rekening, lalu terima atau tolak.", 3 angka ringkas: menunggu, total nominal menunggu, sudah diproses hari ini.
- Tab: Menunggu (badge jumlah) · Tagihan Invoice · Riwayat. Filter cepat (chip): Semua · Hari ini · Cocok · Perlu dicek (bukan EXACT atau ada warning).
- Satu **kartu per bukti** (`id="proof-{{ row.attachment_id }}"`), layout 2 kolom (1 kolom di HP):
  - **Kiri**: pratinjau bukti `<img src="{{ row.view_url }}" loading="lazy">` (max-height 340px, object-fit contain, klik → buka tab baru ukuran penuh). PDF → ikon + tombol "Buka PDF".
  - **Kanan**:
    - Nama pelanggan besar + no. HP (link `tel:`) + lokasi.
    - Pesanan: tanggal (badge "HARI INI" bila `is_today`), sesi, porsi.
    - Tabel uang: Total pesanan · Sudah dibayar · Sisa · Kode unik · **Harus ditransfer** · **Diklaim pelanggan** (+ nama pengirim, no. referensi).
    - Badge cocok: hijau "Cocok" / kuning "Kurang Rp X" / merah "Lebih Rp X" / abu "Nominal tidak diisi".
    - Kotak peringatan merah untuk setiap `warnings`, kuning untuk `blockers`.
    - **Form Terima** (horizontal, ringkas): Nominal masuk di rekening (prefill `claimed_amount`, kalau None prefill `expected_transfer`), Rekening penerima (select wajib; auto-pilih bila hanya 1 rekening), Metode (Transfer default / QRIS / Tunai), Tanggal terima (default hari ini WIB), No. referensi bank (prefill dari claim), Catatan (muncul sebagai wajib bila nominal ≠ tagihan — validasi utama tetap di server), checkbox WAJIB "Saya sudah cek mutasi rekening dan dana ini benar-benar masuk", hidden `draft_id` & `idempotency_key`.
    - Tombol utama: "Terima & Konfirmasi" bila nominal yang diisi ≥ sisa; berubah jadi "Catat & Tahan (kurang Rp X)" bila kurang (update via JS saat nominal diketik). Tombol disabled bila `can_approve` False, dengan alasannya tertulis di bawahnya.
    - Konfirmasi sebelum kirim memakai atribut `data-app-confirm` yang sudah ada, teks: "Terima Rp{nominal} dari {nama} untuk pesanan {tanggal} {sesi} {porsi} porsi?"
    - **Form Tolak** (dilipat di balik tombol "Tolak"): select alasan + catatan.
- Kosong: ilustrasi ikon + "Tidak ada pembayaran yang menunggu."

### 5c. JS & CSS
- JS di `app/static/js/controls.js`: fungsi `setupPaymentInbox()` (dipanggil saat DOM siap, hanya jika ada `[data-payment-inbox]`): filter chip, label tombol dinamis, tandai catatan wajib bila nominal ≠ tagihan, cegah double-submit (disable tombol setelah submit). Ikuti pola fungsi setup lain di file itu (`setupFilterGroup`, `setupTabs`).
- CSS di `app/static/css/app/pages.css` dengan prefix kelas `pin-` (payment inbox). Lalu jalankan `venv\Scripts\python.exe tools\build_css.py`.

### 5d. Navigasi
- Sidebar: link "Bukti Bayar Masuk" → ganti teks menjadi "Pembayaran Masuk" dan arahkan ke `finance.payment_inbox` (badge jumlah tetap). Pastikan state aktif juga menyala untuk endpoint `finance.payment_inbox`.
- `finance/portal_payment_proofs.html`: tambahkan banner di atas "Halaman baru yang lebih cepat: Pembayaran Masuk →" (halaman lama tetap ada).
- `portal/admin_order_drafts.html`: untuk draft yang punya bukti PENDING/VERIFIED, tampilkan badge "Ada bukti bayar" + link "Proses di Pembayaran Masuk" ke `url_for('finance.payment_inbox') ~ '#proof-' ~ attachment_id`.
- Notifikasi upload bukti di `portal_payment_proof_service.py` (`_notify_finance_draft_payment_proof_uploaded`): ubah `action_url` menjadi `/finance/payment-inbox`.

### Test Fase 5 — buat `tests/test_payment_inbox_routes.py`
- GET sebagai ADMIN & OWNER → 200, memuat nama pelanggan dan nominal "Harus ditransfer"; sebagai role portal → ditolak (403/redirect).
- Halaman tidak mengandung teks "User ID".
- POST approve sukses → redirect + flash; draft CONFIRMED.
- POST approve dengan `draft_id` salah → flash error, tidak ada perubahan.
- Jumlah query GET tab waiting dengan 10 bukti ≤ 40 (pasang listener `before_cursor_execute` seperti test performa lain) — mencegah N+1.

---

## FASE 6 — Verifikasi akhir

Jalankan berurutan (PowerShell, dari root repo):
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_payment_unique_code.py tests/test_portal_payment_approval_service.py tests/test_payment_inbox_routes.py -q
venv\Scripts\python.exe -m pytest tests/test_portal_payment_proof_service.py tests/test_portal_payment_creation_service.py tests/test_portal_payment_verification_queue_service.py tests/test_finance_portal_payment_proof_routes.py tests/test_prepaid_orders.py tests/test_contract_lifecycle.py tests/test_shortage_billing.py tests/test_portal_foundation.py -q
venv\Scripts\python.exe -m pytest tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Kalau ada test lama yang gagal, perbaiki KODEMU — jangan ubah/hapus test lama kecuali test itu memeriksa teks UI yang memang sengaja diganti (sebutkan di laporan).

Lalu periksa `tools/seed_demo_data.py` dan `tools/pilot_dry_run.py`: kalau memanggil fungsi yang signature-nya kamu ubah, sesuaikan agar tetap jalan (argumen baru semuanya opsional, jadi seharusnya tidak perlu).

Terakhir, beri tahu owner perintah ini untuk dijalankan sendiri di database dev (jangan kamu jalankan):
```powershell
venv\Scripts\python.exe -m flask db upgrade
```

---

## LAPORAN AKHIR (format wajib)
1. Daftar file baru & file yang diubah (path lengkap).
2. Hasil setiap perintah test (jumlah passed/failed).
3. Hal yang tidak sesuai prompt / asumsi yang kamu ambil.
4. Langkah uji manual singkat untuk owner: login portal pelanggan → pesan → lihat "Transfer TEPAT Rp…" → unggah bukti → login admin → menu "Pembayaran Masuk" → Terima & Konfirmasi → cek pesanan muncul di Operasional.
