# Keterbatasan yang Diketahui

Sistem ini adalah **alat riset dan pendukung keputusan**, bukan sistem profit terjamin. Tidak ada klaim
akurasi, profit, atau kesetaraan dengan hedge fund yang sudah dibuktikan. Semua hasil uji lokal memakai data
**sintetis** (`make-sample`), sehingga tidak mengatakan apa pun tentang pasar Indonesia.

## 1. Data harga dan universe

- **Yahoo Finance tidak resmi**: tanpa SLA, tanpa lisensi, bisa berubah atau diblokir kapan saja.
- **Survivorship bias.** Yahoo tidak menyediakan emiten yang sudah delisting, dan universe historis sebelum
  sistem mulai berjalan tidak tersedia. Backtest masa lalu karena itu terlalu optimistis dalam derajat yang
  tidak diketahui. Validator memberi peringatan.
- Universe diperbarui manual dari file Daftar Saham BEI. IPO baru tidak otomatis masuk.
- Sektor memakai taksonomi Yahoo, bukan IDX-IC, kecuali `config/sectors.csv` disediakan.
- Hari libur bursa harus diisi manual di `config/holidays.yaml`; sistem juga belajar dari hari tanpa data IHSG.

## 2. Eksekusi dan biaya

- Backtest sudah memasukkan fee beli 0,15%, fee jual 0,25%, slippage 10 bps, tick BEI, lot 100, limit order t+1,
  gap pada stop, dan stop-first bila SL dan TP tersentuh di candle yang sama.
- **Belum dimodelkan:** batas ARA/ARB (antrean tidak terisi), spread bid-ask aktual, risiko order tidak terisi
  di luar sentuhan harga, dan dampak harga (market impact) di atas batas `MAX_POSITION_PCT_OF_ADV`.
- Papan Pemantauan Khusus (full call auction) tidak dimodelkan. Karena itu sejak sesi ini emiten di papan
  tersebut berstatus `EXCLUDED` dan tidak pernah mendapat BUY (`coverage.excluded_boards`). Pengecualian ini
  hanya berlaku di scan live. Backtest belum menerapkannya, karena papan pencatatan hanya diketahui per hari ini,
  bukan historis. Akibatnya backtest dan live sedikit berbeda.

## 3. Scalping dan intraday — `BLOCKED_BY_DATA`

- Tidak ada sumber intraday, bid-ask, order book, atau trade-by-trade yang layak dan gratis.
- **GitHub Actions tidak cocok untuk eksekusi intraday.** Run terjadwal di repo ini teramati terlambat
  2,5–6,5 jam (lihat CLOUD_OPERATIONS §3), dan interval minimum cron adalah 5 menit. Sinyal scalping dari
  scheduler ini akan basi sebelum bisa dipakai.
- Storage Neon Free (1 GB) tidak cukup untuk bar intraday seluruh universe dalam jangka panjang
  (±11 juta baris/tahun untuk bar 5 menit).
- Yang realistis tanpa data berbayar: **riset intraday end-of-day** pada subset likuid (fitur seperti VWAP
  distance, rentang intraday, relative volume intraday), dihitung setelah penutupan dan disimpan sebagai agregat
  harian, dengan label `DATA_LIMITED`. Ini **bukan** scalping real-time dan tidak boleh disebut teruji untuk
  scalping. Order-book imbalance dan trade imbalance tidak bisa dihitung sama sekali tanpa data tersebut.

## 4. Fundamental dan valuasi

- Tanpa feed point-in-time, fundamental berasal dari snapshot Yahoo yang hanya sah sejak tanggal diambil.
  Backtest valuasi untuk periode lampau berstatus `INSUFFICIENT_HISTORY`.
- Angka Yahoo bisa restated, dan cakupan emiten kecil BEI tidak lengkap.
- Asumsi valuasi (risk-free 6,8%, ERP 7,5%, dsb. di `config/research.yaml`) harus ditinjau manual. Health check
  memberi WARN bila lebih dari 180 hari.

## 5. Foreign flow dan broker

- Tidak ada sumber aktif → `FOREIGN_FLOW_UNAVAILABLE`, tidak ikut skor (bukan dianggap nol).
- Broker summary hanya antarmuka; datanya membutuhkan vendor berlisensi.
- Indikator akumulasi berbasis harga-volume (OBV, ADL, CMF, MFI) adalah **perkiraan**, bukan bukti transaksi
  aktual. Status di repo memakai label `STRONG/MODERATE_ACCUMULATION_SIGNAL`, `EARLY_ACCUMULATION_WATCHLIST`,
  dan `STRONG/MODERATE_DISTRIBUTION_SIGNAL`. Label spesifikasi (`ACCUMULATION_EVIDENCE`, `MIXED_EVIDENCE`, …)
  belum dipetakan (roadmap Fase 8).

## 6. Model dan strategi

- Pada data sintetis, lapisan ML tidak mengungguli aturan teknikal saja (README §6). Ini **belum** diuji
  pada data BEI asli dengan pembanding yang sama. Jangan menjadikan ML penentu utama sebelum perbandingan itu
  dilakukan dan dipublikasikan dari run produksi.
- Status model produksi saat audit tidak bisa dilihat dari sandbox (log run GitHub tidak dapat diunduh). Bila
  model pertama gagal gerbang promosi, sistem mengaktifkannya sebagai BASELINE dan health check menampilkan
  `MODEL STATUS: WARN`. Periksa itu setelah Initial Setup di Neon.
- Long-term engine belum punya horizon, label, dan backtest jangka panjang sendiri; yang ada adalah valuasi
  dan ranking.
- Skor `scalping_score`, `risk_score`, dan `data_quality_score` dari spesifikasi belum ada sebagai kolom
  tersendiri. Kualitas data kini tercermin di status cakupan per emiten.

## 7. Operasional cloud

- Jadwal GitHub Actions tidak presisi dan di repo ini terlambat berjam-jam (CLOUD_OPERATIONS §3).
- **Workflow terjadwal di repo publik dinonaktifkan GitHub setelah 60 hari tanpa aktivitas repo.**
- Neon Free: backup terbatas (history 6 jam, 1 snapshot manual). Riwayat prediksi tidak bisa direkonstruksi
  bila hilang; ekspor berkala (CLOUD_OPERATIONS §6).
- Repo privat akan memakan sebagian besar 2.000 menit gratis per bulan.

## 8. Verifikasi di sesi ini

- Test dijalankan dengan `unittest` dan shim `pytest` minimal, karena akses ke pypi.org diblokir di sandbox
  pengembangan. CI GitHub (`tests.yml`) memakai pytest asli.
- Jalur PostgreSQL tidak bisa dijalankan di sandbox (driver `psycopg` tidak bisa dipasang). Jalur ini **lulus**
  di CI GitHub (job `pytest` dengan service PostgreSQL 16) untuk commit PR #1.
- Koneksi ke Neon belum diverifikasi karena database belum dibuat. Klaim "berjalan di Neon" baru sah setelah
  Database Health Check hijau di GitHub Actions (CLOUD_OPERATIONS §7).
- `docs/RESEARCH_MODULES.md` dan `docs/examples/` dirujuk README lama tetapi tidak ada di repo.
