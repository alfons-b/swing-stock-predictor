# data/raw — data input riset (opsional)

File di folder ini dibaca oleh workflow GitHub Actions setelah `checkout`, jadi file yang Anda commit ke repo
(PRIVAT) otomatis dipakai oleh daily pipeline. Jangan menyimpan secret di sini.

| Folder | Isi | Format |
|---|---|---|
| `fundamentals/` | Laporan keuangan dari laporan resmi emiten / vendor berlisensi | CSV/XLSX kanonik — buat template: `python main.py fundamentals-template` |
| `foreign_flow/` | File **Ringkasan Saham** unduhan idx.co.id (Data Pasar → Ringkasan Perdagangan → Ringkasan Saham), satu file per hari bursa | `.xlsx`/`.csv` apa adanya; **tanggal wajib ada di nama file**, mis. `Ringkasan Saham-20261009.xlsx` |
| `foreign_flow_csv/` | Foreign flow dari vendor | CSV: `date,ticker,foreign_buy_shares,foreign_sell_shares[,foreign_buy_value,foreign_sell_value,market_segment,units,total_volume_shares]` |
| `fx/` | Kurs untuk laporan non-IDR (mis. emiten batubara ber-laporan USD) | `fx_rates.csv`: `date,currency,rate_idr` |
| `broker_summary/` | Broker summary dari vendor berlisensi (nonaktif default) | lihat `app/accumulation/broker_flow.py` |

Catatan penting:
- Foreign buy/sell BEI dalam **LEMBAR**. Nilai rupiah hanya disimpan bila sumber memberikannya; selain itu nilai
  dihitung sebagai estimasi (lembar × VWAP) dan berlabel `ESTIMATED_VALUE`.
- `publication_date` di file fundamental harus tanggal publikasi ASLI laporan. Bila tidak diketahui, kosongkan —
  sistem memakai tanggal pertama data diketahui (aman untuk live, tidak dipakai mundur di backtest).
- Ukuran: ±900 file Ringkasan Saham (±3,5 tahun) ≈ 50–150 MB di repo. Pertimbangkan Git LFS atau hanya menyimpan
  ±1 tahun terakhir bila repo membesar; histori yang sudah masuk database tetap tersimpan.
