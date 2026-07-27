# BATCH 1G EXTERNAL PORTAL MAPPING APPROVAL PACKAGE

ERP PT Idha Boga Pangan Mandiri

Status: APPROVAL_REQUIRED

Tanggal: 2026-07-27

## Ringkasan

Batch 1A sampai 1F sudah membuat portal internal read-only yang aman:
- feature flag `PORTAL_ENABLED`;
- namespace `/portal`;
- dashboard portal;
- directory Client/PT;
- directory Mandor;
- status shell;
- ownership analysis.

Namun portal belum boleh dibuka ke user eksternal sebelum owner menyetujui desain role, permission, dan mapping ownership.

Alasan:
- `User` existing hanya memiliki `branch_id`, `username`, `password_hash`, `role`, `is_active`.
- Belum ada field atau tabel yang mengikat user ke `Client`, `Mandor`, `ClientPic`, atau principal eksternal.
- Role resmi existing masih internal: `OWNER`, `ADMIN`, `FINANCE`, `ACCOUNTING`, `LOGISTICS`, `HR`, `DAPUR`, `PENGANTAR`.
- Decorator `role_required` memiliki OWNER bypass dan belum memiliki konsep ownership eksternal.

Kesimpulan:
Menambah akun eksternal, role eksternal, atau akses data order/invoice/payment adalah perubahan sensitif dan wajib approval sebelum coding.

## Current Behavior

### Auth dan Role

Existing:
- Login memakai `users`.
- Role divalidasi dari `ALLOWED_ROLES`.
- User management hanya menerima role internal.
- OWNER dapat bypass semua `role_required`.

Belum ada:
- `CUSTOMER`;
- `MANDOR_PORTAL`;
- `PT_PORTAL`;
- `PORTAL_DELEGATE`;
- mapping user ke Client/PT;
- mapping user ke Mandor;
- mapping user ke lokasi;
- ownership guard eksternal.

### Data Ownership Existing

Sumber data yang tersedia:

| Principal | Tabel Existing | Relasi Existing | Catatan |
| --- | --- | --- | --- |
| Client/PT | `clients` | `clients.id -> mandors.client_id` | Master bisnis, belum akun login. |
| PIC Client | `client_pics` | `client_pics.client_id -> clients.id` | Kontak bisnis, belum identitas auth. |
| Mandor | `mandors` | `mandors.branch_id`, `mandors.client_id` | Master lapangan, belum akun login. |
| Lokasi | `delivery_locations` | `delivery_locations.mandor_id -> mandors.id` | Child scope mandor. |
| User | `users` | `users.branch_id`, `users.role` | Internal user saja. |

## Problem Yang Harus Diputuskan

1. Apakah akun portal eksternal akan memakai tabel `users` existing atau tabel auth terpisah?
2. Principal eksternal apa saja yang disetujui:
   - PT/Client;
   - Mandor;
   - PIC/delegate;
   - pelanggan umum.
3. Apakah satu user boleh punya lebih dari satu principal?
4. Apakah satu principal boleh memiliki banyak user?
5. Apakah akses data cukup berdasarkan `client_id`/`mandor_id`, atau juga perlu `delivery_location_id`?
6. Apakah user eksternal boleh melihat invoice/payment pada Stage 1, atau ditunda sampai Stage 2?
7. Apakah user eksternal boleh membuat draft order pada Batch berikutnya, atau hanya melihat status?

## Opsi Desain

### Option A - Minimal Additive Mapping Table

Tambahkan tabel mapping baru, tanpa mengubah kolom `users`:

```text
portal_user_mappings
- id
- user_id
- principal_type
- client_id nullable
- mandor_id nullable
- client_pic_id nullable
- delivery_location_id nullable
- access_level
- is_active
- created_at
- created_by
- updated_at
- updated_by
```

Principal type:
- `CLIENT`
- `MANDOR`
- `CLIENT_PIC`
- `DELEGATE`

Kelebihan:
- Tidak mengubah struktur `users`.
- Bisa satu user punya lebih dari satu akses jika disetujui.
- Bisa menonaktifkan mapping tanpa menonaktifkan user.
- Lebih aman untuk audit ownership.

Risiko:
- Perlu migration baru.
- Perlu ownership guard baru.
- Perlu user management tambahan untuk mapping.
- Perlu test role/data scope yang ketat.

Status:
Recommended, tetapi tetap `APPROVAL_REQUIRED`.

### Option B - Tambah Kolom Langsung di `users`

Tambahkan kolom:

```text
users.portal_principal_type
users.client_id
users.mandor_id
users.client_pic_id
```

Kelebihan:
- Implementasi awal lebih sederhana.

Risiko:
- Kurang fleksibel jika satu user mengelola beberapa mandor/lokasi/PT.
- Mengubah tabel user inti.
- Risiko coupling auth internal dan eksternal terlalu besar.

Status:
Tidak direkomendasikan sebagai default.

### Option C - Auth Eksternal Terpisah

Buat tabel akun portal terpisah.

Kelebihan:
- Pemisahan internal dan eksternal jelas.

Risiko:
- Membuat auth paralel.
- Bertentangan dengan prinsip memakai auth existing sejauh memungkinkan.
- Kompleksitas tinggi untuk session, password, reset, audit.

Status:
Ditolak untuk tahap awal kecuali ada alasan operasional kuat.

## Rekomendasi

Gunakan Option A: mapping table additive.

Namun jangan implementasi dulu sebelum owner menyetujui:
- nama role eksternal;
- principal type;
- data yang boleh diakses;
- apakah Stage 1 hanya read-only atau sudah boleh draft order;
- apakah invoice/payment tetap ditunda.

## Proposed Role Strategy

Tambahkan role baru hanya jika disetujui:

| Role Baru | Tujuan | Mutasi Awal | Catatan |
| --- | --- | --- | --- |
| `PORTAL_CLIENT` | PT/client membaca scope miliknya | Tidak | Bisa melihat mandor/lokasi di bawah client setelah guard tersedia. |
| `PORTAL_MANDOR` | Mandor membaca scope miliknya | Tidak | Bisa melihat lokasi sendiri. |
| `PORTAL_DELEGATE` | PIC/delegasi terbatas | Tidak | Wajib dibatasi oleh mapping eksplisit. |
| `PORTAL_CUSTOMER` | Pelanggan umum | Tidak pada batch awal | Order/prepayment butuh batch dan policy terpisah. |

Alternatif konservatif:
- Jangan menambah role dahulu.
- Tetap OWNER/ADMIN internal.
- Tambahkan mapping design dan tests dulu.

## Proposed Ownership Guard

Guard baru harus terpisah dari `role_required` internal.

Konsep:

```text
portal_login_required
portal_role_required(...)
portal_scope_required(resource_type, resource_id)
```

Aturan:
- OWNER boleh preview semua untuk audit internal.
- ADMIN boleh preview branch sendiri.
- User eksternal hanya boleh melihat data yang terikat mapping aktif.
- Tidak boleh mengandalkan `branch_id` saja untuk user eksternal.
- Semua query portal eksternal wajib melalui service scope resolver.

## Data Yang Boleh Dibuka Bertahap

### Stage Awal Setelah Approval

Boleh:
- profil ringkas principal;
- daftar lokasi milik sendiri;
- status gate;
- empty-state order/invoice.

Belum boleh:
- detail invoice;
- payment;
- jurnal;
- stock;
- closing;
- data mandor/client lain;
- export dokumen.

### Setelah Ownership Test Lulus

Boleh dipertimbangkan:
- status order read-only;
- riwayat order read-only;
- draft order yang belum masuk produksi;
- upload bukti prepayment, tetapi belum membuat payment otomatis.

## Affected Components Jika Disetujui

| Area | Dampak |
| --- | --- |
| Models | Tabel mapping baru atau kolom `users`, tergantung opsi. |
| Migration | Migration additive wajib. |
| Services | `portal_access_service`, ownership guard, user mapping service. |
| Routes | Portal route untuk mapping/admin preview dan eventual external scope. |
| Templates | Form mapping internal dan dashboard eksternal. |
| Tests | Role matrix, ownership scope, unauthenticated/unauthorized/authorized, branch leakage. |
| Audit | Critical audit log untuk create/update/deactivate mapping. |
| Security | Password/reset/session policy eksternal perlu validasi. |

## Data And Financial Impact

Batch approval ini tidak mengubah data.

Jika Option A disetujui:
- tidak mengubah transaksi lama;
- tidak mengubah invoice/payment/journal/stock;
- hanya menambah tabel mapping auth-scope;
- perlu backup sebelum migration;
- perlu rollback migration.

Jika di tahap berikutnya membuka invoice/payment:
- harus ada ownership guard per invoice;
- invoice/payment visibility harus snapshot-safe;
- tidak boleh mengubah status keuangan hanya karena portal view.

## Acceptance Criteria Untuk Batch Implementasi Setelah Approval

1. Migration additive, tidak drop/rename.
2. `flask db upgrade` lulus pada database test.
3. `flask db downgrade` atau rollback plan terdokumentasi.
4. User internal tetap bisa login.
5. Role internal tetap valid.
6. External role tidak masuk route internal.
7. Mapping inactive menolak akses.
8. User eksternal Client tidak melihat Client lain.
9. User eksternal Mandor tidak melihat Mandor lain.
10. Delegate hanya melihat principal yang dimapping.
11. OWNER/ADMIN preview tetap berjalan.
12. Tidak ada route portal mutasi transaksi.
13. Tidak ada commit/rollback di route.
14. Full pytest lulus.
15. Baseline safety audit lulus.

## Rollback Plan Jika Disetujui Dan Diimplementasikan

1. Revert commit batch implementation.
2. Jalankan downgrade migration jika ada dan sudah diuji.
3. Jika downgrade tidak aman, disable via feature flag dan biarkan tabel additive tidak dipakai.
4. Jalankan:

```bash
python -m compileall app tests scripts
python -m pytest -q
python scripts/baseline_safety_audit.py
```

## Approval Required

Perubahan:
- Menambah role eksternal.
- Menambah mapping user eksternal ke Client/PT/Mandor/PIC.
- Menambah migration additive untuk mapping.
- Menambah ownership guard eksternal.

Alasan:
- Tanpa mapping eksplisit, portal eksternal berisiko membocorkan data client/mandor lain.

Modul/tabel terdampak:
- `users`;
- `clients`;
- `client_pics`;
- `mandors`;
- `delivery_locations`;
- kemungkinan tabel baru `portal_user_mappings`;
- portal routes/services/templates/tests.

Risiko:
- kebocoran data antar client;
- role internal ikut terbuka;
- user eksternal melihat invoice/payment sebelum waktunya;
- migration auth-scope tidak rollbackable jika salah desain.

Alternatif paling aman:
- Setujui hanya Option A untuk mapping additive.
- Tetap read-only.
- Jangan buka order/invoice/payment pada batch mapping awal.

Dampak jika tidak dilakukan:
- Portal tetap hanya preview internal OWNER/ADMIN.
- Tidak ada risiko bocor data eksternal, tetapi belum bisa dipakai pelanggan/mandor/PT nyata.

Rencana rollback:
- Revert commit.
- Disable `PORTAL_ENABLED`.
- Downgrade migration jika sudah dibuat dan diuji.

Test yang akan ditambahkan:
- role matrix portal;
- ownership scope per principal;
- unauthorized denial;
- no branch leakage;
- inactive mapping denied;
- route smoke portal external;
- template/url_for audit;
- no route commit/rollback.

## Keputusan Yang Diminta Dari Owner

Mohon pilih satu:

```text
APPROVE_BATCH_1H_OPTION_A_MAPPING_READ_ONLY
```

Artinya:
- boleh tambah tabel mapping additive;
- boleh tambah role portal eksternal minimal;
- tetap read-only;
- tidak membuka order/invoice/payment.

Atau:

```text
DEFER_EXTERNAL_MAPPING_KEEP_INTERNAL_PREVIEW_ONLY
```

Artinya:
- jangan tambah role/schema;
- portal tetap internal OWNER/ADMIN.

## Final Status

APPROVAL_REQUIRED

Batch 1G selesai sebagai paket approval. Tidak ada coding fitur sensitif, migration, atau perubahan role yang dijalankan.
