from copy import deepcopy

from flask import Blueprint, abort, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.routing import BuildError

from app.services.disaster_recovery_sop_service import (
    get_backup_restore_sop,
    get_disaster_recovery_sop,
)
from app.utils.roles import effective_role
from app.utils.terms import L
from app.services.ops_navigation_service import uses_ops_ui


sop_bp = Blueprint("sop", __name__, url_prefix="/sop")


ROLE_ORDER = ['owner',
 'admin',
 'finance',
 'accounting',
 'canteen',
 'logistics',
 'dapur',
 'delivery',
 'hr',
 'master',
 'settings',
 'ui']

SOP_LIBRARY = {'owner': {'title': 'SOP Owner',
           'eyebrow': 'Owner / Direksi',
           'icon': 'bi-person-badge',
           'summary': 'Membaca kesehatan bisnis end-to-end: realtime order, manual backfill buku, invoice, piutang per pihak ditagih, '
                      'payment, stok, warung, payroll, jurnal, audit, dan recovery.',
           'purpose': ['Memantau kondisi usaha catering dan warung dari dashboard sampai transaksi sumber tanpa ikut input harian terlalu '
                       'detail.',
                       'Memastikan dua jalur penagihan berjalan benar: REALTIME order harian dan MANUAL_BACKFILL dari buku/rekap lama.',
                       L('Mengawasi piutang berdasarkan pihak ditagih: {sub_client}, {client}, Kelompok, Perorangan, atau {client} Lain.'),
                       'Memastikan invoice, pembayaran, stok, payroll, jurnal, backup, dan audit log berada pada status wajar sebelum '
                       'keputusan bisnis diambil.'],
           'when_used': ['Setiap pagi untuk cek order aktif, delivery, stok kritis, piutang, hutang supplier, payroll, warung, dan '
                         'reminder penting.',
                         'Akhir minggu atau akhir bulan untuk membaca omzet, kas masuk, sisa piutang, beban, HPP, dan laporan accounting.',
                         'Saat ada tagihan dari buku lama, sarapan/pagi, warung/kasbon, atau pihak bebas yang perlu masuk invoice/piutang.',
                         'Sebelum patch besar, restore, closing, atau import data penting.'],
           'prepared_data': ['Periode laporan: hari ini, minggu ini, bulan ini, atau tanggal custom.',
                             L('Nama pihak ditagih atau pihak lapangan: {sub_client_lower}, {client_lower}, kelompok, perorangan, atau {client_lower} lain.'),
                             'Dokumen pendukung: rekap buku, invoice, bukti transfer, bukti delivery, nota pembelian, dan payroll jika '
                             'perlu audit.'],
           'steps': ['Buka Dashboard Owner untuk membaca KPI order, invoice, payment, piutang, stok, payroll, warung, dan reminder.',
                     'Buka Keuangan > Piutang untuk melihat gabungan piutang realtime dan manual backfill dengan filter tipe pihak, cabang, '
                     'periode, status, dan asal invoice.',
                     'Buka Invoice dan Pembayaran untuk mengecek invoice aktif, sebagian bayar, lunas, atau invoice dari manual backfill.',
                     'Buka Manual Backfill jika ada rekap buku lama, sarapan/pagi, warung/kasbon, atau pihak bebas yang belum berasal dari '
                     'realtime.',
                     'Buka Laporan > Laporan Keuangan dan Akuntansi > Cek Kesehatan Data untuk cek dampak jurnal, balance, dan transaksi belum posting.',
                     'Buka Audit Log saat perlu menelusuri siapa yang membuat, mengubah, lock, void, invoice, bayar, atau menghapus bukti.',
                     'Sebelum patch besar, buka Backup/Restore dan pastikan backup VERIFIED tersedia.'],
           'outputs': ['Keputusan follow up tagihan, penagihan ulang, pembayaran supplier, pembelian, payroll, atau koreksi data.',
                       'Daftar transaksi yang perlu dicek role terkait berdasarkan sumber realtime/manual '
                       'backfill/warung/payroll/logistics.',
                       'Laporan finance/accounting/operational yang siap dibaca, dicetak, atau diekspor.'],
           'journals': ['Owner tidak membuat jurnal dari dashboard, tetapi membaca dampak jurnal dari invoice, payment, procurement, '
                        'warung, payroll, HPP, dan closing.',
                        'Omzet invoice dan kas masuk harus dibedakan: invoice mengakui piutang/pendapatan, payment mengurangi piutang dan '
                        'menambah kas/bank.',
                        'Angka laba rugi hanya valid jika transaksi sumber sudah diposting sesuai flow accounting.'],
           'unposted': ['Invoice/payment yang belum masuk jurnal karena mapping COA atau status belum final.',
                        'Payroll FINAL yang belum post journal.',
                        'Procurement, HPP, warung, atau transaksi manual yang belum generate/post journal.',
                        'Manual backfill VOID tidak boleh dianggap piutang aktif.'],
           'common_mistakes': ['Menyamakan omzet dengan kas masuk. Omzet invoice dan payment diterima harus dibaca terpisah.',
                               'Menganggap semua cash keluar otomatis beban. Beban akuntansi tetap harus berasal dari akun expense/COGS '
                               'yang benar.',
                               L('Menyamaratakan {sub_client_lower} sebagai pihak resmi di semua flow. Di REALTIME {sub_client_lower} adalah PIC lapangan; di '
                                 'MANUAL_BACKFILL {sub_client_lower} boleh menjadi pihak ditagih jika memang sumber buku/tagihan menagih ke {sub_client_lower}.'),
                               'Menyuruh restore sebelum backup diverifikasi.'],
           'work_links': [{'label': 'Dashboard Owner', 'endpoint': 'dashboard.owner', 'icon': 'bi-speedometer2'},
                          {'label': 'Invoice dan Pembayaran', 'endpoint': 'finance.invoices', 'icon': 'bi-receipt'},
                          {'label': 'Piutang Finance', 'endpoint': 'finance.receivables', 'icon': 'bi-cash-coin'},
                          {'label': 'Manual Backfill Rekap Buku',
                           'endpoint': 'finance.manual_billing_batches_list',
                           'icon': 'bi-journal-plus'},
                          {'label': 'Laporan Akuntansi', 'endpoint': 'accounting.reports', 'icon': 'bi-bar-chart-line'},
                          {'label': 'Cek Kesehatan Data', 'endpoint': 'accounting.data_health', 'icon': 'bi-clipboard-pulse'}]},
 'admin': {'title': 'SOP Admin Catering',
           'eyebrow': 'Admin Operasional / Realtime Order',
           'icon': 'bi-diagram-3',
           'summary': 'Alur REALTIME order harian dari input order, lock, produksi, delivery, bukti terima, sampai siap dibuat invoice '
                      'tanpa mengubah jalur manual backfill.',
           'purpose': ['Memastikan order harian masuk lengkap sebelum dipakai dapur, delivery, finance, dan accounting.',
                       'Menjaga flow REALTIME tetap bersih: order harian → lock → rekap/invoice → piutang → pembayaran.',
                       'Menghubungkan operasional harian dengan bukti delivery dan invoice periode.',
                       'Memisahkan kasus buku lama/sarapan/pihak bebas ke jalur MANUAL_BACKFILL agar realtime tidak dipaksa berubah.'],
           'when_used': [L('Saat ada order baru dari {client_lower}, {sub_client_lower}/PIC lapangan, atau {location_lower}.'),
                         'Saat jumlah porsi berubah sebelum atau setelah order dikunci.',
                         'Saat produksi selesai dan delivery harus dibuat agar muncul di role pengantar.',
                         'Saat finance membutuhkan dasar realtime yang sudah locked untuk invoice periode.'],
           'prepared_data': [L('Tanggal order, {client_lower}, {sub_client_lower}/PIC lapangan, {location_lower}, batch makan realtime yang tersedia, jumlah porsi, '
                               'dan harga per porsi.'),
                             L('Menu atau catatan khusus dari {client_lower}/{sub_client_lower}.'),
                             'Informasi driver/default delivery bila pengiriman harus dibuat.',
                             'Catatan jika ada kebutuhan sarapan/pagi: diarahkan ke finance melalui Manual Backfill, bukan dipaksa masuk '
                             'realtime.'],
           'steps': [L('Buka Operasional > Order Harian lalu buat order sesuai tanggal, {client_lower}, {sub_client_lower}, lokasi, batch makan realtime, dan jumlah '
                       'porsi.'),
                     'Tambah detail order sampai jumlah porsi dan harga benar.',
                     'Cek kembali data order, lalu lock order agar menjadi dasar produksi dan invoice.',
                     'Generate produksi dari order yang sudah locked.',
                     'Setelah produksi selesai, cek next action untuk membuat delivery sesuai batch yang ada.',
                     'Pastikan bukti penerimaan dari driver/pengantar sudah masuk sebelum invoice ditagihkan.',
                     'Akhir periode, arahkan finance membuat invoice periode dari order locked dan delivery valid.',
                     'Jika sumbernya rekap buku lama, sarapan/pagi, warung/kasbon, atau pihak bebas, gunakan SOP Finance Manual Backfill.'],
           'outputs': ['Order locked yang siap diproduksi.',
                       'Produksi dan delivery terkait order.',
                       L('Dasar invoice periodik realtime yang bisa ditagihkan ke {client_lower}.'),
                       'Pemisahan jelas antara transaksi realtime dan transaksi manual backfill.'],
           'journals': ['Input order dan produksi tidak selalu langsung membuat jurnal akuntansi.',
                        'Jurnal muncul pada tahap invoice, payment, HPP/stock consumption, atau posting accounting sesuai flow '
                        'masing-masing.'],
           'unposted': ['Order locked belum berarti revenue sudah jadi jurnal.',
                        'Produksi selesai belum berarti HPP sudah masuk jurnal jika stock/HPP consumption belum digenerate.',
                        'Delivery selesai belum berarti payment sudah diterima.'],
           'common_mistakes': ['Lupa lock order sehingga produksi atau invoice tidak punya dasar final.',
                               'Lupa membuat delivery setelah produksi selesai sehingga tugas tidak muncul di pengantar.',
                               'Mengubah data setelah lock tanpa revisi sehingga histori operasional tidak jelas.',
                               'Memasukkan sarapan/pagi ke realtime dengan cara memanipulasi batch. Sarapan/pagi harus lewat Manual '
                               'Backfill.'],
           'work_links': [{'label': 'Order Harian', 'endpoint': 'operational.orders', 'icon': 'bi-journal-text'},
                          {'label': 'Produksi Dapur', 'endpoint': 'production.index', 'icon': 'bi-egg-fried'},
                          {'label': 'Pengiriman', 'endpoint': 'delivery.index', 'icon': 'bi-truck'},
                          {'label': 'Rekap Catering Harian', 'endpoint': 'operational.daily_catering_log', 'icon': 'bi-calendar2-check'},
                          {'label': 'Rekap Catering Bulanan', 'endpoint': 'operational.monthly_catering_recap', 'icon': 'bi-calendar3'},
                          {'label': 'Manual Backfill Finance', 'endpoint': 'finance.manual_billing', 'icon': 'bi-journal-plus'}]},
 'finance': {'title': 'SOP Finance',
             'eyebrow': 'Invoice / Payment / Piutang Finance / Manual Backfill / Kas Bank',
             'icon': 'bi-wallet2',
             'summary': 'Alur penagihan resmi dari realtime dan manual backfill, pembayaran, piutang per pihak ditagih, kas/bank, '
                        'supplier, aset tetap, dan bukti digital.',
             'purpose': ['Membuat invoice resmi dari order/periode realtime yang sudah valid.',
                         'Membuat rekap manual dari buku untuk catering, sarapan/pagi, warung/kasbon, dan pihak ditagih fleksibel tanpa '
                         'mengubah realtime.',
                         'Mencatat pembayaran sesuai invoice, tanggal, metode, rekening, nominal, dan bukti transfer.',
                         'Memantau Piutang Finance gabungan realtime dan manual backfill sampai lunas.',
                         'Menjaga cash/bank, supplier bill, aset tetap, cicilan aset, advance, transport, dan biaya operasional tetap '
                         'tertib.'],
             'when_used': ['Saat akhir periode tagihan catering realtime sudah siap dibuat invoice.',
                           'Saat ada rekap buku/manual yang perlu dibuat draft, diedit, lock, void, print, invoice/piutang, dan '
                           'pembayaran.',
                           'Saat pembayaran masuk melalui cash, transfer, QRIS, atau metode lain yang tersedia.',
                           'Saat perlu mencetak invoice, kwitansi, rekap manual, laporan piutang, atau export CSV.',
                           'Saat ada hutang supplier, pembelian aset tetap, cicilan aset, uang muka, transport, atau biaya operasional.'],
             'prepared_data': [L('Untuk realtime: {client_lower}, periode invoice, order locked, delivery/bukti terima, dan nominal '
                                 'tagihan.'),
                               'Untuk manual backfill: periode buku, cabang, kategori tagihan, tipe pihak ditagih, snapshot nama, nomor '
                               'HP/alamat/catatan bila ada.',
                               'Untuk pihak ditagih manual: MANDOR_EXISTING, CLIENT_EXISTING, KELOMPOK, PERORANGAN, atau CLIENT_LAIN.',
                               'Rincian catering manual per tanggal: sarapan/pagi jika ada, siang, sore, harga, dan catatan. Tanggal dobel '
                               'dalam satu rekap tidak boleh.',
                               'Rincian warung/kasbon manual dan penyesuaian baris tambahan bila ada.',
                               'Tanggal invoice dan tanggal pembayaran. Tanggal bayar tidak boleh lebih awal dari tanggal invoice.',
                               'Metode pembayaran, rekening kas/bank, nomor referensi, dan bukti transfer.'],
             'steps': ['Untuk realtime, buka Invoice dan Pembayaran lalu generate invoice dari order/periode yang sudah valid.',
                       'Untuk manual backfill, buka Keuangan > Tagihan Manual > Buat Rekap Manual dari Buku.',
                       L('Pilih tipe pihak ditagih: {sub_client} Existing, {client} Existing, Kelompok, Perorangan, atau {client} Lain. Untuk pihak '
                         'bebas, isi snapshot nama tanpa wajib master {sub_client_lower}/{client_lower}/PIC.'),
                       'Isi periode. Baris catering otomatis mengikuti tanggal mulai-selesai; baris pertama bisa menurunkan pola '
                       'sarapan/siang/sore/harga/catatan ke baris berikutnya, tetapi setiap baris tetap boleh diedit.',
                       'Gunakan Tambah Baris Catering atau Tambah Baris Warung jika ada penyesuaian di luar pola normal.',
                       'Simpan sebagai DRAFT. Draft boleh diedit selama belum lock/invoice.',
                       'Jika salah total atau salah pihak sebelum invoice, gunakan Void Rekap selama status masih DRAFT/LOCKED dan belum '
                       'punya invoice/piutang.',
                       'Lock rekap manual setelah angka final. Sistem menolak tanggal catering dobel dan menolak invoice jika periode '
                       'belum selesai.',
                       'Buat Invoice/Piutang dari rekap manual yang locked. Sistem mengecek total rekap, item invoice, source key, '
                       'snapshot pihak, cabang, dan status aktif.',
                       'Catat pembayaran dari detail invoice. Sistem menolak tanggal pembayaran sebelum tanggal invoice dan tetap '
                       'mendukung bayar sebagian/lunas lewat flow lama.',
                       'Pantau Keuangan > Piutang untuk filter tipe pihak, cabang, periode, status, asal invoice realtime/manual backfill, '
                       'grouping total per pihak, print, dan export CSV.'],
             'outputs': ['Invoice aktif, sebagian bayar, lunas, batal/void sesuai status pembayaran dan dokumen sumber.',
                         'Rekap manual DRAFT/LOCKED/VOID/INVOICED/PARTIALLY_PAID/PAID yang bisa ditelusuri.',
                         'Payment receipt, lampiran bukti pembayaran, dan sisa piutang terkini.',
                         'Ledger kas/bank, laporan Piutang Finance, export CSV, print invoice, print rekap manual, dan statement piutang.',
                         'Supplier bill, payment supplier, aset tetap, cicilan aset, advance, transport, dan biaya operasional sesuai '
                         'modul finance terkait.'],
             'journals': ['Invoice membentuk Dr Piutang Usaha dan Cr Pendapatan saat generate/post journal sesuai flow accounting.',
                          'Payment membentuk Dr Kas/Bank dan Cr Piutang Usaha jika mapping COA dan data pembayaran valid.',
                          'Manual backfill tetap masuk invoice/piutang existing, bukan tabel piutang paralel.',
                          'Warung eksternal memakai Piutang Usaha/Pendapatan Warung sesuai flow canteen/accounting.',
                          'Supplier bill, fixed asset, cicilan, advance, transport, dan biaya operasional mengikuti mapping jurnal '
                          'masing-masing.'],
             'unposted': ['Invoice draft/baru belum tentu sudah punya jurnal jika posting accounting belum dijalankan.',
                          'Payment tanpa rekening/mapping COA benar bisa gagal posting jurnal.',
                          'Manual backfill DRAFT/LOCKED belum menjadi invoice/piutang sampai tombol Buat Invoice/Piutang dijalankan.',
                          'Rekap manual VOID tidak boleh dianggap piutang aktif dan tidak boleh dibuat invoice.',
                          'Supplier/asset/expense yang belum diposting belum muncul penuh di laporan accounting.'],
             'common_mistakes': ['Membuat invoice manual sebelum periode rekap selesai.',
                                 'Menginput tanggal catering yang sama dua kali dalam satu rekap sehingga dobel tagih. Sistem sekarang '
                                 'menolak ini.',
                                 'Mencatat pembayaran dengan tanggal sebelum invoice. Sistem sekarang menolak ini.',
                                 'Memaksa sarapan/pagi masuk realtime. Sarapan/pagi hanya di Manual Backfill.',
                                 'Mengubah rekap manual setelah lock/invoice. Edit hanya untuk DRAFT; setelah invoice koreksi harus lewat '
                                 'prosedur pembatalan/koreksi yang aman.',
                                 'Membuat jalur/tabel manual_book_recaps. Keputusan proyek: tidak dibuat karena berisiko paralel dan tidak '
                                 'diperlukan.',
                                 L('Membaca Piutang Finance sebagai piutang {client_lower} saja. Halaman ini sekarang mencakup '
                                   '{sub_client}/{client}/Kelompok/Perorangan/{client} Lain.')],
             'work_links': [{'label': 'Invoice dan Pembayaran', 'endpoint': 'finance.invoices', 'icon': 'bi-receipt'},
                            {'label': 'Piutang Finance', 'endpoint': 'finance.receivables', 'icon': 'bi-cash-coin'},
                            {'label': 'Manual Billing Hub', 'endpoint': 'finance.manual_billing', 'icon': 'bi-journal-plus'},
                            {'label': 'Daftar Rekap Manual Buku',
                             'endpoint': 'finance.manual_billing_batches_list',
                             'icon': 'bi-list-check'},
                            {'label': 'Input Rekap Manual Buku',
                             'endpoint': 'finance.manual_billing_backfill_form',
                             'icon': 'bi-pencil-square'},
                            {'label': 'Riwayat Pembayaran', 'endpoint': 'finance.payment_history', 'icon': 'bi-clock-history'},
                            {'label': 'Kas/Bank Ledger', 'endpoint': 'finance.cash_bank_ledger', 'icon': 'bi-bank'},
                            {'label': 'Supplier Bills', 'endpoint': 'finance.supplier_bills', 'icon': 'bi-file-earmark-text'},
                            {'label': 'Pembelian Aset Tetap', 'endpoint': 'finance.fixed_asset_purchases', 'icon': 'bi-building-add'},
                            {'label': 'Cicilan Aset Tetap', 'endpoint': 'finance.fixed_asset_installments', 'icon': 'bi-calendar2-check'}]},
 'accounting': {'title': 'SOP Accounting',
                'eyebrow': 'Jurnal / COA / Tutup Buku / Cek Kesehatan Data',
                'icon': 'bi-journal-check',
                'summary': 'Alur pengecekan jurnal dari realtime, manual backfill, warung, supplier, payroll, HPP, aset, dan closing agar '
                           'laporan tetap balance.',
                'purpose': ['Memastikan semua transaksi yang seharusnya masuk jurnal sudah balance dan sesuai COA mapping.',
                            'Memisahkan sumber transaksi: realtime, manual backfill, canteen/warung, supplier, payroll, HPP, fixed asset, '
                            'dan manual field transaction.',
                            'Menjaga laporan trial balance, general ledger, income summary, dan closing tidak tercampur data belum final.'],
                'when_used': ['Setiap hari setelah finance/logistics/HR melakukan transaksi penting.',
                              'Setelah invoice realtime atau invoice manual backfill dibuat.',
                              'Setelah payment masuk, supplier bill dibayar, payroll diposting/dibayar, atau HPP dikomit.',
                              'Sebelum closing harian/periodik atau sebelum owner membaca laporan final.'],
                'prepared_data': ['Periode jurnal yang dicek.',
                                  'Nomor invoice/payment/supplier bill/payroll/order HPP bila ada selisih.',
                                  'Mapping COA revenue, piutang, kas/bank, hutang, HPP, persediaan, gaji, aset, depresiasi, dan warung.'],
                'steps': ['Buka Status Posting untuk melihat transaksi yang sudah dan belum diposting.',
                          'Generate invoice journals untuk invoice periode/realtime dan invoice manual backfill yang valid.',
                          'Generate payment journals untuk pembayaran invoice yang sudah tercatat.',
                          'Generate procurement/supplier/HPP/payroll/warung journal sesuai sumber transaksi.',
                          'Buka Cek Kesehatan Data untuk cek journal balance, FK, source trace, upload reference, dan inkonsistensi angka.',
                          'Buka General Ledger atau Trial Balance untuk membaca dampak setiap transaksi.',
                          'Lakukan closing hanya setelah transaksi sumber final, jurnal balance, dan tidak ada error kritis.'],
                'outputs': ['Jurnal balance dan bisa ditelusuri ke sumber transaksi.',
                            'Laporan akuntansi siap baca/cetak/export.',
                            'Daftar transaksi belum posting atau bermasalah untuk dikembalikan ke role sumber.'],
                'journals': ['Realtime/manual backfill invoice: Dr Piutang Usaha / Cr Pendapatan.',
                             'Pembayaran invoice: Dr Kas/Bank / Cr Piutang Usaha.',
                             L('Warung hutang {worker_lower}: Dr Piutang Karyawan / Cr Pendapatan Warung.'),
                             'Warung eksternal: Dr Piutang Usaha / Cr Pendapatan Warung.',
                             'Supplier/procurement: Persediaan/Beban atau Hutang Supplier sesuai tipe transaksi.',
                             'Payroll: Dr Beban Gaji / Cr Hutang Gaji lalu Dr Hutang Gaji / Cr Kas/Bank saat dibayar.',
                             'HPP: Dr HPP / Cr Persediaan saat stock consumption/HPP diposting.'],
                'unposted': ['Manual backfill DRAFT/LOCKED/VOID tidak membuat jurnal invoice.',
                             'Invoice tanpa journal posting belum masuk laporan penuh.',
                             'Payment tanpa rekening/mapping benar bisa tertahan.',
                             'Procurement, HPP, payroll, warung, asset depreciation, dan expense yang belum generate journal.'],
                'common_mistakes': ['Closing sebelum semua invoice/payment penting diposting.',
                                    'Membaca invoice manual backfill sebagai transaksi terpisah dari piutang existing. Secara accounting '
                                    'tetap masuk Piutang Usaha.',
                                    'Menghapus jurnal otomatis tanpa menelusuri transaksi sumber.',
                                    'Mengubah COA mapping tanpa memahami dampak laporan lama dan transaksi berikutnya.'],
                'work_links': [{'label': 'Jurnal Akuntansi', 'endpoint': 'accounting.journals', 'icon': 'bi-journal-check'},
                               {'label': 'Status Posting', 'endpoint': 'accounting.posting_status', 'icon': 'bi-check2-square'},
                               {'label': 'Peta Akun & Mapping', 'endpoint': 'accounting.coa_mapping', 'icon': 'bi-diagram-2'},
                               {'label': 'Laporan Akuntansi', 'endpoint': 'accounting.reports', 'icon': 'bi-bar-chart-line'},
                               {'label': 'Cek Kesehatan Data', 'endpoint': 'accounting.data_health', 'icon': 'bi-clipboard-pulse'},
                               {'label': 'Closing Periodik', 'endpoint': 'accounting.period_closing', 'icon': 'bi-calendar-check'}]},
 'canteen': {'title': 'SOP Warung / Canteen',
             'eyebrow': L('Penjualan Warung / Hutang {worker} / Piutang Eksternal'),
             'icon': 'bi-shop',
             'summary': L('Alur penjualan warung cepat, hutang {worker_lower}, piutang warung eksternal, pembayaran, dan koreksi jurnal warung.'),
             'purpose': [L('Mencatat penjualan warung cash, QRIS/transfer, hutang {worker_lower}, dan piutang eksternal dengan status yang jelas.'),
                         L('Memisahkan hutang {worker_lower} dari piutang eksternal agar finance/accounting tidak salah membaca sumber tagihan.'),
                         'Menjaga bukti pembayaran dan pencatatan kas/bank warung tetap rapi.'],
             'when_used': ['Saat transaksi warung harian terjadi.',
                           L('Saat {worker_lower} mengambil barang warung secara hutang/kasbon.'),
                           'Saat pihak luar membeli/berhutang di warung dan menjadi piutang eksternal.',
                           'Saat pembayaran hutang/piutang warung diterima.'],
             'prepared_data': ['Item warung, qty, harga, metode pembayaran, dan rekening bila non-cash.',
                               L('Nama {worker_lower} untuk hutang {worker_lower} atau nama pihak eksternal untuk piutang eksternal.'),
                               'Tanggal pembayaran, nominal, metode, dan bukti jika ada.'],
             'steps': ['Buka Warung/Canteen dan pilih Quick Sale atau Input Penjualan.',
                       'Pilih item, qty, harga, dan metode pembayaran.',
                       'Untuk QRIS/transfer, pilih rekening kas/bank yang benar.',
                       L('Untuk hutang {worker_lower}, wajib pilih {worker_lower}/PIC yang benar.'),
                       'Untuk piutang eksternal, isi pihak eksternal dan pastikan tidak tercampur dengan invoice catering.',
                       'Saat pembayaran diterima, buka Hutang & Piutang Warung lalu catat pembayaran sesuai sumbernya.',
                       'Accounting mengecek posting/koreksi jurnal warung bila ada status belum posting.'],
             'outputs': ['Penjualan warung tercatat.',
                         L('Hutang {worker_lower} atau piutang eksternal dapat dipantau dan dibayar.'),
                         'Kas/bank dan jurnal warung dapat ditelusuri.'],
             'journals': ['Cash/QRIS/transfer: Dr Kas/Bank / Cr Pendapatan Warung.',
                          L('Hutang {worker_lower}: Dr Piutang Karyawan / Cr Pendapatan Warung.'),
                          'Piutang eksternal: Dr Piutang Usaha / Cr Pendapatan Warung.',
                          'Pembayaran hutang/piutang warung: Dr Kas/Bank / Cr Piutang terkait.'],
             'unposted': ['Transaksi warung yang rekening/mapping-nya belum lengkap.',
                          'Pembayaran hutang/piutang warung yang belum diposting jurnal.',
                          'Koreksi warung yang belum digenerate oleh accounting.'],
             'common_mistakes': ['Memilih metode QRIS/transfer tanpa rekening.',
                                 L('Mencatat hutang {worker_lower} tanpa memilih {worker_lower}.'),
                                 'Mencampur piutang warung eksternal dengan invoice catering/manual backfill.',
                                 'Menginput qty/harga kosong lalu menganggap transaksi sudah valid.'],
             'work_links': [{'label': 'Dashboard Warung', 'endpoint': 'canteen.index', 'icon': 'bi-shop'},
                            {'label': 'Quick Sale Warung', 'endpoint': 'canteen.quick_sale', 'icon': 'bi-lightning-charge'},
                            {'label': 'Input Penjualan Warung', 'endpoint': 'canteen.create_sale', 'icon': 'bi-cart-plus'},
                            {'label': 'Hutang & Piutang Warung', 'endpoint': 'canteen.debts', 'icon': 'bi-cash-stack'},
                            {'label': 'Pembayaran Hutang/Piutang', 'endpoint': 'canteen.debt_payment', 'icon': 'bi-wallet2'}]},
 'logistics': {'title': 'SOP Logistics',
               'eyebrow': 'Stok / Pembelian / HPP / Supplier / Bukti Nota',
               'icon': 'bi-box-seam',
               'summary': 'Alur barang masuk, keluar, pemakaian dapur, pembelian, supplier bill, HPP, audit stok, dan bukti digital.',
               'purpose': ['Menjaga stok bahan baku dan barang pendukung tetap terkontrol.',
                           'Mencatat pembelian dan pemakaian barang sebagai dasar HPP dan hutang supplier.',
                           'Memberi sinyal kebutuhan bahan dari prediksi dan histori pemakaian tanpa menggantikan cek lapangan.'],
               'when_used': ['Saat belanja bahan atau barang pendukung masuk gudang.',
                             'Saat dapur memakai stok untuk produksi atau order tertentu.',
                             'Saat stok rusak, selisih, audit, atau perlu penyesuaian.',
                             'Saat permintaan barang dari dapur perlu approve/reject/fulfill.'],
               'prepared_data': ['Nama barang, satuan, jumlah, gudang, supplier, harga beli, tanggal transaksi, dan bukti nota.',
                                 'Order/produksi terkait jika pemakaian stok ingin dikaitkan ke HPP.',
                                 'Catatan selisih stok saat audit atau penyesuaian.'],
               'steps': ['Buka Stok Barang untuk membaca saldo dan status item.',
                         'Catat barang masuk lewat Pembelian Barang (tunai, transfer, atau hutang supplier) supaya uang keluar dan jurnalnya ikut tercatat.',
                         'Upload nota/bukti pembelian bila tersedia.',
                         'Untuk pembelian kredit, hubungkan ke supplier bill/hutang supplier jika flow tersedia.',
                         'Catat stok keluar/pemakaian dapur sesuai kebutuhan produksi.',
                         'Approve/reject/fulfill permintaan barang dari dapur sesuai stok real.',
                         'Gunakan prediksi bahan sebagai referensi belanja, bukan angka final tanpa cek lapangan.',
                         'Lakukan audit stok berkala dan catat selisih dengan alasan jelas.'],
               'outputs': ['Saldo stok yang lebih akurat.',
                           'Dokumen pembelian, nota digital, dan pemakaian barang.',
                           'Dasar HPP produksi/order dan hutang supplier.'],
               'journals': ['Pembelian langsung dijurnal: Dr Persediaan / Cr Kas, Bank, atau Hutang Supplier.',
                            'Setiap barang keluar langsung dijurnal dengan harga rata-rata: produksi 5001, operasional 5002, rusak/selisih kurang 5009, selisih lebih 4004.'],
               'unposted': ['Barang yang belum pernah dibeli dan tidak punya harga di saldo awal: keluarnya tidak bisa dinilai (ditandai Cek Kesehatan Data).'],
               'common_mistakes': ['Mencatat stok keluar tanpa satuan yang sesuai.',
                                   'Menganggap prediksi bahan sebagai perintah belanja final tanpa cek stok real.',
                                   'Tidak upload/arsipkan nota sehingga harga beli sulit diaudit.',
                                   'Approve permintaan barang tanpa mengecek saldo dan kebutuhan produksi.'],
               'work_links': [{'label': 'Stok Barang', 'endpoint': 'logistics.index', 'icon': 'bi-boxes'},
                              {'label': 'Prediksi Bahan', 'endpoint': 'logistics.material_forecast', 'icon': 'bi-clipboard-data'},
                              {'label': 'Pembelian', 'endpoint': 'logistics.purchases', 'icon': 'bi-cart-check'},
                              {'label': 'Permintaan Barang', 'endpoint': 'logistics.item_requests', 'icon': 'bi-inboxes'},
                              {'label': 'Pemakaian Dapur', 'endpoint': 'logistics.kitchen_usage', 'icon': 'bi-box'},
                              {'label': 'HPP Order', 'endpoint': 'costing.order_hpp_snapshots', 'icon': 'bi-clipboard-data'}]},
 'dapur': {'title': 'SOP Dapur / Produksi',
           'eyebrow': 'Produksi Harian / Realisasi Masak / Pemakaian Bahan',
           'icon': 'bi-egg-fried',
           'summary': 'Alur dapur membaca order locked, menyiapkan produksi, mencatat realisasi, meminta bahan, dan memberi sinyal siap '
                      'delivery.',
           'purpose': ['Memastikan dapur hanya memasak berdasarkan order locked yang sudah final.',
                       'Mencatat realisasi produksi supaya admin tahu batch mana yang selesai.',
                       'Menjadi dasar pemakaian bahan, HPP, dan next action delivery.'],
           'when_used': ['Setiap hari sebelum produksi dimulai.',
                         'Saat batch selesai dimasak.',
                         'Saat ada kekurangan, revisi, atau catatan produksi yang harus diketahui admin.',
                         'Saat dapur perlu meminta bahan ke logistics.'],
           'prepared_data': ['Daftar order locked per tanggal dan batch realtime.',
                             'Jumlah porsi rencana, menu, lokasi, dan catatan khusus.',
                             'Jumlah realisasi produksi dan alasan selisih jika ada.',
                             'Daftar bahan yang dibutuhkan bila stok perlu diminta.'],
           'steps': ['Buka Produksi Dapur dan pilih produksi hari ini.',
                     'Cek detail order, batch, jumlah porsi, dan lokasi sebelum mulai masak.',
                     'Jika bahan kurang, buat permintaan barang ke logistics sesuai item yang tersedia.',
                     'Setelah selesai, catat realisasi produksi sesuai jumlah yang benar-benar siap kirim.',
                     'Jika ada kekurangan atau perubahan, isi catatan agar admin bisa follow up revisi atau pengiriman.',
                     'Pastikan status produksi selesai agar admin melihat next action membuat delivery.'],
           'outputs': ['Status produksi selesai/sebagian sesuai realisasi.',
                       'Dasar membuat delivery.',
                       'Data pemakaian bahan dan HPP jika dikaitkan ke stock consumption.'],
           'journals': ['Realisasi produksi sendiri belum selalu membuat jurnal.',
                        'Jurnal HPP muncul saat pemakaian bahan/HPP diposting lewat flow accounting/logistics.'],
           'unposted': ['Produksi selesai tetapi stock usage/HPP belum commit.',
                        'Produksi selesai tetapi delivery belum dibuat.',
                        'Selisih produksi belum dicatat alasannya.'],
           'common_mistakes': ['Memasak dari order yang belum locked.',
                               'Tidak mengisi realisasi sehingga delivery tidak punya sinyal jelas.',
                               'Tidak memberi catatan saat jumlah produksi berbeda dari rencana.',
                               'Menganggap sarapan/pagi sebagai batch realtime. Sarapan/pagi adalah jalur Manual Backfill finance jika '
                               'berasal dari buku/rekap manual.'],
           'work_links': [{'label': 'Produksi Dapur', 'endpoint': 'production.index', 'icon': 'bi-egg-fried'},
                          {'label': 'Order Harian', 'endpoint': 'operational.orders', 'icon': 'bi-journal-text'},
                          {'label': 'Permintaan Barang', 'endpoint': 'logistics.item_requests', 'icon': 'bi-inboxes'},
                          {'label': 'Pemakaian Dapur', 'endpoint': 'logistics.kitchen_usage', 'icon': 'bi-box'},
                          {'label': 'Prediksi Bahan', 'endpoint': 'logistics.material_forecast', 'icon': 'bi-clipboard-data'}]},
 'delivery': {'title': 'SOP Delivery / Pengantar',
              'eyebrow': 'Pengiriman / Bukti Terima / SLA / Selisih',
              'icon': 'bi-truck',
              'summary': 'Alur pengantar melihat tugas hari ini, mengantar makanan, mencatat penerimaan, update SLA, bukti terima, dan '
                         'shortage/replacement.',
              'purpose': ['Memastikan makanan yang sudah diproduksi benar-benar sampai ke lokasi dan diterima pihak lapangan.',
                          'Menyimpan bukti terima sebagai dasar invoice dan audit operasional.',
                          'Mencatat kekurangan/selisih agar dapat diganti atau ditelusuri.'],
              'when_used': ['Setiap kali driver/pengantar akan mengirim batch makanan.',
                            'Saat sampai lokasi dan penerima sudah mengecek jumlah makanan.',
                            'Saat ada kekurangan, keterlambatan, SLA, atau bukti penerimaan perlu diupload.'],
              'prepared_data': ['Daftar delivery hari ini dari sistem.',
                                L('Jumlah planned, lokasi, {sub_client_lower}/PIC lapangan, batch makan, dan target waktu bila ada.'),
                                'Foto bukti terima, tanda tangan, atau catatan penerima jika ada.'],
              'steps': ['Buka Pengiriman Hari Ini dan pilih tugas delivery sesuai lokasi/batch.',
                        'Cek jumlah planned dan detail lokasi sebelum berangkat.',
                        'Update status dispatch/on the way sesuai tombol yang tersedia.',
                        'Setelah diterima, isi jumlah diterima, waktu penerimaan/SLA, dan catatan jika ada.',
                        'Upload bukti terima digital bila tersedia.',
                        'Jika ada kekurangan, catat shortage dan follow up replacement sesuai tombol yang tersedia.',
                        'Cek Riwayat Pengiriman untuk memastikan status sudah selesai.'],
              'outputs': ['Delivery selesai dengan bukti penerimaan.',
                          'Catatan shortage atau replacement jika ada.',
                          'Data valid untuk invoice dan follow up admin.'],
              'journals': ['Delivery tidak membuat jurnal langsung.',
                           'Dampak accounting muncul saat invoice, payment, dan HPP terkait sudah diposting.'],
              'unposted': ['Delivery selesai bukan berarti invoice sudah dibuat.',
                           'Bukti terima belum upload membuat penagihan kurang kuat.',
                           'Shortage belum diselesaikan membuat quantity invoice harus dicek ulang.'],
              'common_mistakes': ['Tidak mengisi jumlah diterima real.',
                                  'Tidak upload bukti terima padahal sudah ada foto/tanda tangan.',
                                  'Mengabaikan shortage sehingga admin tidak tahu perlu penggantian.',
                                  'Mengubah waktu/SLA tanpa alasan saat data sudah menjadi dasar evaluasi delivery.'],
              'work_links': [{'label': 'Pengiriman Hari Ini', 'endpoint': 'delivery.today', 'icon': 'bi-truck'},
                             {'label': 'Penerimaan', 'endpoint': 'delivery.receiving', 'icon': 'bi-clipboard-check'},
                             {'label': 'Riwayat Pengiriman', 'endpoint': 'delivery.history', 'icon': 'bi-clock-history'}]},
 'hr': {'title': 'SOP SDM / HR',
        'eyebrow': 'Karyawan / Payroll / Posting Gaji',
        'icon': 'bi-people',
        'summary': 'Alur karyawan internal, generate payroll, finalize, posting jurnal hutang gaji, dan pembayaran payroll.',
        'purpose': ['Mengelola data karyawan internal yang masuk payroll perusahaan.',
                    'Menghitung payroll bulanan dengan status jelas: DRAFT, FINAL, POSTED, PAID.',
                    'Memastikan pembayaran gaji tercatat dan terhubung ke jurnal sesuai status.'],
        'when_used': ['Saat ada karyawan internal baru, resign, inactive, atau perubahan gaji.',
                      'Akhir periode payroll bulanan.',
                      'Saat gaji sudah siap diposting dan dibayar.'],
        'prepared_data': ['Data karyawan internal: nama, jabatan/skill, no HP, status aktif, dan gaji aktif.',
                          'Periode payroll bulan dan tahun.',
                          'Metode pembayaran, tanggal bayar, dan rekening kas/bank jika pembayaran dilakukan.'],
        'steps': [L('Buka Karyawan Internal lalu pastikan hanya karyawan perusahaan yang masuk payroll. {sub_client} bukan karyawan payroll.'),
                  'Lengkapi gaji aktif dan status karyawan sebelum generate payroll.',
                  'Buka Buat Payroll Bulanan dan generate payroll periode yang benar.',
                  'Cek detail payroll saat status DRAFT; ubah detail hanya sebelum final.',
                  'Finalize payroll jika nominal sudah benar.',
                  'Post journal payroll untuk mencatat hutang gaji.',
                  'Bayar payroll dan cek Riwayat Pembayaran Gaji.'],
        'outputs': ['Data karyawan internal yang rapi.',
                    'Payroll bulanan dengan lifecycle jelas.',
                    'Jurnal hutang gaji dan riwayat pembayaran payroll.'],
        'journals': ['Payroll FINAL yang diposting biasanya membentuk Dr Beban Gaji dan Cr Hutang Gaji.',
                     'Pembayaran payroll biasanya membentuk Dr Hutang Gaji dan Cr Kas/Bank.'],
        'unposted': ['Payroll DRAFT belum perlu jurnal.',
                     'Payroll FINAL belum menjadi jurnal sampai tombol post journal dijalankan.',
                     'Payroll POSTED belum berarti dibayar sampai payment payroll dicatat.'],
        'common_mistakes': [L('Memasukkan {sub_client_lower} ke payroll internal. {sub_client} adalah PIC/partner lapangan, bukan karyawan payroll.'),
                            'Generate payroll sebelum data gaji karyawan lengkap.',
                            'Membayar payroll sebelum posting hutang gaji sehingga lifecycle tidak rapi.'],
        'work_links': [{'label': 'Dashboard SDM', 'endpoint': 'hr.index', 'icon': 'bi-speedometer2'},
                       {'label': 'Karyawan Internal', 'endpoint': 'hr.employees', 'icon': 'bi-people'},
                       {'label': 'Daftar Payroll', 'endpoint': 'hr.payrolls', 'icon': 'bi-cash-stack'},
                       {'label': 'Buat Payroll Bulanan', 'endpoint': 'hr.generate_payroll_route', 'icon': 'bi-calendar-plus'},
                       {'label': 'Riwayat Pembayaran Gaji', 'endpoint': 'hr.payroll_payment_history', 'icon': 'bi-clock-history'}]},
 'master': {'title': 'SOP Master Data',
            'eyebrow': L('{client} / PIC / {sub_client} / Lokasi / Barang / Supplier / Rekening'),
            'icon': 'bi-building',
            'summary': 'Aturan input data induk supaya transaksi finance, operasional, logistics, HR, warung, dan accounting tidak salah '
                       'referensi.',
            'purpose': ['Menjaga data induk tetap bersih, aktif/nonaktif jelas, dan tidak dobel.',
                        L('Memastikan transaksi memakai {client_lower}, PIC, {sub_client_lower}, lokasi, barang, supplier, rekening, driver, aset, dan {worker_lower} '
                          'yang benar.'),
                        'Mengurangi koreksi transaksi karena master data salah sejak awal.',
                        'Memahami bahwa Manual Backfill boleh memakai snapshot pihak bebas tanpa memaksa master baru.'],
            'when_used': ['Sebelum membuat order, invoice, pembelian, payroll, warung, atau ledger baru.',
                          L('Saat ada {client_lower}/{sub_client_lower}/lokasi/barang/supplier/rekening/driver/aset/{worker_lower} baru.'),
                          'Saat data lama perlu dinonaktifkan tanpa menghapus histori transaksi.'],
            'prepared_data': [L('Identitas {client_lower} dan PIC sah {client_lower} jika tersedia.'),
                              L('Data {sub_client_lower} sebagai PIC/partner lapangan; di manual backfill {sub_client_lower} juga bisa dipilih sebagai pihak ditagih '
                                'jika sumber buku begitu.'),
                              L('Data {location_lower}, driver, {worker_lower} warung, barang, supplier, rekening kas/bank, aset tetap, dan profil HPP.'),
                              L('Untuk kelompok/perorangan/{client_lower} lain manual backfill, tidak wajib dibuat master jika hanya dibutuhkan '
                                'sebagai snapshot tagihan.')],
            'steps': ['Buka menu Data Master sesuai data yang akan dibuat.',
                      'Cek apakah data sudah ada agar tidak dobel.',
                      'Isi kode/nama/kontak/status sesuai form yang tersedia.',
                      L('Untuk {client_lower}, pisahkan {client_lower} perusahaan dan PIC sah {client_lower} dari {sub_client_lower} lapangan.'),
                      'Untuk barang, pastikan satuan dan profil HPP/kosting tidak asal.',
                      'Untuk rekening, pastikan dipakai oleh flow kas/bank, payment, payroll, supplier, dan warung.',
                      'Nonaktifkan data yang tidak dipakai, jangan hapus jika sudah pernah dipakai transaksi.'],
            'outputs': ['Master data siap dipilih di transaksi.',
                        'Data aktif/nonaktif lebih tertib.',
                        'Referensi transaksi lebih mudah diaudit.',
                        'Snapshot pihak bebas manual backfill tetap tercatat tanpa membuat master berlebihan.'],
            'journals': ['Master data tidak langsung membuat jurnal.',
                         'Master COA/rekening/mapping dapat mempengaruhi jurnal yang dibuat transaksi berikutnya.'],
            'unposted': ['Master data yang kosong atau salah mapping bisa membuat transaksi gagal posting jurnal.',
                         L('{client}/PIC/rekening yang belum lengkap membuat dokumen invoice resmi kurang kuat.')],
            'common_mistakes': [L('Membuat {client_lower} dobel dengan ejaan berbeda.'),
                                'Menghapus data yang sudah punya transaksi; sebaiknya nonaktifkan.',
                                L('Mencampur {sub_client_lower} dengan karyawan payroll.'),
                                'Membuat master baru untuk setiap nama bebas manual backfill padahal snapshot sudah cukup.'],
            'work_links': [{'label': 'Kelola Master', 'endpoint': 'master.index', 'icon': 'bi-database'},
                           {'label': L('{client}'), 'endpoint': 'master.clients', 'icon': 'bi-building-check'},
                           {'label': L('{sub_client}'), 'endpoint': 'master.mandors', 'icon': 'bi-person-badge'},
                           {'label': 'Barang', 'endpoint': 'master.items', 'icon': 'bi-box-seam'},
                           {'label': 'Supplier', 'endpoint': 'master.suppliers', 'icon': 'bi-truck-flatbed'},
                           {'label': 'Rekening Bank', 'endpoint': 'master.bank_accounts', 'icon': 'bi-bank'},
                           {'label': 'Aset Tetap', 'endpoint': 'master.fixed_assets', 'icon': 'bi-building-add'}]},
 'settings': {'title': 'SOP Settings / Sistem',
              'eyebrow': 'User / Backup / Audit / Reminder / Atomic UI / Recovery',
              'icon': 'bi-gear',
              'summary': 'Aturan pengaturan perusahaan, user, password, backup-restore, audit log, lampiran, reminder, notifikasi, dan UI '
                         'safety global.',
              'purpose': ['Menjaga konfigurasi sistem tetap aman dan sesuai role.',
                          'Memastikan backup dan restore tidak merusak database aktif.',
                          'Memantau audit log, lampiran digital, reminder, notifikasi, dan perubahan user.',
                          'Memahami atomic UI baru: select/date/time, modal confirm, toast, loading guard, tabel, print/export, dan inline '
                          'JS cleanup.'],
              'when_used': ['Saat owner mengubah profil perusahaan, rekening, atau data dasar sistem.',
                            'Saat membuat user baru, reset password, atau mengaktifkan/nonaktifkan akun.',
                            'Sebelum dan sesudah backup/restore manual.',
                            'Saat memvalidasi tampilan UI setelah update besar.'],
              'prepared_data': ['Nama user, role, branch, dan status aktif.',
                                'Data profil perusahaan dan rekening resmi jika ingin tampil di dokumen.',
                                'Folder/file backup yang akan divalidasi sebelum restore.',
                                'Screenshot/halaman jika ada masalah UI, notifikasi, tombol, print, atau export.'],
              'steps': ['Buka Profil Perusahaan untuk mengatur identitas perusahaan, istilah, dan informasi dokumen resmi.',
                        'Buka Pengaturan > Pengguna untuk membuat, edit, reset password, atau menonaktifkan user sesuai role.',
                        'Buka Ganti Password untuk mengganti password sendiri bila perlu.',
                        'Buka Backup & Restore sebelum tindakan besar, lalu buat backup dan validasi file restore jika diperlukan.',
                        'Buka Audit Log saat perlu menelusuri perubahan data penting.',
                        'Buka Lampiran Digital untuk cek file bukti transaksi yang tersimpan.',
                        'Buka Notifikasi/Pengingat untuk melihat pekerjaan yang perlu follow up.'],
              'outputs': ['Konfigurasi perusahaan dan user yang lebih aman.',
                          'Backup valid yang bisa dipakai saat darurat.',
                          'Jejak audit, lampiran digital, dan reminder yang membantu pengawasan.'],
              'journals': ['Settings tidak membuat jurnal langsung.',
                           'Profil perusahaan, rekening, dan mapping dapat mempengaruhi dokumen print serta jurnal transaksi lain.'],
              'unposted': ['Tidak ada posting jurnal dari settings.',
                           'Namun konfigurasi COA/rekening/user yang salah bisa membuat flow transaksi berikutnya gagal atau tidak '
                           'lengkap.'],
              'common_mistakes': ['Memberi role terlalu luas ke user yang tidak membutuhkan akses tersebut.',
                                  'Restore database saat server masih berjalan atau tanpa validasi backup.',
                                  'Mengabaikan audit log ketika ada perubahan angka yang tidak jelas sumbernya.',
                                  'Menganggap atomic UI mengubah data. Atomic UI hanya memperbaiki tampilan/interaksi; source-of-truth '
                                  'tetap field/form backend.'],
              'work_links': [{'label': 'Profil Perusahaan', 'endpoint': 'settings.company_settings', 'icon': 'bi-building-gear'},
                             {'label': 'Pengguna', 'endpoint': 'settings.users', 'icon': 'bi-person-gear'},
                             {'label': 'Ganti Password', 'endpoint': 'settings.change_password', 'icon': 'bi-key'},
                             {'label': 'Backup & Restore', 'endpoint': 'settings.backups', 'icon': 'bi-database-down'},
                             {'label': 'SOP Disaster Recovery', 'endpoint': 'sop.disaster_recovery', 'icon': 'bi-life-preserver'},
                             {'label': 'SOP Backup & Restore', 'endpoint': 'sop.backup_restore', 'icon': 'bi-database-check'},
                             {'label': 'Audit Log', 'endpoint': 'settings.audit_logs', 'icon': 'bi-activity'},
                             {'label': 'Notifikasi', 'endpoint': 'settings.notifications', 'icon': 'bi-bell-fill'}]},
 'ui': {'title': 'SOP UI Operasional',
        'eyebrow': 'Atomic UI / Validasi / Print / Export / Anti Double Submit',
        'icon': 'bi-window-stack',
        'summary': 'Panduan menggunakan UI baru setelah polish besar: field atomic, modal confirm, toast, flash tengah, loading guard, '
                   'tabel, print/export, dan mobile behavior.',
        'purpose': ['Membantu user memahami perubahan UI tanpa mengubah flow bisnis.',
                    'Menjelaskan bahwa select/date/time/password/file/checkbox/number/text/table/print kini dipoles global.',
                    'Mencegah user klik dobel, salah membaca notifikasi, atau melewatkan confirm modal.',
                    'Menjadi checklist QA jika ada tampilan spesifik yang masih terasa aneh.'],
        'when_used': ['Setelah update sistem atau saat user merasa tampilan form/dropdown/tanggal/popup berubah.',
                      'Saat input transaksi penting seperti invoice, pembayaran, lock, void, payroll, supplier, dan backup.',
                      'Saat print/export laporan atau invoice.',
                      'Saat UAT mobile/tablet/laptop.'],
        'prepared_data': ['Halaman yang mau diuji.',
                          'Contoh data aman untuk klik simpan/print/export.',
                          'Screenshot jika ada field, modal, toast, tabel, atau print yang masih tidak rapi.'],
        'steps': ['Gunakan select/dropdown atomic untuk memilih data; original select tetap menjadi sumber submit.',
                  'Gunakan date picker/time picker atomic; perhatikan min/max date dan validasi required.',
                  'Gunakan show/hide password jika perlu mengecek input password.',
                  'Saat muncul modal konfirmasi aplikasi, baca aksi dan tekan Batal/Konfirmasi sesuai kebutuhan. Tidak ada lagi popup '
                  'browser native sebagai standar.',
                  'Perhatikan toast/flash tengah untuk sukses, error, warning, atau info setelah aksi.',
                  'Jangan klik tombol submit berulang; sistem sudah memberi loading dan menolak double submit.',
                  'Untuk tabel panjang, gunakan scroll horizontal yang tersedia; angka/uang sudah dirapikan agar mudah dibaca.',
                  'Saat print/export, tunggu status proses dan cek hasil print/save PDF.',
                  'Jika ada tampilan rusak spesifik halaman, catat URL, role, screenshot, ukuran layar, dan langkah reproduksi.'],
        'outputs': ['Input transaksi lebih konsisten dan mudah dibaca.',
                    'Konfirmasi aksi bahaya lebih jelas.',
                    'Notifikasi tidak lagi hilang di atas halaman.',
                    'Print/export lebih aman dan tabel tidak mudah kepotong.'],
        'journals': ['UI tidak membuat jurnal.',
                     'Jurnal tetap dibuat oleh flow bisnis backend: invoice, payment, procurement, payroll, HPP, warung, dan closing.'],
        'unposted': ['UI loading/confirm/toast bukan bukti jurnal sudah posting.',
                     'Tetap cek Akuntansi > Status Posting untuk status jurnal.'],
        'common_mistakes': ['Menganggap toast sukses sama dengan transaksi sudah diposting accounting. Toast hanya mengonfirmasi aksi '
                            'UI/backend berhasil.',
                            'Menutup halaman saat loading proses simpan/bayar/backup belum selesai.',
                            'Mengabaikan pesan error validasi di field atomic.',
                            'Mengira date picker custom mengubah format database. Field asli tetap format submit standar backend.'],
        'work_links': [{'label': 'Atomic Transaction Map', 'endpoint': 'settings.atomic_transaction_map', 'icon': 'bi-diagram-3'},
                       {'label': 'Audit Log', 'endpoint': 'settings.audit_logs', 'icon': 'bi-activity'}]}}


def _safe_url(endpoint):
    try:
        return url_for(endpoint)
    except (BuildError, RuntimeError):
        return "#"


ROLE_SOP_MAP = {
    "OWNER": ["owner"],
    "ADMIN": ["admin", "finance", "accounting", "canteen", "logistics", "hr", "master", "settings", "ui"],
    "ADMIN_OPERASIONAL": ["admin", "delivery"],
    "DAPUR": ["dapur"],
    "PENGANTAR": ["delivery"],
}


def _allowed_sop_slugs(user):
    if not user or not getattr(user, "is_authenticated", False):
        return []
    role = effective_role(getattr(user, "role", ""))
    return ROLE_SOP_MAP.get(role, [])


def _role_nav(allowed_slugs=None, active_slug=None):
    slugs = allowed_slugs if allowed_slugs is not None else ROLE_ORDER
    nav = []
    for slug in slugs:
        if slug in SOP_LIBRARY:
            item = SOP_LIBRARY[slug]
            nav.append({
                "slug": slug,
                "title": item["title"],
                "summary": item["summary"],
                "icon": item["icon"],
                "is_active": slug == active_slug,
                "url": url_for("sop.role_sop", slug=slug),
            })
    return nav




def _hydrate_safety_pages(pages):
    hydrated = []
    for page in pages or []:
        item = dict(page)
        item["url"] = _safe_url(item.get("endpoint"))
        hydrated.append(item)
    return hydrated

def _hydrate_sop(slug):
    sop = deepcopy(SOP_LIBRARY[slug])
    sop["slug"] = slug
    sop["url"] = url_for("sop.role_sop", slug=slug)
    for link in sop.get("work_links", []):
        link["url"] = _safe_url(link.get("endpoint"))
    return sop


@sop_bp.route("/")
@login_required
def index():
    allowed_slugs = _allowed_sop_slugs(current_user)
    if not allowed_slugs:
        abort(403)
    sop_items = [_hydrate_sop(slug) for slug in allowed_slugs if slug in SOP_LIBRARY]
    return render_template(
        "sop/index.html",
        sop_items=sop_items,
        role_nav=_role_nav(allowed_slugs),
        total_roles=len(sop_items),
    )


@sop_bp.route("/disaster-recovery")
@login_required
def disaster_recovery():
    role = effective_role(getattr(current_user, "role", ""))
    if role not in {"OWNER", "ADMIN"}:
        abort(403)
    allowed_slugs = _allowed_sop_slugs(current_user)
    sop = get_disaster_recovery_sop()
    sop["safety_pages"] = _hydrate_safety_pages(sop.get("safety_pages"))
    return render_template(
        "sop/disaster_recovery.html",
        sop=sop,
        role_nav=_role_nav(allowed_slugs),
    )


@sop_bp.route("/backup-restore")
@login_required
def backup_restore():
    role = effective_role(getattr(current_user, "role", ""))
    if role not in {"OWNER", "ADMIN"}:
        abort(403)
    allowed_slugs = _allowed_sop_slugs(current_user)
    sop = get_backup_restore_sop()
    sop["safety_pages"] = _hydrate_safety_pages(sop.get("safety_pages"))
    return render_template(
        "sop/backup_restore.html",
        sop=sop,
        role_nav=_role_nav(allowed_slugs),
    )


@sop_bp.route("/<slug>")
@login_required
def role_sop(slug):
    if slug not in SOP_LIBRARY:
        abort(404)
    allowed_slugs = _allowed_sop_slugs(current_user)
    if slug not in allowed_slugs:
        abort(403)

    template_name = "driver/sop.html" if current_user.role == "PENGANTAR" else (
        "ops/sop.html" if uses_ops_ui(current_user) else "sop/role_sop.html"
    )
    return render_template(
        template_name,
        sop=_hydrate_sop(slug),
        role_nav=_role_nav(allowed_slugs, active_slug=slug),
    )
