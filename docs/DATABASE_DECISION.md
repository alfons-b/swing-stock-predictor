# Keputusan Database Produksi

**Keputusan: Neon PostgreSQL (paket Free), dalam project Neon baru yang khusus untuk proyek ini.**
Cadangan bila Neon tidak bisa dipakai: Aiven for PostgreSQL (Free).

Status: keputusan desain. Database belum dibuat. Pembuatan akun, project, dan secret `DATABASE_URL` harus dilakukan
sendiri oleh pemilik repo (langkah ada di [CLOUD_OPERATIONS.md](CLOUD_OPERATIONS.md#1-membuat-database-neon)).

Batas paket gratis di bawah ini dicek dari halaman resmi pada **12 Oktober 2026**. Vendor bisa mengubahnya kapan saja,
jadi periksa ulang sebelum mengandalkannya.

## Mengapa bukan Supabase

Pemilik repo memakai Supabase untuk aplikasi lain. Proyek ini **tidak boleh** menumpang project Supabase tersebut,
meminta aksesnya, atau memigrasikan apa pun di dalamnya. Kode tidak lagi bergantung pada Supabase:

- koneksi memakai `DATABASE_URL` PostgreSQL standar;
- model dan report disimpan di tabel database (`storage.*_backend: auto` → `database`);
- workflow tidak lagi meneruskan `SUPABASE_URL` / `SUPABASE_KEY`.

Kelas `Supabase*Storage` masih ada sebagai backend legacy opsional. Kelas itu hanya aktif bila
`MODEL_STORAGE=supabase` diset eksplisit. Di `APP_ENV=production`, host Supabase **ditolak** sebelum koneksi dan
migrasi (`guard_production_database`; override sadar `ALLOW_SUPABASE_DATABASE=true`). Di development, health check
menampilkan `DATABASE PROVIDER: WARN`.

## Perbandingan

| Kriteria | **Neon Free** | **Aiven Free** | Render Free | Supabase Free |
|---|---|---|---|---|
| Storage | 1 GB per project (20 GB total lintas project) | 1 GB disk | 1 GB | 500 MB |
| Compute | 100 CU-jam / project / bulan, autoscale s/d 2 CU | 1 CPU, 1 GB RAM, 1 node | — | — |
| Koneksi | direct + pooler (PgBouncer) | `max_connections` = 20 | — | — |
| Egress | 5 GB / project | tidak disebutkan | — | — |
| Idle | scale-to-zero setelah 5 menit (selalu aktif); bangun otomatis saat ada koneksi | **bisa di-power-off bila tidak ada aktivitas**; ada notifikasi; dinyalakan ulang manual | — | — |
| Persistensi | permanen, tidak ada kebijakan hapus karena idle yang disebutkan | tanpa batas waktu; tetap bisa dimatikan bila idle | **kedaluwarsa 30 hari**, lalu dihapus 14 hari kemudian | — |
| Backup / restore | history 6 jam (maks 1 GB), 1 snapshot manual | backup termasuk (retensi tidak disebutkan) | tidak ada backup | — |
| Saat kuota habis | CU-jam/egress habis → compute ditangguhkan s/d periode berikutnya; storage penuh → **penulisan diblokir**. Data tidak dihapus | disk penuh → penulisan gagal | — | project read-only |
| Kartu pembayaran | tidak perlu | tidak perlu | — | — |
| Dari GitHub Actions | TLS, IPv4, connection string standar | TLS, IPv4 | — | — |
| Status | **dipilih** | cadangan | **ditolak** (bukan penyimpanan jangka panjang) | **dikecualikan** (aturan proyek) |

Sumber: [Neon pricing](https://neon.com/pricing), [Aiven PG free tier](https://aiven.io/docs/products/postgresql/concepts/pg-free-tier),
[Render free](https://render.com/docs/free).

### Alasan memilih Neon

1. **Pola beban cocok dengan scale-to-zero.** Semua job adalah batch pendek, lalu database idle. Database
   tidak perlu hidup 24 jam.
2. **Idle tidak membuat layanan mati.** Neon menangguhkan compute lalu membangunkannya otomatis saat koneksi
   berikutnya. Aiven bisa mematikan layanan yang idle dan butuh tindakan manual, sehingga job terjadwal tanpa
   pengawasan bisa gagal diam-diam.
3. **Kuota habis tidak menghapus data.** Penulisan diblokir, dan sistem sudah punya retensi otomatis sebelum
   batas tercapai (lihat di bawah).
4. **Storage 2× Supabase Free.** 1 GB memberi ruang untuk 6–7 tahun harga harian seluruh universe.

### Risiko Neon yang diterima

- **Backup terbatas.** History 6 jam dan 1 snapshot manual. Mitigasinya: harga dan IHSG bisa diunduh ulang dari
  provider lewat `setup`. Yang tidak bisa direkonstruksi adalah riwayat prediksi, evaluasi, dan registry model.
  Ambil snapshot manual sebelum perubahan besar dan ekspor CSV berkala (lihat CLOUD_OPERATIONS §6).
- **Cold start.** Compute yang sedang suspend perlu beberapa detik untuk bangun. Koneksi dicoba ulang hingga
  6× dengan backoff (`app/database/providers.py`).
- **Kebijakan paket gratis bisa berubah.** Tidak ada jaminan Rp0 selamanya.

## Kesesuaian dengan beban kerja

### Compute (CU-jam)

Durasi job nyata dari run GitHub Actions repo ini (8–12 Oktober 2026):

| Job | Durasi teramati | Frekuensi |
|---|---|---|
| Daily | 8–17 menit | 5×/minggu |
| Retrain | 2–6 menit (hanya melatih bila model > 30 hari) | 1×/minggu |
| Weekly backtest | 10–14 menit | 1×/minggu |
| Setup awal | 6–17 menit | sekali |

Estimasi kasar per bulan: (22 × ~20 menit + 4 × ~25 menit + health check 22 × ~6 menit), termasuk 5 menit ekor
sebelum suspend. Totalnya ≈ 11 jam compute aktif. Pada 0,25 CU itu ≈ 3 CU-jam, dan bila autoscale penuh ke 2 CU
≈ 22 CU-jam. Keduanya jauh di bawah 100 CU-jam. Angka ini estimasi: pantau di Neon Console → Usage.

### Storage

Ukuran per baris diukur penulis proyek di PostgreSQL 16 untuk ±920 emiten (lihat `app/database/maintenance.py`):

| Tabel | Pertumbuhan | Dengan retensi default |
|---|---|---|
| `price_history` | ±45 MB/tahun | 7 tahun ≈ 300–330 MB |
| `predictions` + evaluasi | ±177 MB/tahun | WAIT/AVOID 180 hari → ±90 MB + BUY/WATCHLIST (disimpan selamanya) |
| `valuation_results` | ±22 MB/tahun | ±30 MB + akhir bulan |
| `scan_coverage` (baru) | ±28 MB/tahun | 120 hari ≈ 10 MB |
| `foreign_flow_history` (bila ada sumber) | ±45 MB/tahun | 7 tahun ≈ 315 MB ← **terlalu besar bersama tabel lain** |

Tanpa foreign flow, total ±500–600 MB, muat di batas efektif 950 MB. **Bila sumber foreign flow diaktifkan**,
turunkan `research_retention.foreign_flow_years` ke 2–3 tahun.

**Data intraday tidak muat untuk seluruh universe dalam jangka panjang.** Bar 5 menit untuk ±960 emiten ≈ 48 bar ×
245 hari ≈ 11 juta baris/tahun, lebih dari 1 GB. Bila intraday diimplementasikan, simpan hanya fitur/agregat
harian secara permanen, dan bar mentah dengan retensi 20–60 hari untuk subset likuid (KNOWN_LIMITATIONS §3).

## Implementasi

`app/database/providers.py` mendeteksi provider dari host di `DATABASE_URL`:

| Provider | Deteksi host | Batas efektif (`DB_SIZE_LIMIT_MB=auto`) | SSL | Retry koneksi |
|---|---|---|---|---|
| neon | `*.neon.tech` | 950 MB (dari 1 GB) | `sslmode=require` ditambahkan bila belum ada | 6× |
| aiven | `*.aivencloud.com` | 800 MB (dari 1 GB disk termasuk WAL) | wajib | 4× |
| supabase | `*supabase.co/.com` | 500 MB | wajib | 3× |
| postgres lain | host lain | 1000 MB (set `DB_SIZE_LIMIT_MB`) | `require` | 4× |

Batas efektif sengaja dibulatkan ke bawah karena cara vendor mengukur storage tidak identik dengan
`pg_database_size`. Perilaku terkait kuota:

- `health`: `DATABASE SIZE` WARN ≥ 80%, FAIL ≥ 95%.
- Daily menjalankan retensi otomatis bila ukuran ≥ 85%.
- Sebelum menulis, daily menjalankan maintenance darurat (retensi + `VACUUM FULL`) bila ukuran ≥ 95% atau
  database read-only. Bila masih penuh, daily berhenti dengan pesan jelas, bukan gagal di tengah penulisan.
- Workflow **Database Health Check** melakukan uji tulis harian (insert + delete). Neon tidak menandai
  database sebagai read-only saat kuota habis, jadi `SELECT 1` saja tidak cukup.

Setelah upgrade paket, set Variable repo `DB_SIZE_LIMIT_MB` ke batas baru (MB).

## Skema

Skema didefinisikan sekali di `app/database/schema.py` dan dimigrasi secara **additive** (`CREATE … IF NOT EXISTS`
dan `ALTER TABLE ADD COLUMN`), dicatat di `schema_migrations`. Migrasi tidak pernah menghapus tabel atau kolom.
Versi skema saat ini: **4** (menambah `scan_coverage`).

Pemetaan tabel yang diminta spesifikasi ke tabel yang ada:

| Spesifikasi | Tabel di repo | Catatan |
|---|---|---|
| `stock_universe` | `stocks` | `is_active`, `listing_date`, `delisting_date`, `board`, `previous_ticker` |
| `universe_history` | `stocks` (first_seen/last_seen/delisting) + `scan_coverage` | histori status per tanggal ada di `scan_coverage` (120 hari) |
| `daily_ohlcv` | `price_history` | UNIQUE(stock_id, date) |
| `intraday_ohlcv` | — | BLOCKED_BY_DATA (KNOWN_LIMITATIONS §3) |
| `corporate_actions` | `corporate_actions` | |
| `fundamental_statements` | `financial_statements` | point-in-time, tidak pernah dihapus |
| `foreign_flow` | `foreign_flow_history` | |
| `broker_activity` | — | antarmuka ada (`app/accumulation/broker_flow.py`), tabel menunggu sumber data |
| `technical_features` | `features` (snapshot 5 hari) | fitur dihitung ulang dari harga, bukan disimpan |
| `strategy_signals` | `trading_signals` + `predictions` | |
| `model_predictions` | `predictions` + `prediction_evaluations` | |
| `valuation_results` | `valuation_results` | |
| `backtest_runs` | `backtest_runs` + `backtest_trades` | |
| `portfolio_positions` | — | belum ada (paper trading, roadmap Fase 14) |
| `risk_metrics` | kolom di `predictions` + `backtest_runs.metrics` | |
| `pipeline_runs` | `pipeline_runs` + `system_logs` | |
| `data_quality_reports` | `pipeline_runs.summary` (validate_data) + `scan_coverage` | |
| `provider_status` | `data_sources` | |
| `model_versions` | `model_versions` (artifact BYTEA) | |
