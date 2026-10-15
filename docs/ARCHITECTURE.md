# Arsitektur

## Alur produksi

```
GitHub Actions (cron UTC / Run workflow)               ← tidak ada proses di laptop
  └─ python main.py <job>   (START → PROCESS → SAVE → EXIT)
       ├─ Universe Manager ──────── config/universe.xlsx (Daftar Saham BEI) → stocks
       ├─ Market Data Provider ──── ProviderChain: Yahoo → IDX (berlisensi) → CSV, retry + fallback
       ├─ Data Quality ──────────── validasi baris → cleaner (CA, suspensi) → freshness → CAKUPAN per emiten
       ├─ Feature Engineering ───── teknikal, regime, sektor, relative strength, likuiditas (bebas look-ahead)
       ├─ Strategy Engines ──────── swing setups · valuasi · foreign flow · akumulasi/distribusi
       ├─ ML Engine ─────────────── model aktif (walk-forward, kalibrasi, gerbang promosi)
       ├─ Risk & Ranking ────────── filter NO-TRADE, sizing lot BEI, konsentrasi sektor/korelasi, ranking
       └─ Persist ───────────────── Neon PostgreSQL (UPSERT idempoten) + report CSV/HTML/MD di tabel `reports`
Dashboard (Streamlit, web service terpisah) ── baca-saja dari database
```

Desain database: lapisan tipis DB-API (`app/database/db.py`; sqlite3 untuk dev/test, psycopg 3 untuk PostgreSQL),
bukan ORM. Semua akses tabel lewat `app/database/repository.py`. Skema didefinisikan sekali
(`app/database/schema.py`) dan dimigrasi secara additive. Profil provider (Neon/Aiven/Supabase) ada di
`app/database/providers.py`.

Entry point satu-satunya adalah `main.py` (argparse). Lihat "Kode legacy" di bawah.

## Peta modul dan status

Status:

- `TESTED`: diimplementasikan dan dicakup test otomatis.
- `IMPLEMENTED`: kode ada, tetapi verifikasi bergantung pada lingkungan luar (GitHub, database cloud).
- `PARTIALLY_IMPLEMENTED`: sebagian dari spesifikasi.
- `BLOCKED_BY_DATA`: tidak bisa dibangun atau diuji jujur tanpa data yang belum tersedia.

| # | Modul (spesifikasi) | Lokasi | Status | Test |
|---|---|---|---|---|
| 1 | Universe Manager | `app/data/universe.py`, `universe_file.py`, `tickers.py` | TESTED | `test_universe_file` |
| 2 | Market Data Provider | `app/data/providers/` (`base`, `chain`, `yahoo`, `idx`, `csv`) | TESTED | `test_provider`, `test_provider_contract`, `test_incremental_update` |
| 3 | Data Quality Engine | `app/data/validator.py`, `cleaner.py`, `ingestion.validate_new_rows`, `pipeline/freshness.py`, **`scanner/coverage.py`** | TESTED | `test_data_validation`, `test_upsert`, **`test_scan_coverage`** |
| 4 | Fundamental Engine | `app/valuation/fundamental_provider.py`, `financial_statement_normalizer.py` | PARTIALLY_IMPLEMENTED: kode lengkap; data point-in-time tidak ada | `test_valuation` |
| 5 | Technical Engine | `app/features/` | TESTED | `test_feature_engineering`, `test_no_data_leakage` |
| 6 | Foreign Flow Engine | `app/flows/` | TESTED (logika); BLOCKED_BY_DATA di produksi | `test_flows_accumulation` |
| 7 | Accumulation/Distribution | `app/accumulation/` | TESTED (OBV/ADL/CMF/MFI/RVOL/VWAP); broker summary BLOCKED_BY_DATA | `test_flows_accumulation` |
| 8 | Valuation Engine | `app/valuation/` (DCF, relative, historical, dividend, justified P/B; bobot per tipe sektor; skenario; margin of safety; value trap) | TESTED | `test_valuation`, `test_research` |
| 9 | Scalping Engine | — | BLOCKED_BY_DATA | — |
| 10 | Swing Engine | `app/strategy/` (setup: BREAKOUT, BREAKOUT_VOLUME, BASE_BREAKOUT, VCP_BREAKOUT, PULLBACK_UPTREND, SUPPORT_BOUNCE, TREND/MOMENTUM_CONTINUATION, HH_HL), `scanner/` | TESTED | `test_stop_loss`, `test_take_profit`, `test_risk_reward`, `test_target_generation` |
| 11 | Long-Term Engine | valuasi + skor kualitas + ranking `best_value` / `quality_value` | PARTIALLY_IMPLEMENTED: belum ada horizon, label, dan backtest jangka panjang tersendiri | `test_research` |
| 12 | ML Engine | `app/models/` (logistic, RF, HistGBM, LightGBM/XGBoost/CatBoost bila terpasang; kalibrasi; ensemble; gerbang promosi) | TESTED | `test_model`, `test_probability`, `test_no_data_leakage` |
| 13 | Backtesting Engine | `app/backtest/` (event-driven, limit order t+1, gap stop, fee 0,15%/0,25%, slippage 10 bps, tick BEI, lot 100, walk-forward) | TESTED | `test_backtest` |
| 14 | Risk Engine | `app/risk/`, `strategy/filters.py` (17 alasan tolak → BUY/WATCHLIST/WAIT/AVOID; NO TRADE) | TESTED | `test_risk`, `test_position_sizing`, `test_board_lot` |
| 15 | Portfolio Engine | `risk/concentration.py` (sektor, korelasi), portofolio di backtest | PARTIALLY_IMPLEMENTED: belum ada posisi live atau paper trading | `test_backtest` |
| 16 | Ranking Engine | `scanner/ranking.py`, `research/integrated_scoring.py` (9 ranking) | TESTED; skor `scalping_score`, `risk_score`, `data_quality_score` belum ada sebagai kolom tersendiri | `test_research`, `test_analytics` |
| 17 | Reporting Engine | `app/reporting/` (CSV, HTML, Markdown), `storage/report_storage.py` | TESTED | `test_daily_pipeline` |
| 18 | Cloud Scheduler & Monitoring | `.github/workflows/`, `pipeline/context.py` (pipeline_runs, system_logs), `pipeline/health.py` | IMPLEMENTED: logika diuji; eksekusi workflow hanya bisa diverifikasi di GitHub | `test_daily_pipeline`, `test_database_providers` |

## Model challenger (LSTM, GRU, ARIMA-GARCH, TFT)

Paket `app/challengers/` berisi empat model challenger, dirinci di [CHALLENGER_MODELS.md](CHALLENGER_MODELS.md).
Paket ini terpisah dari model aktif:
- tabel sendiri: `challenger_models` dan `model_forecasts`;
- workflow sendiri: `challenger_train.yml` (mingguan) dan `challenger_predict.yml` (setelah Daily);
- dependensi sendiri: `requirements-models.txt` dan torch CPU.

Challenger tidak memengaruhi keputusan BUY/WAIT. Evaluasinya memakai label, fold test, biaya, dan metrik yang sama
dengan model aktif. Status: `TESTED` (`test_challengers_core`, `test_challengers_models` di CI dengan library asli).

## Cakupan pemindaian (baru)

`app/scanner/coverage.py` memberi setiap emiten aktif tepat satu status per tanggal scan:

| Status | Kapan |
|---|---|
| `SUCCESS` | data hari scan lengkap, histori ≥ `quality.min_history_days`, lolos aturan universe |
| `PARTIAL_DATA` | baris hari scan ada tetapi fitur inti kosong, atau baris ditolak cleaner |
| `INSUFFICIENT_DATA` | histori terlalu pendek (IPO baru) atau belum ada data sama sekali |
| `PROVIDER_ERROR` | provider gagal teknis untuk emiten itu pada run tersebut |
| `EXCLUDED` | suspensi, tidak likuid, harga < minimum, atau papan Pemantauan Khusus |
| `STALE_DATA` | data terakhir lebih tua dari tanggal scan |

Coverage dihitung dari frame fitur **sebelum** ranking. `apply_coverage_gate` menurunkan BUY menjadi WAIT
untuk semua status selain SUCCESS dan menambahkan alasan `coverage_<status>`. Akibatnya, data tidak valid
tidak bisa menghasilkan sinyal.

Hasilnya disimpan di:

- tabel `scan_coverage` (per emiten, retensi 120 hari);
- `pipeline_runs.summary.coverage` (ringkasan, permanen);
- report `scan_coverage_YYYYMMDD.csv` dan bagian *Cakupan pemindaian* di report Markdown;
- dashboard → *Full-Market Coverage*.

Bila cakupan < `coverage.min_coverage_pct` (80%), run ditandai `PARTIAL_SUCCESS`.

## Pencegahan bias (yang sudah ada)

- **Look-ahead:** `test_no_data_leakage` membuktikan fitur dari data penuh = fitur dari data yang dipotong di
  t, dan bahwa mengubah data setelah t tidak mengubah fitur di t. Test ini juga terbukti bisa gagal ketika fitur
  bocor disuntikkan.
- **Walk-forward:** test set 6 bulan terakhir disegel (tidak dipakai untuk tuning); embargo sebesar horizon
  terpanjang di setiap batas fold.
- **Promosi model:** AUC ≥ 0,52, std AUC ≤ 0,05, ECE ≤ 0,06, proxy trading positif ≥ 50% fold, dan tidak lebih
  buruk dari model aktif pada data setelah model aktif dilatih. Bila tidak lolos → REJECTED.
- **Fundamental point-in-time:** `first_known_date`. Snapshot Yahoo tidak dipakai mundur di backtest.
- **Survivorship:** emiten delisting tidak dihapus. Keterbatasan sumber harga dibahas di KNOWN_LIMITATIONS.

## Kode legacy (tidak dipakai, tidak bisa dijalankan)

File berikut berasal dari versi awal berbasis SQLAlchemy dan Typer. Tidak ada jalur produksi yang
mengimpornya, dan dependensinya (`sqlalchemy`, `typer`) tidak ada di `requirements.txt`:

`app/cli.py`, `app/database/{base,session,models,init_db}.py`, `app/pipeline/daily.py`,
`app/pipeline/evaluation.py`, `app/data/manager.py`, `app/data/yahoo.py`, `app/data/csv_provider.py`,
`scripts/train_from_database.py`.

`app/risk/engine.py`, `app/models/model.py`, dan `app/data/provider.py` masih diimpor oleh test atau modul lain,
jadi perlu dicek sebelum dihapus. Rekomendasinya: hapus kelompok pertama dalam PR terpisah setelah dipastikan tidak ada yang
memakainya (roadmap Fase 1b). Kode ini tidak dihapus di sesi audit agar perubahan tetap kecil dan mudah
ditinjau.
