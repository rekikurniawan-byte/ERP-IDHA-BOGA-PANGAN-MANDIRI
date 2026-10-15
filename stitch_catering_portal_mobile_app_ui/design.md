# DESIGN SYSTEM SPECIFICATION (DESIGN.md)
# Product: Portal Katering Mobile - PT Idha Boga Pangan Mandiri
# Target: Smartphone / Mobile App (Standar Super-App Indonesia: Gojek / Grab)
## 1. DESIGN PHILOSOPHY & ANTI-AI SLOP RULES
- **Anti-AI Slop Rule 1 (Zero Generic Placeholders):** Dilarang keras memakai "Lorem Ipsum", nama fiktif "John Doe", atau label template "Item 1, Card Title". Semua teks wajib bahasa Indonesia kontekstual lapangan katering (contoh: "Mandor Hendra", "Barak Mess A", "Ayam Bakar Madu", "Rp 4.250.000").
- **Anti-AI Slop Rule 2 (No Generic AI Purple/Crypto Gradients):** Jangan gunakan palet warna ungu/neon template AI generik. Gunakan palet hangat katering terpercaya: Oranye Katering Segar, Slate Navy gelap untuk kartu keuangan, dan putih bersih untuk card kontras tinggi.
- **Anti-AI Slop Rule 3 (Zero Horizontal Scroll Tables):** Dilarang memasukkan tabel desktop yang dipaksa ke mobile. Semua data disajikan dalam bentuk Mobile Cards modular, clean list, atau accordion sentuh.
- **Thumb-Zone Ergonomics:** Semua aksi utama (tombol bayar, counter porsi +/-, navigasi tab) berada di area jangkauan jempol bawah layar (Bottom 60% of viewport).
---
## 2. COLOR PALETTE & TOKENS
- **Brand Primary:** `#EA580C` (Warm Deep Orange) - Tombol aksi utama, status aktif, aksen brand.
- **Brand Primary Hover/Active:** `#C2410C` (Darker Orange)
- **Financial Slate (Hero Card):** `#0F172A` (Deep Navy Slate) - Kartu ringkasan tagihan gaya e-wallet (GoPay/OVO style).
- **Background Surface:** `#F8FAFC` (Cool Off-White) - Latar belakang layar bersih dan sejuk di mata.
- **Card Surface:** `#FFFFFF` (Pure White) dengan border halus `#E2E8F0` dan bayangan lembut `0 4px 12px rgba(0, 0, 0, 0.05)`.
- **Text Hierarchy:**
  * Title/Headings: `#0F172A` (Slate 900 - Kontras tinggi di bawah terik matahari)
  * Body Text: `#334155` (Slate 700)
  * Muted/Caption: `#64748B` (Slate 500)
- **Semantic Status Badges (Pills):**
  * Sukses / Lunas / Selesai: Background `#DCFCE7`, Teks `#15803D`
  * Menunggu / Perlu Konfirmasi: Background `#FEF3C7`, Teks `#B45309`
  * Bahaya / Terkunci / Blokir: Background `#FEE2E2`, Teks `#B91C1C`
  * Info / Sedang Diantar: Background `#E0F2FE`, Teks `#0369A1`
---
## 3. TYPOGRAPHY SYSTEM
- **Font Family:** `Plus Jakarta Sans` atau `Inter`, sans-serif modern.
- **Scale:**
  * Greeting/Hero Balance: 24px - 28px (Bold 700)
  * Section Titles: 18px (Bold 600)
  * Card Titles & Menu Names: 15px - 16px (Semi-Bold 600)
  * Body Text: 14px (Regular 400 & Medium 500)
  * Micro Badges & Meta Info: 12px (Medium 500)
---
## 4. COMPONENT BLUEPRINTS & TOUCH STANDARDS
### A. Persistent Bottom Navigation Bar (Wajib Mobile App)
- Tinggi: 64px + Safe Area bottom padding.
- Latar: Putih solid `#FFFFFF` dengan garis tepi atas tipis `#E2E8F0`.
- 4 Tab Navigasi Jempol:
  1. 🏠 Beranda (Home)
  2. 📋 Pesanan (Orders & Stepper Porsi)
  3. 💳 Tagihan (Invoices & Pembayaran)
  4. 👤 Akun (Profil & Alamat)
- Tab aktif ditandai warna Oranye `#EA580C` dan titik indikator 4px di bawah ikon.
### B. Financial Wallet Card (GoPay/OVO Style)
- Tampilan kartu melayang di atas beranda:
  * Latar belakang: Gradien gelap elegan `linear-gradient(135deg, #0F172A 0%, #1E293B 100%)`.
  * Teks: Putih bersih. Menampilkan "Sisa Tagihan / Total Tanggungan" dalam font 24px tebal.
  * Dua tombol taktil cepat:
    - [Bayar Sekarang] (Solid Oranye `#EA580C`, tinggi 44px)
    - [Upload Bukti] (Putih transparan 15% dengan border putih)
### C. Touch-Friendly Portion Counter Card (+ / -)
- Digunakan untuk mengatur pesanan esok hari:
  * Tombol Minus `[ - ]` dan Plus `[ + ]`: Ukuran minimal **48px × 48px**, sudut melengkung 12px, mudah ditekan jempol tanpa salah sentuh.
  * Angka porsi di tengah: 24px Bold (`40 Porsi`).
  * Countdown timer penguncian: "Terkunci dalam 1 jam 45 menit (10.00 WIB)".
### D. BottomSheet Dialog (Alasan Porsi 0)
- Jika tombol porsi diturunkan ke 0, muncul BottomSheet meluncur dari bawah (bukan popup kaku desktop):
  * Judul: "Pilih Alasan Porsi 0"
  * Pilihan radio dengan area sentuh luas (pilihan nyata kontrak PT Idha Boga):
    1. Libur hari ini saja
    2. Libur sampai tanggal... (dengan kalender)
    3. Berhenti sementara
    4. Proyek / pekerjaan selesai
    5. Pekerja sedang tidak di lokasi
    6. Lainnya (dengan catatan)
### E. Live Delivery Visual Stepper
- Tracker pengantaran horizontal dengan 4 titik proses visual:
  `[Diterima] ─── [Dimasak Dapur] ─── [Diantar Driver] ─── [Tiba di Lokasi]`
- Kartu supir lengkap dengan foto supir, nomor kendaraan (contoh: "Pick-up Box BG 8124 XY"), dan tombol panggil WhatsApp 1-ketuk.
---
## 5. REAL DATA CONTRACT (STRICTLY ENFORCED)
- **Nama Perusahaan:** PT Idha Boga Pangan Mandiri
- **Lokasi Dapur Utama:** Air Sugihan, Jalur 25, Kab. Ogan Komering Ilir (OKI), Sumatera Selatan.
- **Nama Pelanggan & Mandor Contoh:** Mandor Hendra (PT Musi Agro Lestari), Barak Mess KM 12.
- **Contoh Menu Harian Nyata:** 
  * Siang: Ayam Bakar Madu + Sayur Asem + Sambal Terasi + Tahu Tempe
  * Malam: Ikan Tongkol Balado + Tumis Buncis Jagung + Kerupuk
- **Jam Lock Pesanan:** Siang tepat pukul 10.00 WIB, Malam tepat pukul 15.00 WIB.
- **Format Mata Uang:** Format Indonesia baku, contoh: `Rp 125.412` (termasuk kode unik 3 digit untuk verifikasi otomatis).