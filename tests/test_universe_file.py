"""Universe dari file unduhan BEI apa adanya (No | Kode | Nama Perusahaan | Tanggal Pencatatan | Saham | Papan Pencatatan)."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.data.universe import UniverseManager
from app.data.universe_file import UniverseFileError, apply_sectors, load_universe_file, parse_date, parse_shares
from tests.helpers import make_cfg, make_ctx

IDX_ROWS = [
    {"No": 1, "Kode": "AALI", "Nama Perusahaan": "Astra Agro Lestari Tbk.", "Tanggal Pencatatan": "09 Des 1997",
     "Saham": "1.924.688.333", "Papan Pencatatan": "Utama"},
    {"No": 2, "Kode": "BBCA", "Nama Perusahaan": "Bank Central Asia Tbk.", "Tanggal Pencatatan": "31 Mei 2000",
     "Saham": "123.275.050.000", "Papan Pencatatan": "Utama"},
    {"No": 3, "Kode": "goto ", "Nama Perusahaan": "GoTo Gojek Tokopedia Tbk.", "Tanggal Pencatatan": "11 Apr 2022",
     "Saham": "1.144.000.000.000", "Papan Pencatatan": "Utama"},
]


def tmpdir():
    return Path(tempfile.mkdtemp(prefix="ssp_uni_"))


class TestParsers(unittest.TestCase):
    def test_dates(self):
        for s in ("31 Mei 2000", "31-May-2000", "2000-05-31", "31/05/2000", "31 Mei, 2000", 36677, "36677"):
            self.assertEqual(parse_date(s), pd.Timestamp("2000-05-31"), s)
        self.assertEqual(parse_date("09 Agustus 2021"), pd.Timestamp("2021-08-09"))
        self.assertEqual(parse_date("1 Okt 2024"), pd.Timestamp("2024-10-01"))
        self.assertTrue(pd.isna(parse_date("-")))

    def test_shares(self):
        self.assertEqual(parse_shares("123.275.050.000"), 123275050000.0)
        self.assertEqual(parse_shares("1,924,688,333"), 1924688333.0)
        self.assertEqual(parse_shares(5e9), 5e9)


class TestIDXFile(unittest.TestCase):
    def _check(self, u):
        self.assertEqual(u["ticker"].tolist(), ["AALI", "BBCA", "GOTO"])
        self.assertEqual(u.loc[1, "name"], "Bank Central Asia Tbk.")
        self.assertEqual(u.loc[1, "listing_date"], pd.Timestamp("2000-05-31"))
        self.assertEqual(u.loc[1, "listed_shares"], 123275050000.0)
        self.assertEqual(u.loc[0, "board"], "Utama")

    def test_xlsx_with_title_rows(self):
        p = tmpdir() / "Daftar Saham.xlsx"
        with pd.ExcelWriter(p) as w:  # unduhan kadang punya baris judul di atas tabel
            pd.DataFrame([["Daftar Saham"], [""]]).to_excel(w, index=False, header=False)
            pd.DataFrame(IDX_ROWS).to_excel(w, index=False, startrow=3)
        self._check(load_universe_file(p))

    def test_csv_semicolon_and_comma(self):
        for sep in (",", ";"):
            p = tmpdir() / "daftar.csv"
            pd.DataFrame(IDX_ROWS).to_csv(p, index=False, sep=sep)
            self._check(load_universe_file(p))

    def test_internal_format_still_works(self):
        p = tmpdir() / "u.csv"
        pd.DataFrame({"ticker": ["BBRI.JK"], "sector": ["Financials"]}).to_csv(p, index=False)
        u = load_universe_file(p)
        self.assertEqual((u.loc[0, "ticker"], u.loc[0, "sector"]), ("BBRI", "Financials"))

    def test_missing_code_column(self):
        p = tmpdir() / "x.csv"
        pd.DataFrame({"Nama": ["A"]}).to_csv(p, index=False)
        with self.assertRaises(UniverseFileError):
            load_universe_file(p)

    def test_sector_file_merge(self):
        d = tmpdir()
        pd.DataFrame({"Kode": ["BBCA", "AALI"], "Sektor": ["Keuangan", "Barang Konsumen Primer"],
                      "Subsektor": ["Bank", "Perkebunan"]}).to_csv(d / "sektor.csv", index=False)
        pd.DataFrame(IDX_ROWS).to_csv(d / "daftar.csv", index=False)
        u = apply_sectors(load_universe_file(d / "daftar.csv"), d / "sektor.csv")
        self.assertEqual(u.set_index("ticker").loc["BBCA", "sector"], "Keuangan")
        self.assertTrue(pd.isna(u.set_index("ticker").loc["GOTO", "sector"]))  # tidak ada di file sektor → kosong, tidak ditebak


class TestUniverseManagerWithIDXFile(unittest.TestCase):
    def test_file_used_when_csv_is_only_fallback(self):
        d = tmpdir()
        pd.DataFrame(IDX_ROWS).to_excel(d / "daftar.xlsx", index=False)
        cfg = make_cfg()
        cfg["universe"]["file"] = str(d / "daftar.xlsx")
        # production-like: CSV provider ada tetapi BUKAN provider utama
        cfg["market_data"]["providers"] = [
            {"name": "idx", "type": "idx", "enabled": True, "priority": 1},
            {**cfg["market_data"]["providers"][0], "priority": 99}]
        ctx = make_ctx(cfg)
        out = UniverseManager(cfg, ctx.repo, ctx.chain).update()
        self.assertEqual(out["source"], "file:daftar.xlsx")
        st = ctx.repo.stocks().set_index("ticker")
        self.assertEqual(sorted(st.index), ["AALI", "BBCA", "GOTO"])
        self.assertEqual(float(st.loc["BBCA", "listed_shares"]), 123275050000.0)
        self.assertEqual(str(st.loc["GOTO", "listing_date"])[:10], "2022-04-11")
        # emiten hilang dari daftar berikutnya → nonaktif, histori tidak dihapus; listed_shares tidak tertimpa NULL
        pd.DataFrame(IDX_ROWS[:2]).drop(columns=["Saham"]).to_excel(d / "daftar.xlsx", index=False)
        out = UniverseManager(cfg, ctx.repo, ctx.chain).update()
        st = ctx.repo.stocks().set_index("ticker")
        self.assertEqual(out["deactivated"], ["GOTO"])
        self.assertFalse(bool(st.loc["GOTO", "is_active"]))
        self.assertEqual(float(st.loc["BBCA", "listed_shares"]), 123275050000.0)


class TestMigration(unittest.TestCase):
    def test_new_column_added_to_old_database(self):
        from app.database.db import Database
        from app.database.schema import existing_columns, migrate
        db = Database.from_url("sqlite:///:memory:")
        db.executescript(["CREATE TABLE stocks (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, "
                          "is_active INTEGER NOT NULL, UNIQUE (ticker))",
                          "INSERT INTO stocks (ticker, is_active) VALUES ('BBCA', 1)"])
        migrate(db)
        self.assertIn("listed_shares", existing_columns(db, "stocks"))
        self.assertEqual(db.scalar("SELECT ticker FROM stocks"), "BBCA")  # data lama utuh


if __name__ == "__main__":
    unittest.main()
