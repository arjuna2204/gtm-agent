import json
import tempfile
import unittest
from datetime import date
from unittest import mock

from scout import score, writeups
from scout.store import Store

TODAY = date(2026, 11, 26)


def build_store(tmp):
    s = Store(tmp)
    s.upsert_company("Ledgerly, Inc.", state="NY", industry="Other Technology", size_est="50-200", source="formd")
    s.add_signal("ledgerly", "raise", "acc1", "2026-11-12", "Raised $22.5M of a $25.0M round (Form D)", "https://sec/1")
    s.add_signal("ledgerly", "hiring", "job1", "2026-11-20", "Hiring: Controller", "https://jobs/1",
                 data={"role_class": "stack", "title": "Controller"})
    lead, _ = s.add_signal("ledgerly", "leader", "news1", "2026-11-10", "Ledgerly appoints CFO", "https://news/1",
                           data={"needs_check": False, "confirmed": True})
    s.upsert_company("Quiet Co", state="CA", size_est="500+", source="watchlist")
    s.add_signal("quiet", "hiring", "job2", "2026-11-01", "Hiring: Staff Accountant", "https://jobs/2",
                 data={"role_class": "finance", "title": "Staff Accountant"})
    s.upsert_company("No Signal Inc", state="TX")
    return s


class TestScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = build_store(self.tmp.name)
        for sig in self.s.signals.values():
            sig["last_seen"] = "2026-11-25T00:00:00+00:00"
        self.profile = score.load_profile()

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_marks_account(self):
        rows = score.score_all(self.s, self.profile, TODAY)
        top = rows[0]
        self.assertEqual(top["company_id"], "ledgerly")
        self.assertEqual(top["parts"], {"industry": 15, "size": 15, "region": 10, "raise": 20, "hiring": 15,
                                        "leader": 10, "strength": 15})
        self.assertEqual(top["total"], 100)
        self.assertEqual(len(top["signal_ids"]), 3)

    def test_weaker_account_and_filtering(self):
        rows = score.score_all(self.s, self.profile, TODAY)
        ids = [r["company_id"] for r in rows]
        self.assertNotIn("no-signal", ids)  # no timing signal = not listed
        q = rows[ids.index("quiet")]
        self.assertEqual(q["parts"]["hiring"], 8)
        self.assertEqual(q["parts"]["size"], 8)  # 500+ is next to 200-500
        self.assertEqual(q["parts"]["industry"], 8)  # unknown industry = partial credit

    def test_stale_hiring_ignored(self):
        for sig in self.s.signals.values():
            sig["last_seen"] = "2026-10-01T00:00:00+00:00"
        rows = score.score_all(self.s, self.profile, TODAY)
        self.assertEqual(rows[0]["parts"]["hiring"], 0)

    def test_unconfirmed_leader_not_counted(self):
        for sig in self.s.signals.values():
            if sig["type"] == "leader":
                sig["data"]["confirmed"] = False
        self.assertEqual(score.score_all(self.s, self.profile, TODAY)[0]["parts"]["leader"], 0)


class TestCitations(unittest.TestCase):
    def test_drops_uncited_and_banned(self):
        draft = {"why_now": [{"text": "Raised $22.5M", "signal_ids": ["a"]},
                             {"text": "Invented fact", "signal_ids": ["zzz"]},
                             {"text": "No cite", "signal_ids": []}],
                 "persona": {"title": "Controller", "why": "owns AP"}, "brief": "b",
                 "emails": [{"step": 1, "subject": "s", "body": "Saw the Controller opening.", "signal_ids": ["b"]},
                            {"step": 2, "subject": "s", "body": "I hope this finds you well", "signal_ids": ["a"]},
                            {"step": 3, "subject": "s", "body": "ok", "signal_ids": ["nope"]}]}
        clean, dropped = writeups.check_citations(draft, {"a", "b"})
        self.assertEqual([b["text"] for b in clean["why_now"]], ["Raised $22.5M"])
        self.assertEqual([e["step"] for e in clean["emails"]], [1])
        self.assertEqual(dropped, 4)

    def test_write_top_with_mocked_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = build_store(tmp)
            for sig in s.signals.values():
                sig["last_seen"] = "2026-11-25T00:00:00+00:00"
            rows = score.score_all(s, score.load_profile(), TODAY)
            ids = rows[0]["signal_ids"]
            fake = json.dumps({"why_now": [{"text": "Fresh raise", "signal_ids": [ids[0]]}],
                               "persona": {"title": "VP Finance", "why": "x"}, "brief": "b",
                               "emails": [{"step": 1, "subject": "s", "body": "short", "signal_ids": [ids[0]]}]})
            with mock.patch.object(writeups, "DATA", s.dir), \
                    mock.patch.object(writeups, "call_claude", return_value=fake) as m:
                out = writeups.write_top(s, rows, score.load_profile(), top=1, usage=[], log=lambda *_: None)
                self.assertIn("ledgerly", out)
                # second run with unchanged signals reuses the saved write-up (no API call)
                writeups.write_top(s, rows, score.load_profile(), top=1, usage=[], log=lambda *_: None)
                self.assertEqual(m.call_count, 1)
            prompt = writeups.account_prompt(s.companies["ledgerly"], [s.signals[i] for i in ids], rows[0],
                                             score.load_profile())
            self.assertIn(ids[0], prompt)


if __name__ == "__main__":
    unittest.main()
