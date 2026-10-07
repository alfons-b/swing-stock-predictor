# swing-stock-predictor — AI Swing Stock Predictor BEI (cloud-first)

**Analytical decision support system** untuk swing trading saham Bursa Efek Indonesia. Sistem ini bukan sistem profit terjamin, dan tidak pernah berkata "pasti naik". Yang diberikannya adalah probabilitas, level entry/SL/TP, risk/reward, dan ukuran posisi. Sistem juga berani menjawab **NO TRADE**.

Seluruh pipeline berjalan di **GitHub Actions** dan menyimpan data ke **Supabase PostgreSQL**. **Laptop Anda tidak perlu hidup.** Laptop hanya dipakai untuk development, menjalankan test, dan membuka dashboard.

```
GitHub Actions (cron / Run workflow) ─► python main.py daily ─► Supabase PostgreSQL ◄─ Dashboard (web service terpisah)
        │                                   │
        │                                   ├─ data provider (Yahoo / IDX feed / CSV) + retry + fallback
        │                                   ├─ fitur → regime → sektor → setup → ML → risk → ranking
        │                                   └─ prediksi, sinyal, report, log, status run → database
        └─ job hidup hanya selama run: START → PROCESS → SAVE → EXIT
```

---

## 1. Menyiapkan production (sekali saja)

### 1.1 Buat repository GitHub dan push project

```bash
git init
git add .
git commit -m "swing-stock-predictor"
git branch -M main
git remote add origin https://github.com/<user>/swing-stock-predictor.git
git push -u origin main
```

Repository **privat** mendapat kuota menit GitHub Actions bulanan yang terbatas; repository publik gratis tanpa batas menit. Cek kuota akun Anda di *Settings → Billing*.

### 1.2 Buat project Supabase

1. Buka supabase.com, lalu buat **New project**. Simpan password database-nya.
2. Ambil connection string di **Connect → Connection string**. Pilih **Session pooler** (port 5432), bentuknya seperti ini:
   ```
   postgresql://postgres.<project-ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   Pakai **pooler**, bukan *direct connection*. Runner GitHub Actions hanya mendukung IPv4, sedangkan direct connection Supabase umumnya IPv6.
3. Skema tabel dibuat otomatis oleh `setup`/`daily` (migrasi idempoten). Bila ingin membuatnya manual, jalankan isi `sql/schema_postgres.sql` di **SQL Editor**.

### 1.3 Isi GitHub Secrets

Buka **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Wajib | Isi |
|---|---|---|
| `DATABASE_URL` | **Ya** | Connection string Session pooler dari langkah 1.2 |
| `SUPABASE_URL` | Tidak | Hanya bila `MODEL_STORAGE`/`REPORT_STORAGE` = `supabase` |
| `SUPABASE_KEY` | Tidak | *Service role key*, untuk Supabase Storage. Jangan pernah dipakai di dashboard publik |
| `MARKET_DATA_API_KEY` | Tidak | Hanya bila Anda punya feed data berlisensi (IDX) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` / `NOTIFY_WEBHOOK_URL` | Tidak | Notifikasi ringkasan harian |

Ada juga **Variables** (bukan secret) yang opsional: `PORTFOLIO_VALUE` (default `100000000`), `MODEL_STORAGE`, dan `REPORT_STORAGE` (default `auto`).

Secrets tidak pernah ditulis ke file, report, log, atau Docker image. Fungsi `describe()` database juga sengaja menyembunyikan user dan password.

### 1.4 Konfigurasi data provider

Default-nya **Yahoo Finance** (`config/sources.yaml`), dengan fallback ke CSV. Ada dua batasan yang perlu Anda ketahui:

- **Universe.** Yahoo tidak menyediakan daftar emiten BEI. Sistem mencoba endpoint publik situs BEI, yang sering diblokir dari IP datacenter. Bila gagal, sistem memakai `config/universe.csv`. File itu baru berisi beberapa kode saham besar sebagai **contoh**. **Ganti dengan daftar lengkap** hasil ekspor dari idx.co.id (*Data Pasar → Daftar Saham*). Kolom yang dipakai: `ticker,name,sector,subsector,listing_date,delisting_date,board`.
- **Emiten delisting.** Emiten yang sudah delisting biasanya hilang dari Yahoo, sehingga ada survivorship bias, dan validator akan memperingatkannya. Data berlisensi bisa dipakai lewat `IDXProvider` (siapkan `MARKET_DATA_API_KEY` dan implementasikan `_fetch_prices`), atau diekspor ke CSV standar untuk `CSVProvider`.

Isi juga `config/holidays.yaml` dengan hari libur bursa dari kalender resmi BEI. Sistem tidak mengarang tanggal libur. Selain itu, hari kerja tanpa data IHSG otomatis dipelajari sebagai hari non-bursa.

### 1.5 Jalankan test workflow

Buka **Actions → Tests → Run workflow**. Workflow ini menjalankan lint, lalu pytest dengan SQLite, lalu pytest dengan **PostgreSQL sungguhan** (service container). Workflow ini juga otomatis jalan di setiap push.

### 1.6 Initial setup (sekali)

Buka **Actions → Initial Setup → Run workflow**. Job ini akan:

1. migrasi database;
2. memuat universe;
3. mengunduh histori;
4. menjalankan validasi;
5. membangun fitur;
6. melakukan walk-forward dan perbandingan model;
7. menyimpan `model_v001` lalu menandainya **ACTIVE**;
8. menjalankan backtest awal.

Bila model pertama tidak lolos gerbang kualitas, model itu tetap diaktifkan sebagai **BASELINE** supaya daily bisa berjalan. Statusnya ditandai `MODEL STATUS: WARN` di health check, dan filter NO-TRADE tetap berlaku.

### 1.7 Verifikasi database

Jalankan `python main.py health` dari laptop dengan `DATABASE_URL` production. Cara lainnya, lihat tabel `pipeline_runs`, `price_history`, dan `model_versions` di Supabase Table Editor.

### 1.8 Aktifkan daily workflow

`daily.yml` sudah terjadwal **Senin–Jumat 18:30 WIB** (`cron: "30 11 * * 1-5"`, karena cron GitHub selalu memakai UTC). Pastikan workflow tidak dalam keadaan *disabled* di tab Actions. GitHub juga bisa menonaktifkan schedule pada repo yang tidak aktif selama 60 hari.

Untuk menjalankannya **kapan saja secara manual**: **Actions → Daily Market Pipeline → Run workflow**. Hal yang sama berlaku untuk *Weekly Backtest* dan *Model Retrain*.

### 1.9 Deploy dashboard (web service terpisah)

Daily job **tidak** menjalankan dashboard. Ada dua pilihan hosting:

- **Streamlit Community Cloud (gratis).**
  1. Buka *New app*, pilih repo ini, lalu isi *Main file path*: `dashboard/app.py`.
  2. Di *Advanced settings → Python requirements*, pakai `requirements-dashboard.txt`.
  3. Di *Secrets*, isi:
     ```toml
     DATABASE_URL = "postgresql://...pooler.supabase.com:5432/postgres"
     ```
  4. Sebaiknya buat user Postgres khusus yang **read-only** untuk dashboard.
- **Render / Railway / Fly.io / Cloud Run.** Pakai `Dockerfile.dashboard` (Render: `render.yaml`) dan set environment variable `DATABASE_URL`.

Halaman dashboard: Market Overview, Top Swing Stocks, Sector Strength, Stock Detail, Prediction History, Backtest, Model Performance, Pipeline Status, Data Health.

---

## 2. Development lokal

### Windows (PowerShell)

PowerShell 5.1 **tidak mendukung** `&&` dan `source`. Jalankan perintah satu per satu:

```powershell
cd C:\Users\<anda>\Desktop\swing-stock-predictor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Bila muncul error "running scripts is disabled", jalankan sekali:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt
Copy-Item .env.example .env
$env:YAHOO_ENABLED = "false"          # uji offline dengan data contoh
python main.py make-sample
python main.py setup
python main.py daily
python -m pytest -q
```

Proyek di dalam folder **OneDrive** bisa bentrok dengan file SQLite yang sedang disinkronkan. Bila muncul error "database is locked", pindahkan proyek ke luar OneDrive (misalnya `C:\dev\`).

### macOS / Linux

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
YAHOO_ENABLED=false python main.py make-sample
YAHOO_ENABLED=false python main.py setup
YAHOO_ENABLED=false python main.py daily
pytest -q
```

Variabel di `.env` **tidak** dibaca otomatis. Set lewat shell, atau jalankan `docker compose --profile job run job daily` yang membaca `.env`. Untuk development, default-nya adalah `sqlite:///data/local.db`.

### Perintah

| Perintah | Fungsi |
|---|---|
| `python main.py health [--json] [--no-provider]` | DATABASE, PROVIDER, UNIVERSE, tanggal pasar vs database, ACTIVE MODEL, LAST PIPELINE, DATA FRESHNESS |
| `python main.py setup` | Inisialisasi lengkap (§11). Idempoten |
| `python main.py daily [--skip-ingest]` | Pipeline harian penuh (§6) |
| `python main.py update-data [--actions]` | Unduh **hanya** data yang hilang, lalu validasi dan UPSERT |
| `python main.py validate-data` | Laporan kualitas data di database |
| `python main.py features` | Membangun fitur dari database |
| `python main.py train [--if-due]` | Retrain, bandingkan dengan model aktif, lalu promote atau reject |
| `python main.py backtest [--folds N]` | Walk-forward + track record sinyal live |
| `python main.py scan [--date]` / `predict BBCA` | Scan seluruh universe / analisis satu saham |
| `python main.py evaluate` | Evaluasi prediksi yang horizonnya sudah lewat |
| `python main.py models [--promote model_v00X]` | Daftar versi model / manual override |
| `python main.py db-schema` | Menulis `sql/schema_postgres.sql` |
| `--as-of YYYY-MM-DD` | Simulasi tanggal (untuk test dan backfill) |

Kode keluar (exit code):

| Kode | Arti |
|---|---|
| 0 | Sukses |
| 1 | Gagal; GitHub Actions menampilkan **FAILED** |
| 2 | Config salah |
| 3 | Health check kritis gagal |

---

## 3. Bagaimana sistem menjaga integritas

**Ingestion incremental (§10).**
- Untuk tiap emiten, sistem membandingkan *tanggal terakhir di database* dengan *tanggal bursa yang seharusnya sudah tersedia*. Tanggal itu dihitung dengan zona waktu Asia/Jakarta, bukan jam laptop atau runner.
- Hanya tanggal yang hilang yang diunduh. Run yang terlewat atau gagal otomatis dikejar pada run berikutnya, karena sistem tidak mengasumsikan run sebelumnya berhasil (§52).
- Penulisan ke database memakai **UPSERT idempoten** dengan `UNIQUE(stock_id, date)`.

**Retry & fallback (§22).**
- Exponential backoff per batch.
- Ticker yang gagal dicoba di provider berikutnya. Satu ticker gagal tidak membatalkan pipeline (status `PARTIAL_SUCCESS`).
- Bila lebih dari 50% ticker gagal, status menjadi `FAILED`.

**Split.** OHLC dari Yahoo disesuaikan split secara retroaktif. Bila harga pertama yang baru melonjak lebih dari 35% dibanding close terakhir di database, histori ticker itu **diunduh ulang** agar skala harga tidak tercampur.

**Survivorship.** Emiten yang hilang dari daftar ditandai `is_active = false` dan tidak pernah dihapus. Histori emiten delisting tetap di-backfill.

**Freshness (§23).** Status `UP_TO_DATE`, `UPDATE_REQUIRED`, `STALE`, atau `UNAVAILABLE`. Bila data STALE, semua BUY diturunkan menjadi WAIT dan headline menjadi `NO TRADE — data STALE`.

**Tanpa look-ahead (§31).** `tests/test_no_data_leakage.py` membuktikannya dengan dua cara:
- fitur dari data penuh sama dengan fitur dari data yang dipotong di tanggal t;
- mengubah data **setelah** t tidak mengubah fitur di t.

Test itu juga dibuktikan bisa gagal dengan menyuntikkan fitur yang bocor.

**Walk-forward rolling (§30).**
- Test = 6 bulan terbaru, tidak pernah dipakai untuk tuning atau seleksi model.
- Validasi = 4 fold × 6 bulan sebelumnya.
- Embargo sebesar horizon terpanjang di setiap batas fold.

**Kebijakan promosi model (§15).** Model kandidat hanya menjadi ACTIVE bila memenuhi semua syarat berikut:

| Syarat | Batas |
|---|---|
| AUC | ≥ 0,52 |
| Std AUC antar fold | ≤ 0,05 |
| ECE (kalibrasi) | ≤ 0,06 |
| Proxy trading positif | ≥ 50% fold |
| Log loss pada data **setelah** model aktif dilatih | Tidak lebih buruk dari model aktif |

Bila tidak memenuhi, status model menjadi **REJECTED** dan model lama tetap aktif. Setiap prediksi menyimpan `model_version`.

**Ambang probabilitas relatif.**
- Contoh konfigurasi di spesifikasi memakai `minimum_confidence: 0.65`, tetapi base rate bullish (return 5 hari > 3%) hanya sekitar 25%.
- Model 3-kelas yang terkalibrasi jujur hampir tidak pernah memberi angka sebesar itu, sehingga ambang absolut menghasilkan **nol trade**. Ini sudah terbukti di versi sebelumnya proyek ini.
- Karena itu, ambang default = base rate training + `MIN_PROB_EDGE`. Ambang absolut tetap bisa dipakai lewat `strategy.MIN_CONFIDENCE`.

---

## 4. Biaya & kapasitas

- **Tanpa server 24/7.** Daily job berjalan beberapa menit lalu selesai. Dashboard di Streamlit Community Cloud bisa gratis.
- **Storage Supabase (perkiraan kasar, verifikasi di dashboard Supabase).** `price_history` untuk ~900 emiten × 10 tahun ≈ 2,2 juta baris. Dengan index, ukurannya bisa mendekati batas paket gratis 500 MB. Untuk paket gratis, set `data.initial_history_years: 5`–`6`.
- **Tabel `features`** hanya menyimpan snapshot beberapa hari terakhir (`pipeline.features_snapshot_days`), karena fitur dihitung ulang dari harga.
- **Daily** hanya memuat sekitar 2 tahun terakhir (`scan_lookback_trading_days`). **Retrain** memuat seluruh histori dan jadwalnya mingguan, tetapi hanya benar-benar melatih bila model aktif sudah lebih tua dari `retrain_frequency_days` (30 hari).
- Daily, retrain, dan backtest memakai `concurrency: market-pipeline`, sehingga tidak pernah menulis database bersamaan.

---

## 5. Struktur proyek

```
.github/workflows/  daily.yml · model_retrain.yml · weekly_backtest.yml · tests.yml · setup.yml
app/
  data/          providers (Yahoo, IDX, CSV, ProviderChain), universe manager, ingestion, validator, cleaner
  database/      db.py (SQLite/PostgreSQL, UPSERT), schema.py (17 tabel, migrasi), repository.py
  features/      indikator & fitur teknikal (bebas look-ahead), fundamental/berita point-in-time
  market/        TradingCalendar (Asia/Jakarta), market regime, sector strength & relative strength
  models/        label, model factory, kalibrasi, ensemble, trainer, retrain + kebijakan promosi
  strategy/      setup detector, entry, stop loss, take profit, scoring, filter NO-TRADE, explain
  risk/          position sizing (lot BEI, batas risiko & likuiditas)
  scanner/       ranking & daily scanner, analisis per saham
  backtest/      engine (eksekusi konservatif), metrik, walk-forward, runner
  pipeline/      context (run tracking), jobs (daily/setup/...), health, freshness, evaluate
  storage/       ModelStorage & ReportStorage (local / database / Supabase Storage)
  reporting/     CSV, HTML, Markdown harian
  notifications/ Telegram / webhook (opsional)
dashboard/app.py    Streamlit (membaca database)
config/             app.yaml · sources.yaml · model.yaml · trading.yaml · holidays.yaml · universe.csv
tests/              test_database … test_daily_pipeline (lihat §57)
Dockerfile · Dockerfile.dashboard · docker-compose.yml · render.yaml · .env.example
```

---

## 6. Hasil uji lokal (data contoh SINTETIS — bukan BEI)

Hasil ini dijalankan dengan SQLite dan `make-sample` (45 ticker fiktif, 2017–2026). Angkanya hanya membuktikan bahwa pipeline bekerja dan jujur; angka ini **tidak** mengatakan apa pun tentang pasar Indonesia.

- **`update-data` ulang:** 44 emiten up-to-date, tidak ada yang diunduh ulang. Hanya emiten delisting (ZDEL) yang di-backfill (1.400 baris).
- **Retrain pertama:** RF + Logistic, AUC walk-forward 0,510. Model **ditolak gerbang** (< 0,52), lalu diaktifkan sebagai BASELINE dengan status `MODEL STATUS: WARN`.
- **Backtest (setelah biaya):**

| Periode | Strategi ML | Teknikal saja | IHSG buy & hold |
|---|---|---|---|
| Validasi Apr 2025–Apr 2026 | +0,2% (Sharpe 0,07, 99 trade) | +7,3% (Sharpe 0,51) | +17,8% (Sharpe 0,96) |
| Test Apr–Okt 2026 | +10,5% (Sharpe 1,72, 42 trade, PF 1,63) | +14,4% (Sharpe 1,65) | +3,7% (Sharpe 0,49) |

  Di kedua periode, lapisan ML **tidak** mengalahkan aturan teknikal saja. Lakukan perbandingan yang sama pada data BEI asli sebelum memercayai komponen ML.

- **Daily 2 Okt 2026:** regime STRONG_BEAR, sehingga hasilnya **NO HIGH-CONVICTION SETUP TODAY** dengan 5 saham di watchlist. Contoh report ada di `docs/examples/`.

---

## 7. Keterbatasan yang diketahui (dinyatakan terus terang)

- **Yahoo Finance** adalah sumber tidak resmi. Kualitas dan ketersediaannya bisa berubah sewaktu-waktu, data emiten delisting tidak tersedia, dan sektor memakai taksonomi Yahoo, bukan IDX-IC.
- **Batas ARA/ARB, papan pemantauan khusus (full call auction), dan spread bid-ask** belum dimodelkan di backtest.
- **Hari libur bursa** harus Anda isi sendiri di `config/holidays.yaml` dari kalender resmi BEI.
- **Hasil pada data contoh** (`make-sample`) bersifat **sintetis** dan tidak mencerminkan apa pun tentang BEI. Semua output dari data contoh diberi tanda peringatan.
- **Evaluasi strategi.** Pada versi riset sebelumnya, strategi teknikal-saja mengungguli lapisan ML di periode test. Selalu bandingkan keduanya di laporan backtest sebelum memercayai komponen ML.
