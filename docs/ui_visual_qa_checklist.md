# ERP Visual QA Checklist

Gunakan status `PASS`, `FAIL`, atau `BLOCKED` untuk setiap butir. Catat route,
browser, build/commit, jenis data, viewport CSS, zoom, DPR, dan tautan screenshot.
Build/test hijau dan tidak adanya error JavaScript bukan pengganti inspeksi visual.

## Matriks Wajib

- [ ] Desktop 1440 px, zoom 100%.
- [ ] Desktop 1440 px, zoom 80%.
- [ ] Desktop 1440 px, zoom 67%.
- [ ] Desktop 1280 px, zoom 100%.
- [ ] Tablet 768 px.
- [ ] Mobile 390 px.
- [ ] Data kosong dan data panjang/ekstrem yang aman.
- [ ] Dropdown terbuka dekat sisi atas, bawah, kiri, dan kanan viewport.

Catat zoom dan responsive viewport secara terpisah. Untuk emulasi zoom, simpan
lebar fisik screenshot, `window.innerWidth`, dan `devicePixelRatio` sebagai bukti.

## App Shell

- [ ] Sidebar, topbar, dan content area tidak overlap atau keluar viewport.
- [ ] Tidak ada horizontal scroll pada dokumen atau shell.
- [ ] Kontrol navigasi dan akun tetap dapat diakses dengan keyboard dan pointer.
- [ ] Elemen fixed/sticky tidak menutupi judul, toolbar, modal, atau dropdown.

## Page Header

- [ ] Judul, deskripsi, breadcrumb/konteks, dan aksi utama memiliki hierarki jelas.
- [ ] Teks panjang wrap dengan wajar; grup aksi dapat wrap tanpa overlap.
- [ ] Aksi penting tetap terlihat dan dapat digunakan pada mobile.

## Filter Toolbar

- [ ] Semua label, input, select, tombol filter, dan reset tetap lengkap.
- [ ] Nama/value/query parameter existing tidak berubah.
- [ ] Grid/flex child memakai `min-width: 0` dan wrap/breakpoint yang aman.
- [ ] Focus ring terlihat dan tidak terpotong.

## Form

- [ ] Label terhubung ke control; help/error text tidak bertabrakan.
- [ ] Input panjang, validation state, disabled, readonly, dan required diperiksa.
- [ ] Tombol submit/cancel tidak keluar viewport dan urutannya konsisten.
- [ ] Tidak ada horizontal scroll pada form.

## Table

- [ ] Header, data, angka, status, dan aksi selaras serta tetap terbaca.
- [ ] Horizontal scroll hanya berada pada wrapper tabel bila diperlukan.
- [ ] Kolom pertama dan kolom aksi dapat dicapai dengan scroll/keyboard.
- [ ] Nama, kode, nominal, unit, dan status panjang tidak memecah layout.
- [ ] Empty row tidak diperlakukan sebagai row data oleh enhancer global.

## Dropdown

- [ ] Trigger, selected value, search, group label, dan option rata kiri.
- [ ] Menu terbuka di dalam viewport dan tidak terpotong oleh overflow ancestor.
- [ ] Label panjang wrap; item aktif/hover/focus tetap terbaca.
- [ ] Keyboard open, navigate, select, Escape, dan focus return bekerja.

## Modal

- [ ] Dialog berada dalam viewport dan body modal dapat scroll bila perlu.
- [ ] Backdrop, focus trap, Escape, close, confirm, dan cancel bekerja.
- [ ] Dropdown/date picker di dalam modal tidak tertutup atau salah z-index.

## States

- [ ] Empty state memakai copy dan action yang sesuai konteks halaman.
- [ ] Loading state tidak menggeser struktur secara liar.
- [ ] Error/validation state terlihat, dapat dibaca, dan tidak menutup control.
- [ ] Tidak ada action dummy atau informasi bisnis yang disembunyikan.

## Sign-off

- [ ] Screenshot tersedia untuk setiap kondisi yang dijalankan.
- [ ] Tidak ada overlap, clipping tak disengaja, atau elemen penting di luar viewport.
- [ ] Overflow dokumen = 0; overflow tabel dicatat dan diuji sampai kolom aksi.
- [ ] Defect lokal yang diperbaiki dan risiko global yang ditunda dipisahkan jelas.
- [ ] Build CSS, static contract, route/template test, dan hitungan `!important` lulus.
