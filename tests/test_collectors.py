import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from scout import ats, formd, news
from scout.store import Store, clean_name, company_id

FX = Path(__file__).parent / "fixtures"


class TestFormD(unittest.TestCase):
    def test_index_keeps_only_new_form_d(self):
        rows = formd.parse_index((FX / "form.20261124.idx").read_text())
        self.assertEqual([r["company"] for r in rows], ["Ledgerly, Inc.", "Blue Harbor Fund II, L.P."])
        self.assertEqual(rows[0]["cik"], "1987654")
        self.assertEqual(rows[0]["accession"], "0001987654-26-000001")
        self.assertEqual(rows[0]["filed"], "2026-11-24")

    def test_index_url(self):
        self.assertEqual(formd.index_url(date(2026, 11, 24)),
                         "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261124.idx")

    def test_primary_doc(self):
        d = formd.parse_primary_doc((FX / "primary_doc.xml").read_text())
        self.assertEqual(d["entity_name"], "Ledgerly, Inc.")
        self.assertEqual(d["state"], "NY")
        self.assertEqual(d["industry"], "Other Technology")
        self.assertEqual(d["first_sale"], "2026-11-12")
        self.assertEqual(d["amount_sold"], 22_500_000)
        self.assertFalse(d["is_amendment"])
        self.assertEqual(d["people"][0]["name"], "Dana Example")
        self.assertIn("Executive Officer", d["people"][0]["relationships"])
        self.assertEqual(d["securities"], ["isEquityType"])

    def test_filters(self):
        d = formd.parse_primary_doc((FX / "primary_doc.xml").read_text())
        self.assertTrue(formd.is_operating_company("Ledgerly, Inc.", d)[0])
        fund = dict(d, entity_name="Blue Harbor Fund II, L.P.")
        self.assertFalse(formd.is_operating_company("x", fund)[0])
        self.assertFalse(formd.is_operating_company("x", dict(d, industry="Pooled Investment Fund"))[0])
        self.assertFalse(formd.is_operating_company("x", dict(d, amount_sold=500_000, offering_total=None))[0])
        self.assertFalse(formd.is_operating_company("x", dict(d, state="A1"))[0])

    def test_stage(self):
        self.assertEqual(formd.stage_from_amount(22.5e6), "Series B")
        self.assertEqual(formd.stage_from_amount(3e6), "Seed")

    def test_collect_end_to_end(self):
        idx = (FX / "form.20261124.idx").read_text()
        doc = (FX / "primary_doc.xml").read_text()

        def fake(url):
            if url.endswith(".idx"):
                return (200, idx) if "20261124" in url else (404, "")
            return 200, doc

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(formd, "sec_get", side_effect=fake):
            s = Store(tmp)
            formd.collect(s, days=1, end=date(2026, 11, 25), log=lambda *_: None)
            self.assertIn("ledgerly", s.companies)
            c = s.companies["ledgerly"]
            self.assertEqual((c["state"], c["city"], c["stage_est"]), ("NY", "New York", "Series B"))
            sig = s.signals_for("ledgerly", "raise")[0]
            self.assertEqual(sig["date"], "2026-11-12")
            self.assertIn("$22.5M", sig["title"])
            self.assertTrue(sig["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/1987654/"))
            # re-running does not duplicate
            formd.collect(s, days=1, end=date(2026, 11, 25), log=lambda *_: None)
            self.assertEqual(len(s.signals), 1)
            s.save()
            self.assertEqual(len(Store(tmp).signals), 1)


class TestATS(unittest.TestCase):
    def test_classify_titles(self):
        cases = {
            "Controller": "stack", "Senior Manager, FP&A": "stack", "Accounts Payable Specialist": "stack",
            "Head of Finance": "stack", "VP, Finance": "stack", "Staff Accountant": "finance",
            "Payroll Specialist": "finance", "Software Engineer, Payments": "", "Account Executive, Finance Vertical": "",
            "Product Designer": "", "Tax Manager": "finance",
        }
        for title, want in cases.items():
            self.assertEqual(ats.classify_title(title), want, title)

    def test_slugs(self):
        self.assertEqual(ats.candidate_slugs("Ledgerly, Inc.", strict=True), ["ledgerly"])
        self.assertEqual(ats.candidate_slugs("Northwind Robotics Inc", strict=True), ["northwindrobotics", "northwind-robotics"])
        self.assertIn("northwind", ats.candidate_slugs("Northwind Robotics Inc"))

    def test_record_board(self):
        jobs = [{"id": "ashby:ledgerly:1", "title": "Controller", "location": "New York", "department": "Finance",
                 "url": "https://jobs.ashbyhq.com/ledgerly/1", "posted": "2026-11-20T00:00:00Z"},
                {"id": "ashby:ledgerly:2", "title": "Software Engineer", "location": "Remote", "department": "Eng",
                 "url": "u", "posted": ""}]
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(tmp)
            s.upsert_company("Ledgerly, Inc.")
            n_stack, n_fin, new = ats.record_board(s, "ledgerly", "ashby", "ledgerly", jobs, "2026-11-26")
            self.assertEqual((n_stack, n_fin, new), (1, 0, 1))
            c = s.companies["ledgerly"]
            self.assertEqual((c["open_roles"], c["size_est"]), (2, "under 50"))
            sig = s.signals_for("ledgerly", "hiring")[0]
            self.assertEqual(sig["date"], "2026-11-20")
            self.assertEqual(sig["data"]["role_class"], "stack")


class TestNews(unittest.TestCase):
    def test_leader_items(self):
        items = news.parse_rss((FX / "news.xml").read_text())
        self.assertEqual(len(items), 3)
        keep = news.leader_items(items, "Ledgerly", today=date(2026, 11, 26))
        self.assertEqual([k["url"] for k in keep], ["https://news.example.com/a"])
        self.assertEqual(keep[0]["date"], "2026-11-10")


class TestStore(unittest.TestCase):
    def test_names(self):
        self.assertEqual(clean_name("Ledgerly, Inc."), "Ledgerly")
        self.assertEqual(clean_name("Acme Co., LLC"), "Acme")
        self.assertEqual(company_id("Brex Inc."), "brex")


if __name__ == "__main__":
    unittest.main()
