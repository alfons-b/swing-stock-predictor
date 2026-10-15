# Roadmap Implementasi

Dokumen ini berbasis audit repo pada **12 Oktober 2026** (commit `e64ce21`). Repo **tidak** dibangun ulang: kode
yang sudah ada matang (204 file, 152 test lulus, semua workflow produksi hijau di GitHub Actions), jadi setiap fase
memperluas kode tersebut secara bertahap.

## Hasil audit singkat

| Area | Kondisi saat audit |
|---|---|
| Bahasa / versi | Python (CI 3.12; diuji juga di 3.13), pandas, NumPy, scikit-learn, psycopg 3, yfinance; LightGBM/XGBoost/CatBoost opsional |
| Database | Lapisan DB-API tipis, SQLite (dev/test) + PostgreSQL (produksi). **Produksi menunjuk ke Supabase.** 21 tabel, migrasi additive |
| Universe | 962 emiten dari file Daftar Saham BEI (`config/universe.xlsx`) |
| Data | Yahoo (harga, IHSG, CA, fundamental snapshot). Foreign flow dan broker: antarmuka ada, tanpa sumber |
| Model | Walk-forward, kalibrasi, ensemble, gerbang promosi, registry versi di database |
| Workflow | daily, setup, model_retrain, weekly_backtest, db_maintenance, tests. Semua hijau. Run terjadwal teramati terlambat 2,5–6,5 jam |
| Dashboard | Streamlit, 13 halaman, membaca database |
| Test | 152 lulus (1 dilewati: butuh PostgreSQL) |
| Dokumentasi | README rinci; folder `docs/` tidak ada (README merujuk `docs/RESEARCH_MODULES.md` yang hilang) |
| Masalah | Ketergantungan Supabase (docs, workflow, default 500 MB); `db_maintenance.yml` memaksa batas 500 MB; tidak ada status cakupan per emiten; emiten papan Pemantauan Khusus bisa mendapat BUY; kode legacy SQLAlchemy/Typer yang tidak bisa dijalankan |

## Status fase

| Fase | Isi | Status |
|---|---|---|
| 1 | Audit repo | **Selesai** (sesi ini) |
| 2 | Evaluasi database gratis, keputusan | **Selesai**: Neon ([DATABASE_DECISION.md](DATABASE_DECISION.md)) |
| 3 | Konfigurasi database dan migrasi aman | **Kode selesai**: profil provider, SSL, retry cold start, batas otomatis, pemulihan sebelum penulisan diblokir, uji tulis, skema v4 additive. **Menunggu pengguna:** membuat project Neon + secret, lalu Initial Setup (CLOUD_OPERATIONS §7) |
| 4 | Universe manager dan full-market scanner | **Selesai untuk cakupan**: status per emiten (6 status), tabel `scan_coverage`, gerbang BUY, report CSV/MD, halaman dashboard, ambang cakupan 80%. Universe dinamis dari sumber resmi otomatis: BLOCKED (endpoint BEI memblokir datacenter) |
| 5 | Data providers dan data quality | Sebagian besar sudah ada sebelumnya. Sisa: label `data_quality_score` per emiten (turunan dari status cakupan + validator) |
| 6 | Swing scanner dan risk engine | Sudah ada sebelumnya (TESTED). Sisa: evaluasi setup per strategi secara terpisah (hipotesis, out-of-sample per setup) |
| 7 | Fundamental, valuasi, undervaluation | Sudah ada sebelumnya (TESTED). Sisa: data point-in-time (BLOCKED_BY_DATA tanpa feed) |
| 8 | Foreign flow dan akumulasi | Logika sudah ada. Sisa: pemetaan status ke `ACCUMULATION_EVIDENCE` / `DISTRIBUTION_EVIDENCE` / `MIXED_EVIDENCE` / `INSUFFICIENT_DATA`; sumber foreign flow (keputusan pengguna) |
| 9 | Backtesting | Sudah ada sebelumnya (TESTED). Sisa: ARA/ARB, spread, stabilitas lintas rezim dalam satu laporan |
| 10 | ML dan evaluasi model | Sudah ada sebelumnya. Sisa: laporan pembanding ML vs aturan teknikal saja dari data produksi BEI |
| 11 | Scalping | **BLOCKED_BY_DATA** ([KNOWN_LIMITATIONS §3](KNOWN_LIMITATIONS.md)) |
| 12 | Dashboard dan CSV | Ditambah halaman *Full-Market Coverage* + unduh CSV. Sisa: halaman Backtest Lab interaktif, Portfolio & Risk |
| 13 | GitHub Actions scheduler | Ditambah `database_health_check.yml`, `fundamental_refresh.yml`; Supabase dihapus dari env workflow; batas ukuran tidak lagi dipaksa 500 MB |
| 14 | Paper trading, monitoring, validasi akhir | Belum |

### Alasan urutan

Fase 3 dan 4 dikerjakan lebih dulu karena keduanya prasyarat semua fase lain. Tanpa database yang benar, tidak
ada yang persisten. Tanpa status cakupan, skor dari data cacat tidak bisa dibedakan dari skor valid
(kriteria penerimaan 5, 6, 7). Fase 6–10 sebagian besar sudah ada di repo, sehingga nilai tambah terbesar
berikutnya adalah pada data dan evaluasi, bukan menulis ulang strategi.

## Perubahan sesi ini

| Berkas | Perubahan |
|---|---|
| `app/database/providers.py` (baru) | deteksi Neon/Aiven/Supabase/lainnya, batas ukuran efektif, `sslmode=require`, retry |
| `app/database/db.py` | `PostgresDatabase` memakai profil provider; `describe()` menampilkan provider tanpa kredensial |
| `app/database/maintenance.py` | batas ukuran `auto` per provider; ukuran melaporkan provider; retensi `scan_coverage` |
| `app/database/schema.py` | tabel `scan_coverage`, skema v4 |
| `app/database/repository.py` | `save_coverage`, `coverage` |
| `app/scanner/coverage.py` (baru) | status cakupan, ringkasan, gerbang BUY, CSV, Markdown |
| `app/scanner/scanner.py` | `scan_day(..., coverage=)` menerapkan gerbang sebelum ranking |
| `app/pipeline/jobs.py` | cakupan di daily, scan, dan predict; pemulihan storage pada rasio ≥ 95% |
| `app/pipeline/context.py` | `guard_production_database`: produksi menolak host Supabase sebelum koneksi atau migrasi |
| `app/pipeline/health.py` | `DATABASE PROVIDER`, `write_probe`, `strict_failures` |
| `main.py` | `health --strict` (uji tulis); ringkasan cakupan di output daily |
| `dashboard/app.py` | halaman Full-Market Coverage; tidak membaca secret Supabase |
| `config/app.yaml` | `size_limit_mb: auto`, `coverage.*`, `retention.scan_coverage_days` |
| workflow | 2 baru; env Supabase dihapus; `DB_SIZE_LIMIT_MB` diteruskan tanpa default paksa |
| test | `test_database_providers.py` (19), `test_scan_coverage.py` (11) |

Hasil: **182 test lulus, 1 dilewati** (PostgreSQL; berjalan di CI).

## Model challenger (15 Okt 2026)

Empat model challenger diimplementasikan tanpa mengubah model aktif: LSTM, GRU, ARIMA-GARCH, dan TFT. Detailnya di
[CHALLENGER_MODELS.md](CHALLENGER_MODELS.md). Status `TESTED` di CI dengan torch, statsmodels, dan arch asli, termasuk
training end-to-end pada data contoh dan test train/serve skew. Run produksi pertama: Actions → Challenger Train.

## Instruksi untuk sesi berikutnya

1. **Pengguna:** ikuti CLOUD_OPERATIONS §7 (Neon → secret → Initial Setup → Database Health Check → Daily).
   Ganti secret **sebelum atau bersamaan** dengan merge: setelah merge, produksi menolak berjalan terhadap Supabase.
   Laporkan hasilnya: ringkasan run, baris `Cakupan: …`, dan output health.
2. Verifikasi di run produksi pertama: distribusi status cakupan (berapa STALE/EXCLUDED/INSUFFICIENT dari 962),
   durasi daily di Neon, dan CU-jam di Neon Console.
3. Fase 1b (PR kecil): hapus kode legacy SQLAlchemy/Typer yang tercantum di ARCHITECTURE.md.
4. Fase 8: pemetaan status akumulasi ke label spesifikasi + test.
5. Fase 10: laporan pembanding ML vs teknikal-saja vs IHSG dari data BEI produksi, per rezim; promosikan ML
   hanya bila konsisten lebih baik setelah biaya.
6. Fase 6/9: backtest per setup (hipotesis, entry/exit, out-of-sample) dan pemodelan ARA/ARB.
7. Pertimbangkan workflow keep-alive untuk mencegah penonaktifan otomatis 60 hari (tanpa commit hasil scan ke repo).

Cara menjalankan test lokal:

```bash
pip install -r requirements.txt
YAHOO_ENABLED=false pytest -q            # SQLite
TEST_POSTGRES_URL=postgresql://... pytest -q   # tambah jalur PostgreSQL
```
