# Sumber Data

Prinsip: **tidak ada data yang dikarang.** Data yang tidak tersedia diberi label (`UNAVAILABLE`,
`INSUFFICIENT_DATA`, `FOREIGN_FLOW_UNAVAILABLE`, …) dan tidak diisi nol. Setiap provider berada di belakang
antarmuka, jadi sumber bisa diganti tanpa mengubah strategi.

## Ringkasan

| Data | Sumber aktif | Status | Antarmuka |
|---|---|---|---|
| Daftar emiten (universe) | `config/universe.xlsx` = file **Daftar Saham** unduhan idx.co.id (962 emiten, commit di repo) | **Berfungsi**; diperbarui manual | `app/data/universe.py`, `universe_file.py` |
| Harga harian OHLCV + IHSG | Yahoo Finance (`BBCA.JK`, `^JKSE`) via `yfinance` | **Berfungsi**; tidak resmi | `app/data/providers/yahoo_provider.py`, `ProviderChain` |
| Corporate action (split, dividen) | Yahoo | Berfungsi; cakupan BEI tidak dijamin lengkap | `ingest_actions` |
| Sektor | Yahoo (taksonomi Yahoo, ±40 emiten per run) atau `config/sectors.csv` | Parsial | `universe.sectors_file` |
| Laporan keuangan | Yahoo (snapshot terbaru, bukan point-in-time); CSV kanonik; feed berlisensi | Parsial | `app/valuation/fundamental_provider.py` |
| Foreign flow | File *Ringkasan Saham* BEI (manual), CSV vendor, API vendor | **Tidak ada sumber aktif** → `FOREIGN_FLOW_UNAVAILABLE` | `app/flows/foreign_flow_provider.py` |
| Broker summary | Vendor berlisensi | **Tidak ada** → `BROKER_SUMMARY_UNAVAILABLE` | `app/accumulation/broker_flow.py` |
| Intraday OHLCV / bid-ask / order book | — | **BLOCKED_BY_DATA** | belum ada |
| Kurs (laporan non-IDR) | `data/raw/fx/fx_rates.csv` | opsional | `fundamentals.fx_file` |
| Hari libur bursa | `config/holidays.yaml` (isi dari kalender resmi BEI) + belajar dari hari tanpa IHSG | Berfungsi | `app/market/calendar.py` |

## Detail dan keterbatasan per sumber

### Universe

- Endpoint publik BEI (`GetSecuritiesStock`) dicoba lebih dulu. Endpoint ini **hampir selalu diblokir** dari IP
  datacenter seperti runner GitHub Actions. Sumber yang andal adalah file Daftar Saham yang di-commit.
- Emiten yang hilang dari daftar ditandai `is_active = false`; histori tidak dihapus. Deaktivasi massal
  (daftar baru < 50% jumlah aktif) ditunda karena kemungkinan file terpotong.
- Perubahan kode emiten: `config/ticker_changes.yaml`.
- Saat audit, file berisi 962 emiten: Pengembangan 556, Utama 293, **Pemantauan Khusus 68**, Akselerasi 44,
  Ekonomi Baru 1. Papan Pemantauan Khusus (full call auction) di-`EXCLUDED` dari sinyal (lihat `coverage.excluded_boards`).
- **Keterbatasan:** daftar diperbarui manual. IPO baru tidak terlihat sampai file diganti. Tidak ada histori
  universe point-in-time sebelum sistem mulai mencatat (`first_seen`), sehingga backtest lampau terpapar
  survivorship bias (KNOWN_LIMITATIONS §1).

### Harga harian (Yahoo Finance)

- Sumber **tidak resmi**: tanpa SLA, tanpa lisensi redistribusi, format dan ketersediaan bisa berubah.
- Harga di-*adjust* split secara retroaktif. Sistem mendeteksi lonjakan > 35% vs close terakhir di DB lalu
  mengunduh ulang histori ticker tersebut agar skala tidak tercampur.
- Emiten yang sudah delisting tidak tersedia → survivorship bias.
- Ingestion incremental per emiten (hanya tanggal yang hilang), validasi baris (OHLC > 0, high ≥ low,
  volume ≥ 0), lalu UPSERT `UNIQUE(stock_id, date)`.
- Alternatif berlisensi: `IDXProvider` (implementasikan `_fetch_prices`, secret `MARKET_DATA_API_KEY`) atau
  ekspor CSV standar untuk `CSVProvider`.

### Fundamental

Urutan provider (`config/research.yaml → fundamentals.providers`):

1. `idx_fundamentals`: feed berlisensi point-in-time; tidak aktif tanpa kredensial.
2. `csv_fundamentals`: file kanonik di `data/raw/fundamentals` (template: `python main.py fundamentals-template`).
3. `yahoo_fundamentals`: snapshot ±4 tahun + ±5 kuartal terakhir, **tanpa tanggal publikasi** dan bisa berisi
   angka restated. `first_known_date` = tanggal sistem mengambilnya. Aman untuk penggunaan live, **tidak sah**
   untuk backtest masa lalu.

Laporan tidak pernah dihapus (histori point-in-time dan restatement). Estimasi tanggal publikasi
(`ESTIMATED_PIT`) hanya untuk riset dan diberi label.

### Foreign flow

- BEI mempublikasikan foreign buy/sell harian per emiten dalam **lembar** di *Ringkasan Saham*. Tidak ada API
  publik resmi, dan situs memblokir akses otomatis dari datacenter. Sistem **sengaja tidak** melakukan scraping.
- Cara mengaktifkan: unduh file Ringkasan Saham per hari ke `data/raw/foreign_flow/` (tanggal di nama file),
  sediakan CSV vendor, atau isi secret API vendor.
- **Perhatian untuk repo publik:** `data/raw/README.md` menyarankan commit file ke repo *privat*. Repo ini
  **publik**, jadi meng-commit file data BEI atau vendor bisa melanggar ketentuan penggunaan sumbernya. Periksa
  ketentuan sebelum meng-commit.

### Intraday

Belum ada sumber. Yahoo menyediakan bar intraday dengan riwayat pendek dan tidak real-time (batas persisnya belum
diverifikasi di sesi ini). Itu tidak cukup untuk backtest scalping yang realistis: tidak ada bid-ask, order book,
atau trade-by-trade. Lihat KNOWN_LIMITATIONS §3.

## Fitur yang membutuhkan data eksternal

| Fitur | Data yang dibutuhkan | Status tanpa data |
|---|---|---|
| Valuasi point-in-time untuk backtest | feed fundamental dengan tanggal publikasi asli | live saja; backtest valuasi `INSUFFICIENT_HISTORY` |
| Skor foreign flow | Ringkasan Saham harian / vendor | `FOREIGN_FLOW_UNAVAILABLE`, tidak ikut skor |
| Akumulasi berbasis broker | broker summary vendor | indikator berbasis harga-volume saja (OBV, ADL, CMF, MFI) |
| Scalping | intraday + bid-ask/order book | `BLOCKED_BY_DATA` |
| Backtest bebas survivorship | harga emiten delisting + universe historis | dibatasi; diperingatkan validator |
