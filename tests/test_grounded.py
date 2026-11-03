import json
import tempfile
import unittest
from pathlib import Path

from grounded import coach
from grounded.meta_client import BudgetExceeded, Ledger, MetaClient, price
from grounded.offline import OfflineClient
from grounded.server import load_sample
from grounded.store import Store

FACTS = {
    "F-2": {"id": "F-2", "status": "confirmed",
            "text": "Led the migration of webhook delivery to Kafka, cutting median delivery latency from 40s to 2s."},
}
ALL = {**FACTS, "F-9": {"id": "F-9", "status": "draft", "text": "Wrote a postmortem."}}


class GroundingTests(unittest.TestCase):
    def check(self, **kw):
        return coach.check_sentence({"text": "x", "fact_id": None, "quote": None} | kw, FACTS, ALL)

    def test_grounded_claim_with_verbatim_quote(self):
        r = self.check(text="I moved webhooks to Kafka and latency went from 40s to 2s.", fact_id="F-2", quote="cutting median delivery latency")
        self.assertEqual(r["status"], "grounded")

    def test_quote_match_ignores_case_whitespace_and_smart_quotes(self):
        self.assertTrue(coach.quote_in("LED  the migration\nof webhook", FACTS["F-2"]["text"]))
        self.assertTrue(coach.quote_in("“from 40s to 2s”", FACTS["F-2"]["text"]))

    def test_paraphrased_quote_is_unsupported(self):
        r = self.check(text="I sped up webhooks.", fact_id="F-2", quote="made webhooks much faster")
        self.assertEqual(r["status"], "unsupported")

    def test_inflated_number_is_unsupported_even_with_valid_quote(self):
        r = self.check(text="Latency dropped 95% to 2s.", fact_id="F-2", quote="cutting median delivery latency")
        self.assertEqual(r["status"], "unsupported")
        self.assertIn("95%", r["issues"][0])

    def test_unknown_and_draft_facts(self):
        self.assertEqual(self.check(fact_id="F-404", quote="anything here").get("status"), "unsupported")
        self.assertEqual(self.check(fact_id="F-9", quote="Wrote a postmortem").get("status"), "draft_fact")

    def test_tiny_quotes_do_not_count(self):
        self.assertFalse(coach.quote_in("to", FACTS["F-2"]["text"]))

    def test_spelled_out_units_match_abbreviations(self):
        r = self.check(text="Median latency went from 40 seconds to 2 seconds.", fact_id="F-2", quote="cutting median delivery latency")
        self.assertEqual(r["status"], "grounded")
        self.assertEqual(coach.numbers("900 milliseconds, 30 percent, 2 million"), {"900ms", "30%", "2m"})
        self.assertNotEqual(coach.numbers("40 percent"), coach.numbers("40s"))

    def test_stray_numbers(self):
        self.assertEqual(coach.stray_numbers("From 40s to 2s, saving $3M and 50%.", FACTS), ["$3M", "50%"])


class BudgetTests(unittest.TestCase):
    def test_price_uses_cached_rate(self):
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_tokens_details": {"cached_tokens": 500_000}}
        self.assertAlmostEqual(price("muse-spark-1.3", usage), 0.625 + 0.075 + 4.25)

    def test_ledger_refuses_before_calling(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Ledger(Path(d) / "spend.jsonl", cap_usd=0.01)
            ledger.record({"cost_usd": 0.009})
            client = MetaClient(ledger, "fake-key")
            client._post = lambda *a, **k: self.fail("network must not be touched")
            with self.assertRaises(BudgetExceeded):
                client.chat_json("t", [{"role": "user", "content": "hi"}], {"type": "object"}, max_out=4000)

    def test_live_call_is_priced_and_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Ledger(Path(d) / "spend.jsonl", cap_usd=5)
            client = MetaClient(ledger, "fake-key")
            client._post = lambda path, body, timeout=180: {
                "model": "muse-spark-1.3", "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                "choices": [{"message": {"content": json.dumps({"ok": True})}}]}
            out, meta = client.chat_json("t", [{"role": "user", "content": "hi"}], {"type": "object"})
            self.assertEqual(out, {"ok": True})
            self.assertAlmostEqual(ledger.spent(), (1000 * 1.25 + 200 * 4.25) / 1e6, places=6)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / "g.sqlite3")
        self.client = OfflineClient(Ledger(root / "spend.jsonl", 1))
        self.jd = load_sample(self.store)["jd"]

    def tearDown(self):
        self.store.con.close()
        self.tmp.cleanup()

    def test_plan_verifies_jd_quotes_and_story_ids(self):
        plan = coach.make_plan(self.client, self.store, "Orbit", "SSE", self.jd)
        self.assertEqual(len(plan["questions"]), 8)
        self.assertTrue(all(q["jd_quote_verified"] for q in plan["questions"]))
        ids = {s["id"] for s in self.store.stories()}
        self.assertTrue(all(q["story_id"] in ids or q["story_id"] is None for q in plan["questions"]))

    def test_grade_drops_fabricated_rewrite_sentence(self):
        plan = coach.make_plan(self.client, self.store, "Orbit", "SSE", self.jd)
        q = next(q for q in plan["questions"] if q["story_id"])
        answer = ("I led the migration of webhook delivery from a cron poller to Kafka. "
                  "Median delivery latency went from 40s to 2s. We also saved $2M a year.")
        g = coach.grade_answer(self.client, self.store, plan["id"], q["id"], answer, 75)
        self.assertIn("$2M", g["stray_numbers"])
        self.assertTrue(any("73%" in s["text"] for s in g["dropped_sentences"]))
        self.assertFalse(any("73%" in s["text"] for s in g["improved_answer"]))
        self.assertTrue(all(s["status"] in ("grounded", "connective") for s in g["improved_answer"]))
        md = coach.brief_markdown(self.store, plan["id"])
        self.assertIn("Last practice", md)

    def test_entailment_removes_embellishment_and_missing_verdicts(self):
        facts = self.store.confirmed_facts()
        sents = [{"text": facts["F-4"]["text"], "fact_id": "F-4"},
                 {"text": "I audited every single alert, rebuilt dashboards and trained the whole org on paging hygiene.", "fact_id": "F-4"},
                 {"text": "Here is an example.", "fact_id": None}]
        kept, removed, _ = coach.entailment_filter(self.client, sents, facts)
        self.assertEqual([s["text"] for s in kept], [sents[0]["text"], sents[2]["text"]])
        self.assertIn("adds detail beyond F-4", removed[0]["issues"][0])

        class Silent:
            def chat_json(self, *a, **k):
                return {"verdicts": []}, {}
        kept, removed, _ = coach.entailment_filter(Silent(), sents, facts)
        self.assertEqual((kept, len(removed)), ([], 3))

    def test_deferred_entailment_matches_inline(self):
        plan = coach.make_plan(self.client, self.store, "Orbit", "SSE", self.jd)
        answer = "I led the migration of webhook delivery to Kafka; median delivery latency went from 40s to 2s."
        inline = coach.grade_answer(self.client, self.store, plan["id"], "Q1", answer)
        g = coach.grade_answer(self.client, self.store, plan["id"], "Q1", answer, entail=False)
        self.assertEqual(g["entailment"], "pending")
        done = coach.finish_entailment(self.client, self.store, g["id"])
        self.assertEqual(done["entailment"], "done")
        self.assertEqual([s["text"] for s in done["improved_answer"]], [s["text"] for s in inline["improved_answer"]])
        self.assertEqual(self.store.attempt(g["id"])["entailment"], "done")
        self.assertEqual(len(coach.finish_entailment(self.client, self.store, g["id"])["call"]), len(done["call"]))

    def test_followup_drill_chains_and_stops(self):
        plan = coach.make_plan(self.client, self.store, "Orbit", "SSE", self.jd)
        g = coach.grade_answer(self.client, self.store, plan["id"], "Q1", "I led the migration of webhook delivery to Kafka on the payments platform team.")
        ids = [g["id"]]
        for depth in (1, 2, 3):
            f = coach.grade_followup(self.client, self.store, ids[-1], "I don't have a measured number for that; I would check the dashboards first.")
            self.assertEqual((f["depth"], f["root_id"], f["parent_id"]), (depth, ids[0], ids[-1]))
            ids.append(f["id"])
        self.assertEqual(f["follow_up"], "")
        with self.assertRaises(ValueError):
            coach.grade_followup(self.client, self.store, ids[-1], "one more answer that should be refused")
        self.assertIn("Follow-up drill: 3 round(s)", coach.brief_markdown(self.store, plan["id"]))

    def test_import_marks_everything_draft(self):
        self.store.reset()
        r = coach.import_profile(self.client, self.store, "Built a billing service handling 2M invoices per month in Go.\nShort")
        self.assertEqual(r["facts_added"], 1)
        self.assertEqual(r["source_verified"], 1)
        self.assertEqual(self.store.confirmed_facts(), {})

    def test_unconfirmed_facts_cannot_ground(self):
        for f in self.store.facts():
            self.store.set_fact(f["id"], "draft")
        plan = coach.make_plan(self.client, self.store, "Orbit", "SSE", self.jd)
        g = coach.grade_answer(self.client, self.store, plan["id"], "Q1", "I led the migration of webhook delivery to Kafka and it was faster.")
        self.assertFalse(any(c["status"] == "grounded" for c in g["claims"]))


if __name__ == "__main__":
    unittest.main()
