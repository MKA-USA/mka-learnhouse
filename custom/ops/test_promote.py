import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import promote as p

DEV = """services:
  app:
    build:
      context: 'https://x/y.git#dev'
    environment:
      - 'A=${A:-}'
      - 'B=${B:-}'
      - 'NEW1=${NEW1:-}'
      - 'C=${C:-}'
      - 'NEW2=${NEW2:-}'
    volumes:
      - data:/d
  db:
    environment:
      - 'P=1'
"""
PROD = """services:
  app:
    build:
      context: 'https://x/y.git#prod'
    environment:
      - 'A=${A:-}'
      - 'B=${B:-}'
      - 'C=${C:-}'
    volumes:
      - data:/d
  db:
    environment:
      - 'P=1'
"""


class EnvPlan(unittest.TestCase):
    def test_plan(self):
        dev = [{"key": "A", "value": "1"}, {"key": "B", "value": "https://ilm-dev.mkausa.org/x"},
               {"key": "C", "value": "same"}, {"key": "MKA_AUTOMATION_CRON_SECRET", "value": "d"},
               {"key": "MKA_AUTOMATION_WEBHOOK_SECRET", "value": "d"}, {"key": "SERVICE_PASSWORD_X", "value": "d"},
               {"key": "N", "value": "n"}]
        prod = [{"key": "A", "value": "0"}, {"key": "B", "value": "https://ilm.mkausa.org/x"},
                {"key": "C", "value": "same"}, {"key": "MKA_AUTOMATION_CRON_SECRET", "value": "p"},
                {"key": "ONLYPROD", "value": "z"}]
        r = p.plan_env(dev, prod)
        ops = {a["key"]: a for a in r["actions"]}
        self.assertEqual(ops["A"]["op"], "update")
        self.assertEqual(ops["N"]["op"], "create")
        self.assertNotIn("B", ops)  # host-rewritten value already equal
        self.assertNotIn("C", ops)
        self.assertEqual(r["gen"], ["MKA_AUTOMATION_WEBHOOK_SECRET"])
        self.assertEqual(r["prod_only"], ["ONLYPROD"])
        self.assertIn("SERVICE_PASSWORD_X", r["skipped"])

    def test_host_rewrite_in_plan(self):
        r = p.plan_env([{"key": "U", "value": "https://ilm-dev.mkausa.org"}], [])
        self.assertEqual(r["actions"][0]["value"], "https://ilm.mkausa.org")

    def test_rewrite_host(self):
        self.assertEqual(p.rewrite_host("a ilm-dev.mkausa.org b"), "a ilm.mkausa.org b")
        self.assertEqual(p.rewrite_host(5), 5)


class Secrets(unittest.TestCase):
    def test_secrets_not_copied(self):
        dev = [{"key": k, "value": "v"} for k in (
            "NEXTAUTH_SECRET", "POSTGRES_PASSWORD", "LEARNHOUSE_AUTH_JWT_SECRET_KEY", "SOME_API_TOKEN",
            "MY_DSN", "LEARNHOUSE_GOOGLE_CLIENT_SECRET", "NEXT_PUBLIC_TURNSTILE_SITE_KEY", "PLAIN")]
        dev.append({"key": "REDIS_X", "value": "redis://u:pw@h:6379/0"})
        r = p.plan_env(dev, [{"key": "SOME_API_TOKEN", "value": "p"}])
        copied = {a["key"] for a in r["actions"]}
        self.assertEqual(copied, {"LEARNHOUSE_GOOGLE_CLIENT_SECRET", "NEXT_PUBLIC_TURNSTILE_SITE_KEY", "PLAIN"})
        self.assertIn("NEXTAUTH_SECRET", r["manual"])
        self.assertIn("REDIS_X", r["manual"])
        self.assertNotIn("SOME_API_TOKEN", r["manual"])  # exists on prod: left alone

    def test_redact(self):
        out, names = p.redact_compose("      - 'A_SECRET=abc'\n      - 'B_SECRET=${B_SECRET:-}'\n      - 'C=1'")
        self.assertEqual(names, ["A_SECRET"])
        self.assertNotIn("abc", out)
        self.assertIn("${B_SECRET:-}", out)


class Compose(unittest.TestCase):
    def test_insert_positions(self):
        new, added = p.compose_insert(DEV, PROD)
        self.assertEqual(added, [("app", "NEW1"), ("app", "NEW2")])
        env = [v for v, _ in p.parse_env_lines(new)["app"]]
        self.assertEqual(env, ["A", "B", "NEW1", "C", "NEW2"])
        self.assertIn("#prod", new)  # build ref untouched
        self.assertNotIn("#dev", new)

    def test_only_added_lines_differ(self):
        new, _ = p.compose_insert(DEV, PROD)
        self.assertEqual(set(PROD.splitlines()) - set(new.splitlines()), set())
        self.assertEqual(len(new.splitlines()) - len(PROD.splitlines()), 2)

    def test_idempotent(self):
        new, _ = p.compose_insert(DEV, PROD)
        again, added = p.compose_insert(DEV, new)
        self.assertEqual(added, [])
        self.assertEqual(again, new)


class Org(unittest.TestCase):
    def test_diff_ignores_ids_and_dates(self):
        dev = {"id": 1, "name": "A", "creation_date": "x", "config": {"config": {"customization": {"general": {"watermark": False}}}}}
        prod = {"id": 9, "name": "A", "creation_date": "y", "config": {"config": {"customization": {"general": {"watermark": True}}}}}
        d = p.org_diff(dev, prod)
        self.assertEqual([x[0] for x in d], [("config", "config", "customization", "general", "watermark")])

    def test_diff_missing_and_lists(self):
        d = p.org_diff({"links": {"a": "1"}, "x": [1, 2]}, {"x": [1]})
        self.assertEqual({x[0] for x in d}, {("links", "a"), ("x",)})

    def test_clean_rewrites_host(self):
        self.assertEqual(p.clean_org({"u": "https://ilm-dev.mkausa.org", "id": 1}), {"u": "https://ilm.mkausa.org"})

    def test_plan_ops(self):
        dev = {"links": {"a": "b"}, "config": {"config": {
            "customization": {"general": {"watermark": False, "favicon_image": "f.png"}, "menu": {"items": [1]}},
            "admin_toggles": {"ai": {"disabled": False, "copilot_enabled": False}, "security": {"require_2fa": True}}}}}
        prod = {"links": {}, "config": {"config": {
            "customization": {"general": {"watermark": True, "favicon_image": "g.png"}, "menu": {"items": []}},
            "admin_toggles": {"ai": {"disabled": False, "copilot_enabled": True}, "security": {"require_2fa": False}}}}}
        diff = p.org_diff(p.clean_org(dev), p.clean_org(prod))
        ops, manual, images = p.plan_org_ops(diff, dev, prod)
        by = {o["label"]: o for o in ops}
        self.assertEqual(by["general.watermark"]["query"], {"watermark_enabled": "false"})
        self.assertEqual(by["admin_toggles.ai"]["query"], {"ai_enabled": "true", "copilot_enabled": "false"})
        self.assertEqual(by["customization.menu"]["json"], {"items": [1]})
        self.assertEqual(images, [("config", "config", "customization", "general", "favicon_image")])
        self.assertEqual(manual, [("config", "config", "admin_toggles", "security", "require_2fa")])

    def test_media_url(self):
        self.assertEqual(p.media_url("https://h", "org_1", "logos", "f.png"), "https://h/content/orgs/org_1/logos/f.png")


if __name__ == "__main__":
    unittest.main()
