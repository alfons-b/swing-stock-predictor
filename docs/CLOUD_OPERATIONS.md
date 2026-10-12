# Operasi Cloud — GitHub Actions + Neon PostgreSQL

Semua proses produksi berjalan di **GitHub-hosted runners**. Hasilnya disimpan di **Neon PostgreSQL**.
Laptop hanya untuk menulis kode, menjalankan test, dan debugging. Laptop yang mati, sleep, atau offline tidak
menghentikan jadwal, **selama** workflow aktif di tab Actions, kuota GitHub Actions dan Neon tersedia, dan
layanan GitHub sendiri berjalan normal.

Tidak ada Windows Task Scheduler, cron lokal, atau proses Python yang harus hidup terus. Runner bersifat
sementara: semua yang perlu bertahan ditulis ke database, bukan ke filesystem runner, dan tidak di-commit ke
repo.

---

## 1. Membuat database Neon

Langkah ini harus Anda lakukan sendiri. Tidak ada akun atau layanan yang dibuat otomatis.

1. Daftar di [neon.com](https://neon.com) (paket Free, tanpa kartu).
2. **Buat project baru** khusus proyek ini, misalnya `swing-stock-predictor`. Jangan gunakan project atau database
   milik aplikasi lain.
   - **Postgres version:** 16 atau 17 (CI menguji di PostgreSQL 16).
   - **Region:** pilih yang dekat dengan runner GitHub Actions. Runner GitHub-hosted berjalan di Azure dan umumnya
     berada di Amerika Serikat; lokasinya tidak dijamin. *AWS US East* biasanya memberi latensi query terendah
     untuk job. *Asia Pacific (Singapore)* tetap bisa dipakai, tetapi setiap round-trip lebih lama, sehingga
     job sedikit lebih lambat.
3. Buka **Connect** dan pilih database dan role. Salin connection string **tanpa** `-pooler` di host
   (koneksi *direct*). Bentuknya:
   ```
   postgresql://<role>:<password>@ep-<nama>-<id>.<region>.aws.neon.tech/<database>?sslmode=require
   ```
   Kenapa direct, bukan pooled: setiap job membuka satu koneksi, dan `VACUUM` serta `SET SESSION` di maintenance
   butuh sesi utuh. Pooled (`-pooler`) tetap didukung untuk dashboard.
4. (Disarankan) Buat role **read-only** untuk dashboard:
   ```sql
   CREATE ROLE dashboard_ro LOGIN PASSWORD '<password-kuat>';
   GRANT CONNECT ON DATABASE <database> TO dashboard_ro;
   GRANT USAGE ON SCHEMA public TO dashboard_ro;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;
   ```
   Jalankan **setelah** workflow Initial Setup membuat tabel.

## 2. GitHub Secrets dan Variables

**Settings → Secrets and variables → Actions.**

| Nama | Jenis | Wajib | Isi |
|---|---|---|---|
| `DATABASE_URL` | Secret | **Ya** | connection string Neon direct dari §1.3 |
| `MARKET_DATA_API_KEY` | Secret | Tidak | feed harga berlisensi bila ada |
| `FUNDAMENTAL_API_KEY` | Secret | Tidak | feed fundamental berlisensi (point-in-time) |
| `FOREIGN_FLOW_API_URL`, `FOREIGN_FLOW_API_KEY` | Secret | Tidak | API foreign flow vendor |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTIFY_WEBHOOK_URL` | Secret | Tidak | notifikasi |
| `DB_SIZE_LIMIT_MB` | Variable | Tidak | kosongkan (otomatis 950 MB untuk Neon Free); isi hanya setelah upgrade |
| `PORTFOLIO_VALUE` | Variable | Tidak | default `100000000` |

`SUPABASE_URL` / `SUPABASE_KEY` tidak dipakai lagi. Hapus dari Secrets setelah migrasi (§7).

Secret tidak pernah dicetak:

- GitHub menyamarkan nilai secret di log;
- `describe()` hanya menampilkan host, tidak pernah user atau password;
- pesan error koneksi hanya memuat nama kelas exception.

## 3. Workflow

Semua workflow punya `workflow_dispatch` (tombol **Run workflow**), `timeout-minutes`, dan `concurrency`.
Workflow yang menulis data berbagi grup `market-pipeline`, sehingga tidak pernah menulis database bersamaan;
run berikutnya menunggu, tidak dibatalkan.

| Workflow | File | Jadwal (WIB) | Cron (UTC) | Tugas |
|---|---|---|---|---|
| Daily Market Pipeline | `daily.yml` | Sen–Jum 18:30 | `30 11 * * 1-5` | test → health → ingest incremental seluruh universe → validasi → fitur → scan → **cakupan per emiten** → riset → simpan → report |
| Database Health Check | `database_health_check.yml` | Sen–Jum 07:47 | `47 0 * * 1-5` | koneksi, provider, ukuran vs kuota, **uji tulis**; merah bila gagal |
| Fundamental Refresh | `fundamental_refresh.yml` | Sab 09:13 | `13 2 * * 6` | tuntaskan fundamental yang jatuh tempo + hitung ulang valuasi |
| Model Retrain | `model_retrain.yml` | Min 06:00 | `0 23 * * 6` | update data + cek corporate action; retrain hanya bila model > 30 hari; promosi hanya bila lolos gerbang |
| Weekly Backtest | `weekly_backtest.yml` | Min 08:00 | `0 1 * * 0` | walk-forward + track record live + evaluasi modul riset |
| Database Maintenance | `db_maintenance.yml` | tgl 1, 09:00 | `0 2 1 * *` | retensi + VACUUM (opsi dry-run / FULL) |
| Initial Setup | `setup.yml` | manual | — | migrasi, universe, histori 6 tahun, model awal, backtest |
| Tests | `tests.yml` | setiap push / PR | — | ruff (error nyata) + pytest di SQLite **dan** PostgreSQL 16 |

### Pemetaan ke workflow pada spesifikasi

| Spesifikasi | Implementasi | Alasan |
|---|---|---|
| `daily_market_scan.yml` | `daily.yml` | Nama lama dipertahankan agar riwayat run dan status enable/disable di GitHub tidak hilang. |
| `full_market_scan.yml` | `daily.yml` | Daily **sudah** memproses seluruh universe (962 emiten) dalam 8–17 menit, jauh di bawah timeout 120 menit. Checkpoint dan resume dipenuhi oleh ingestion incremental: titik awal tiap emiten dihitung dari isi database, jadi run ulang setelah gagal hanya mengunduh yang belum ada. Workflow terpisah dengan matrix batch baru diperlukan bila durasi mendekati batas (roadmap). |
| `fundamental_refresh.yml` | `fundamental_refresh.yml` | baru |
| `intraday_scan.yml` | — | **BLOCKED_BY_DATA**. Tidak ada sumber intraday yang layak. Workflow kosong tidak dibuat (KNOWN_LIMITATIONS §3). |
| `weekly_model_evaluation.yml` | `model_retrain.yml` + `weekly_backtest.yml` | Retrain membandingkan kandidat dengan model aktif di data yang belum dilihat; backtest mengevaluasi out-of-sample setelah biaya. |
| `manual_backtest.yml` | `weekly_backtest.yml` → Run workflow | Input `folds` tersedia. |
| `database_health_check.yml` | `database_health_check.yml` | baru |

### Zona waktu dan kalender

- Cron GitHub ditulis dalam **UTC**. WIB = UTC+7, dan Indonesia tidak memakai daylight saving, jadi konversinya
  tetap sepanjang tahun.
- Di dalam job, `TZ=Asia/Jakarta`. Tanggal bursa yang diharapkan dihitung `TradingCalendar` dengan zona
  `Asia/Jakarta`, `data_ready_time` 17:30, hari libur dari `config/holidays.yaml`, dan hari tanpa data IHSG
  yang dipelajari otomatis.
- **Jadwal tidak presisi, dan di repo ini terlambatnya besar.** Kelima run terjadwal yang tercatat hingga
  12 Oktober 2026 semuanya mulai jauh setelah jadwal. Cron tidak pernah berubah (`30 11 * * 1-5` sejak commit
  pertama):

  | Workflow | Jadwal (UTC) | Mulai sebenarnya (UTC) | Terlambat |
  |---|---|---|---|
  | Daily | 7 Okt 11:30 | 17:55 | ±6,4 jam |
  | Daily | 8 Okt 11:30 | 17:57 | ±6,5 jam |
  | Daily | 9 Okt 11:30 | 17:30 | ±6,0 jam |
  | Model Retrain | 10 Okt 23:00 | 11 Okt 01:30 | ±2,5 jam |
  | Weekly Backtest | 11 Okt 01:00 | 06:51 | ±5,9 jam |

  Artinya hasil "18:30 WIB" dalam praktik tersedia sekitar **00:30–01:00 WIB**. Untuk swing harian ini masih
  sebelum sesi berikutnya dibuka (09:00 WIB). Bila hasil dibutuhkan lebih cepat, jalankan Daily secara manual
  (Run workflow); manual dispatch di repo ini mulai dalam hitungan detik. Pipeline aman terhadap keterlambatan:
  ingestion mengejar tanggal yang tertinggal, dan data yang terlalu tua → status `STALE` → semua BUY diturunkan
  ke WAIT.
- Hindari jadwal di menit `:00` (paling ramai). Workflow baru memakai menit acak (`:47`, `:13`).

### Idempotensi, retry, dan pemulihan

| Mekanisme | Di mana |
|---|---|
| UPSERT dengan kunci unik (tidak ada duplikat bila run diulang) | `Database.upsert`, semua tabel |
| Retry provider dengan backoff, fallback antar-provider, satu ticker gagal tidak menghentikan run | `ProviderChain`, `run_ingestion` |
| Run gagal bila > 50% ticker gagal (`FAILED`), sebagian gagal → `PARTIAL_SUCCESS` | `jobs._ingest` |
| Cakupan < `coverage.min_coverage_pct` (80%) → `PARTIAL_SUCCESS` + peringatan | `jobs._record_coverage` |
| Retry koneksi database (cold start Neon) | `PostgresDatabase.connect` |
| Query baca langsung menutup transaksinya, sehingga tidak ada sesi *idle in transaction* selama komputasi panjang (Neon memutus sesi seperti itu; insiden Initial Setup 12 Okt 2026) | `Database._run(read=True)` |
| Koneksi yang diputus server dibuka ulang dan operasinya diulang **sekali**, hanya di luar `transaction()` | `Database._run` |
| Pemulihan storage penuh sebelum menulis | `jobs.ensure_writable` |
| Exit code: 0 sukses, 1 gagal, 2 config, 3 health kritis → GitHub menandai run merah | `main.py` |
| Notifikasi kegagalan | email GitHub bawaan untuk workflow gagal; Telegram/webhook opsional |

## 4. Kuota dan biaya

**Target operasi Rp0 dengan paket gratis selama batas mencukupi. Ini bukan janji gratis selamanya.**

| Layanan | Batas yang relevan (dicek 12 Okt 2026) | Pemakaian proyek (estimasi) |
|---|---|---|
| GitHub Actions, repo **publik**, runner standar | gratis; tidak ada batas menit yang dinyatakan | ±20–25 jam runner/bulan |
| GitHub Actions, repo **privat** (GitHub Free) | 2.000 menit/bulan; artifact 500 MB; cache 10 GB/repo | ±1.200–1.500 menit/bulan. **Mepet**: tiap workflow produksi juga menjalankan job Tests (±2–3 menit) |
| Neon Free | 1 GB storage, 100 CU-jam, 5 GB egress per project | lihat DATABASE_DECISION.md: ±3–22 CU-jam, ±500–600 MB |
| Yahoo Finance (via `yfinance`) | tidak resmi, tanpa SLA, batas request tidak dipublikasikan | 962 emiten per hari (batch 50) |
| Streamlit Community Cloud (dashboard) | gratis; app tidur bila tidak dibuka | — |
| API model AI | **tidak dipakai** | — |

Yang **akan** membutuhkan layanan berbayar bila diinginkan:

- data intraday real-time, order book, atau broker summary yang andal;
- feed fundamental point-in-time berlisensi;
- storage > 1 GB (Neon Launch);
- latensi rendah atau eksekusi tepat waktu, yang tidak bisa dijamin GitHub Actions.

Tidak ada layanan berbayar yang diaktifkan otomatis.

Risiko layanan gratis:

- **GitHub menonaktifkan workflow terjadwal di repo publik setelah 60 hari tanpa aktivitas repo**
  ([docs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)).
  Pantau email dari GitHub. Untuk mengaktifkan kembali: Actions → pilih workflow → *Enable workflow*, atau
  lakukan satu commit.
- Neon bisa mengubah kuota. Bila CU-jam atau egress habis, compute ditangguhkan sampai periode berikutnya;
  Database Health Check akan merah.
- Yahoo bisa memblokir atau mengubah API kapan saja. Provider chain akan jatuh ke provider berikutnya bila
  dikonfigurasi.

## 5. Monitoring

| Yang dipantau | Di mana |
|---|---|
| Status setiap run | tab Actions, dan tabel `pipeline_runs` (status, jumlah emiten, baris, ringkasan JSON termasuk cakupan) |
| Cakupan per emiten | tabel `scan_coverage`, report `scan_coverage_YYYYMMDD.csv`, dashboard → **Full-Market Coverage** |
| Kesehatan database | Database Health Check (harian), `python main.py health --strict` |
| Ukuran database | health `DATABASE SIZE`, workflow Database Maintenance, Neon Console → Usage |
| Provider data | tabel `data_sources`, dashboard → Data Health |
| Log penting | tabel `system_logs` (retensi 90 hari), log job di Actions |

## 6. Backup dan ekspor

Neon Free hanya menyimpan history 6 jam dan 1 snapshot manual.

- **Sebelum perubahan besar** (upgrade skema, retensi agresif): Neon Console → Backup & restore → buat snapshot
  manual.
- **Ekspor berkala data yang tidak bisa direkonstruksi** (`predictions`, `prediction_evaluations`,
  `trading_signals`, `model_versions` tanpa artifact, `backtest_runs`) dari laptop:
  ```bash
  pg_dump "$DATABASE_URL" --data-only -t predictions -t prediction_evaluations -t trading_signals \
          -t backtest_runs -t pipeline_runs -Fc -f swing_backup_$(date +%Y%m%d).dump
  ```
- Harga, IHSG, dan fitur bisa direkonstruksi dengan workflow Initial Setup.

## 7. Migrasi dari database lama (Supabase) ke Neon

Saat audit, workflow produksi repo ini masih menulis ke database yang ditunjuk secret `DATABASE_URL` lama
(Supabase menurut README sebelumnya).

**Pengaman:** di `APP_ENV=production`, sistem kini **menolak berjalan** bila `DATABASE_URL` menunjuk ke host
Supabase. Penolakan terjadi sebelum koneksi dan sebelum migrasi skema (`guard_production_database`, exit code 2).
Akibatnya, setelah perubahan ini masuk ke `main`, workflow produksi akan **merah dengan pesan jelas** sampai secret
diganti ke Neon. Ini disengaja, agar kode baru tidak pernah membuat tabel di project Supabase. Override sadar:
Variable/env `ALLOW_SUPABASE_DATABASE=true`.

Urutan yang disarankan, tanpa menyentuh Supabase:

1. Buat project Neon (§1).
2. Ganti secret `DATABASE_URL` dengan connection string Neon. Nilai lama tidak bisa dibaca lagi dari GitHub;
   simpan sendiri bila masih perlu.
3. Actions → **Initial Setup** → Run workflow. Ini membuat skema, memuat universe, mengunduh 6 tahun histori, dan
   melatih model awal (±10–20 menit).
4. Actions → **Database Health Check** → Run workflow. Harus hijau, termasuk `DATABASE WRITE: OK` dan
   `DATABASE PROVIDER: OK (neon …)`.
5. Actions → **Daily Market Pipeline** → Run workflow. Periksa ringkasan run dan `Cakupan: …`.
6. Hapus secret `SUPABASE_URL` / `SUPABASE_KEY` bila ada.

Riwayat prediksi sejak run pertama (7 Oktober 2026) **tidak** ikut pindah; prediksi baru mulai dari nol. Bila
ingin membawanya, Anda sendiri yang memutuskan dan menjalankan `pg_dump --data-only` dari database lama lalu
`pg_restore` ke Neon setelah Initial Setup. Itu operasi baca pada database lama. Tabel proyek ini di Supabase
tidak dihapus oleh kode mana pun; membersihkannya adalah keputusan Anda.

## 8. Dashboard

Dashboard tidak berjalan di GitHub Actions. Dashboard adalah web service terpisah yang hanya membaca database.

- **Streamlit Community Cloud** (gratis): main file `dashboard/app.py`, requirements `requirements-dashboard.txt`,
  Secrets `DATABASE_URL = "<connection string role dashboard_ro>"`.
- Alternatif: Render web service (`render.yaml`, `Dockerfile.dashboard`). Render **web service** gratis berbeda dari
  Render PostgreSQL gratis yang kedaluwarsa; yang ditolak di DATABASE_DECISION.md adalah databasenya.

## 9. Pemeriksaan lokal (opsional, dari laptop)

```bash
export DATABASE_URL='postgresql://...neon.tech/...?...'
python main.py health --no-provider --strict   # koneksi, provider, ukuran, uji tulis
python main.py db-maintenance --dry-run        # apa yang akan dihapus retensi
```
