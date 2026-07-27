# 07 — Implementation Roadmap

## Stage 0 — Baseline hardening
Wajib sebelum fitur baru besar:
- runtime/route regression audit;
- route smoke coverage;
- template/url_for audit;
- transaction atomicity;
- migration integrity;
- PostgreSQL test;
- backup/restore drill;
- clean baseline/tag;
- UAT existing core.

## Stage 1 — Portal dan order dasar
- portal pelanggan/mandor;
- role mapping;
- order dan lokasi;
- status;
- prepayment guard;
- admin confirmation.

Tidak termasuk gateway, subscription, scoring, atau approval kompleks.

## Stage 2 — Financial visibility
- dashboard hutang/invoice;
- cicilan;
- payment history;
- closing;
- PT monitoring mandor;
- worker debt detail.

Prioritaskan read model dari sumber existing sebelum membuat tabel baru.

## Stage 3 — Payment enhancement
- QRIS statis;
- transfer verification;
- cash confirmation;
- allocation;
- proof upload;
- receivable recap.

## Stage 4 — Contract and service quality
- contract;
- expiry notification;
- complaint;
- return;
- document archive;
- adjustment workflow.

## Stage 5 — Operational automation
- subscription;
- cut-off;
- change/cancel approval;
- SLA;
- notification center;
- delegation.

## Stage 6 — Advanced governance
- approval engine penuh;
- customer scoring;
- blacklist;
- advanced reporting;
- optimization;
- integration lanjutan.

## Gate tahap
Tahap hanya ditutup jika:
- acceptance criteria terpenuhi;
- tidak ada P0 blocker;
- migration dan rollback diuji;
- full suite lulus;
- UAT selesai;
- laporan dibuat;
- perubahan sensitif telah disetujui.
