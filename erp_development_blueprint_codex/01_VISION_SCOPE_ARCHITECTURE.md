# 01 — Vision, Scope, and Architecture

## Visi
ERP tetap menjadi pusat seluruh transaksi bisnis dan dikembangkan menjadi platform yang menghubungkan perusahaan dengan pelanggan umum, mandor, dan PT.

## Tujuan
- mengurangi input ulang dari WhatsApp;
- mengurangi human error;
- mempercepat order, produksi, pengiriman, pembayaran, dan invoice;
- transparansi hutang dan invoice;
- menjaga single source of truth;
- mempertahankan histori;
- meningkatkan traceability.

## Existing core yang wajib dipertahankan
- order internal;
- produksi;
- persediaan;
- keuangan;
- piutang;
- hutang;
- pengiriman;
- dashboard;
- audit internal;
- alur realtime dan manual backfill existing.

## Arsitektur target
```text
Portal Pelanggan / Portal Mandor / Portal PT
                    |
                    v
                 ERP CORE
Order | Production | Inventory | Delivery | Finance
Receivable | Payable | Invoice | Contract | Audit
                    |
                    v
                Dashboard
```

## Guardrail teknis
- satu PostgreSQL database existing;
- portal hanya channel input/display;
- route: request, validation, authorization, response;
- service: business rule dan transaction boundary;
- template tidak menyimpan business rule;
- helper lintas modul berada di service/helper domain;
- tidak ada import route-ke-route;
- tidak ada commit/rollback langsung di route;
- migration baru untuk schema baru;
- migration lama immutable;
- kompatibilitas route/data lama dipertahankan.

## Non-goals
- microservices;
- rebuild;
- mobile native tahap awal;
- chat internal;
- sistem navigasi sendiri;
- payment gateway tahap awal;
- penggabungan invoice antar-periode.
