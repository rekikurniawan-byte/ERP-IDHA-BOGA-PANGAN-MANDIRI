# Handoff Integrasi ML ↔ ERP Idha Boga

Dokumen ini adalah "kontrak integrasi" antara sistem ERP (Flask, repo ini) dan
sistem ML (project terpisah). Tujuannya: ML bisa membaca data catering LIVE dari
ERP TANPA mengganggu ERP, dan ERP tidak perlu tahu soal tabel-tabel ML.

> PENTING: Semua perintah SQL di bawah dijalankan DARI SISI ML (oleh ML engineer),
> BUKAN dari repo ERP. ERP = nol sentuhan pada struktur tabelnya.
> Database yang dipakai bersama: `idha_boga_staging`.

---

## 1. Prinsip Isolasi (kenapa ini aman)

- ERP (Flask) hanya menampilkan tabel yang punya MODEL SQLAlchemy. Tabel apa pun
  yang tidak punya model (mis. `ml_*`, `research_*`) TIDAK akan pernah muncul di web ERP.
- ML membaca data ERP lewat 1 VIEW read-only bernama `daily_catering`.
- VIEW tidak bisa menulis/mengubah data ERP. Aman total.

```
Database idha_boga_staging
├── [ERP: punya model & route]           → tampil di web ERP
│   ├── daily_orders
│   ├── daily_order_details
│   ├── mandors
│   └── ... (94 tabel ERP)
│
├── daily_catering (VIEW)                → read-only, sumber tunggal untuk ML
│                                          (UNION: historis ML + live ERP)
│
└── [ML: ERP TIDAK kenal]                → TIDAK tampil di web ERP
    ├── ml_catering_historical           → dataset historis (5.243 baris)
    ├── ml_mandor                        → mapping kode_mandor ↔ id mandor ERP
    ├── ml_predictions
    ├── ml_recipe_bom
    └── research_* (internal ML)
```

---

## 2. Skema Sumber Catering di ERP (untuk bagian LIVE view)

ERP menyimpan catering di 2 tabel. CATATAN PENTING: ERP TIDAK punya kolom
`waktu_makan`. Siang & sore disimpan sebagai 2 kolom pada 1 baris, jadi harus di-UNPIVOT.

Tabel `daily_orders`:
| kolom        | tipe    | keterangan                          |
|--------------|---------|-------------------------------------|
| id           | int PK  |                                     |
| order_date   | DATE    | tanggal pengiriman (no UTC shift)   |
| is_locked    | bool    | TRUE = final/aktual (dipakai ML)    |
| branch_id    | int     |                                     |

Tabel `daily_order_details`:
| kolom             | tipe   | keterangan                          |
|-------------------|--------|-------------------------------------|
| daily_order_id    | int FK | → daily_orders.id                   |
| mandor_id         | int FK | → mandors.id (integer, BUKAN M001)  |
| lunch_qty         | int    | jumlah bungkus SIANG                 |
| dinner_qty        | int    | jumlah bungkus SORE                  |
| price_per_portion | float  | harga per bungkus                    |

Pemetaan ke format ML (`daily_catering`):
| kolom ML          | sumber ERP                                             |
|-------------------|--------------------------------------------------------|
| kode_mandor       | dari `ml_mandor` (JOIN by erp_mandor_id) — lihat §3     |
| tanggal           | `daily_orders.order_date`                              |
| waktu_makan       | 'siang' (dari lunch_qty) / 'sore' (dari dinner_qty)    |
| jumlah_bungkus    | `lunch_qty` / `dinner_qty`                              |
| harga_per_bungkus | `daily_order_details.price_per_portion`                |
| sumber_data       | literal 'DETAIL_HARIAN_ASLI' (hanya order is_locked)   |

---

## 3. Tabel mapping `ml_mandor` (solusi kode_mandor)

ERP tidak punya "M001". Supaya prediksi tidak ketuker antar mandor, kode mandor
ditentukan eksplisit di sisi ML dan dipetakan ke id mandor ERP.

```sql
CREATE TABLE IF NOT EXISTS ml_mandor (
    id            SERIAL PRIMARY KEY,
    kode_mandor   VARCHAR(10) UNIQUE NOT NULL,   -- M001 dst (sama dgn dataset historis)
    nama_mandor   VARCHAR(150),
    erp_mandor_id INTEGER,                         -- = mandors.id di ERP
    is_active     BOOLEAN DEFAULT TRUE
);
```

Alur: saat mandor baru diinput di ERP (dapat id, mis. 5), catat di `ml_mandor`:
`kode_mandor='M001', erp_mandor_id=5, nama_mandor='...'`.

---

## 4. Rename tabel data historis ML

Tabel data 5.243 baris (saat ini bernama `daily_catering`) HARUS di-rename supaya
nama `daily_catering` bebas dipakai untuk VIEW.

```sql
ALTER TABLE daily_catering RENAME TO ml_catering_historical;
```

> Setelah rename, update kode ML yang membaca tabel ini (clean_dataset.py,
> feature_engineering.py, train_models.py, evaluate_models.py, predict*.py,
> serta model Laravel terkait). ML tetap membaca lewat VIEW `daily_catering`
> untuk data gabungan, dan `ml_catering_historical` untuk data historis murni.

---

## 5. VIEW `daily_catering` (UNION historis + live ERP)

Ini sumber TUNGGAL yang dibaca ML. Menggabungkan historis (ML) + live (ERP).

```sql
CREATE OR REPLACE VIEW daily_catering AS

-- (A) DATA HISTORIS (dataset 5.243 baris milik ML)
SELECT
    kode_mandor,
    tanggal,
    waktu_makan,
    jumlah_bungkus,
    harga_per_bungkus,
    sumber_data
FROM ml_catering_historical

UNION ALL

-- (B) LIVE ERP — unpivot SIANG
SELECT
    mm.kode_mandor,
    do2.order_date              AS tanggal,
    'siang'::text               AS waktu_makan,
    dod.lunch_qty               AS jumlah_bungkus,
    dod.price_per_portion       AS harga_per_bungkus,
    'DETAIL_HARIAN_ASLI'::text  AS sumber_data
FROM daily_order_details dod
JOIN daily_orders do2 ON do2.id = dod.daily_order_id
JOIN ml_mandor mm     ON mm.erp_mandor_id = dod.mandor_id
WHERE do2.is_locked = TRUE AND dod.lunch_qty > 0

UNION ALL

-- (C) LIVE ERP — unpivot SORE
SELECT
    mm.kode_mandor,
    do2.order_date,
    'sore'::text,
    dod.dinner_qty,
    dod.price_per_portion,
    'DETAIL_HARIAN_ASLI'::text
FROM daily_order_details dod
JOIN daily_orders do2 ON do2.id = dod.daily_order_id
JOIN ml_mandor mm     ON mm.erp_mandor_id = dod.mandor_id
WHERE do2.is_locked = TRUE AND dod.dinner_qty > 0;
```

Hasil: ML tetap `SELECT ... FROM daily_catering` tanpa ubah kode query, dan otomatis
mendapat data historis + data live ERP terbaru.

---

## 6. Aturan Data Lump-Sum (offline / no sinyal)

- Pemasukan WARUNG total harian → catat di modul keuangan ERP (penyesuaian kas /
  rekap kas harian). TIDAK relevan untuk ML (ML tidak pakai data warung).
- CATERING yang hanya punya total (tanpa rincian per mandor) → JANGAN diberi
  `sumber_data='DETAIL_HARIAN_ASLI'`. Tandai sebagai estimasi. VIEW hanya mengambil
  `DETAIL_HARIAN_ASLI`, jadi data estimasi otomatis diabaikan model.

---

## 7. Checklist Eksekusi (dijalankan ML engineer)

1. [ ] Backup database dulu.
2. [ ] `ALTER TABLE daily_catering RENAME TO ml_catering_historical;`
3. [ ] `CREATE TABLE ml_mandor (...)` + isi mapping kode_mandor ↔ erp_mandor_id.
4. [ ] `CREATE OR REPLACE VIEW daily_catering AS ...` (§5).
5. [ ] Update kode ML (Python + Laravel) untuk nama tabel baru.
6. [ ] Tes: `SELECT sumber_data, COUNT(*) FROM daily_catering GROUP BY sumber_data;`
       → harus ada baris historis; baris live muncul setelah ada order ERP terkunci.

---

## 8. Sisi ERP: yang TIDAK berubah

- Tidak ada perubahan pada tabel ERP mana pun.
- Tidak ada model/route baru untuk tabel ML.
- Tidak ada migration ERP terkait ML.
- ERP tetap berjalan normal, tidak sadar keberadaan tabel ML.
