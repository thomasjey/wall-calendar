"""The deploy tools: parameter checks (ADR-28) and what goes into the package."""

import unittest

from tools import build_package, deploy_params

A = "00000000-0000-0000-aaaa-000000000001"
B = "00000000-0000-0000-bbbb-000000000002"
C = "11111111-2222-3333-4444-555555555555"
GOOD = {"ALLOWED_OBJECT_IDS": f"{A}, {B}", "SIGNIN_CLIENT_ID": C, "SYNC_CLIENT_ID": C, "ADMIN_PRINCIPAL_ID": C,
        "ALERT_EMAIL": "admin@example.com"}


class DeployParams(unittest.TestCase):
    def test_good(self):
        p = deploy_params.build("prod", GOOD)["parameters"]
        self.assertEqual(p["allowedObjectIds"]["value"], [A, B])
        self.assertEqual((p["enrolmentOpen"]["value"], p["alwaysReady"]["value"]), (False, 1))
        self.assertEqual(deploy_params.build("dev", GOOD)["parameters"]["alwaysReady"]["value"], 0)
        self.assertTrue(deploy_params.build("dev", {**GOOD, "ENROLMENT_OPEN": "true"})["parameters"]["enrolmentOpen"]["value"])

    def test_refused(self):
        cases = {
            "empty list means everyone": {**GOOD, "ALLOWED_OBJECT_IDS": " , "},
            "missing list": {k: v for k, v in GOOD.items() if k != "ALLOWED_OBJECT_IDS"},
            "too many": {**GOOD, "ALLOWED_OBJECT_IDS": ",".join(f"00000000-0000-0000-0000-{i:012d}" for i in range(11))},
            "duplicates": {**GOOD, "ALLOWED_OBJECT_IDS": f"{A},{A}"},
            "not an ID": {**GOOD, "ALLOWED_OBJECT_IDS": f"{A},someone@example.com"},
            "upper case": {**GOOD, "ALLOWED_OBJECT_IDS": A.upper()},
            "bad client": {**GOOD, "SIGNIN_CLIENT_ID": "x"},
            "bad email": {**GOOD, "ALERT_EMAIL": "nobody"},
            "bad enrolment": {**GOOD, "ENROLMENT_OPEN": "yes"},
        }
        for name, environ in cases.items():
            with self.subTest(name), self.assertRaises(deploy_params.ParamError):
                deploy_params.build("dev", environ)
        with self.assertRaises(deploy_params.ParamError):
            deploy_params.build("staging", GOOD)

    def test_errors_never_echo_values(self):
        with self.assertRaises(deploy_params.ParamError) as cm:
            deploy_params.build("dev", {**GOOD, "ALERT_EMAIL": "secret-value"})
        self.assertNotIn("secret-value", str(cm.exception))


class Package(unittest.TestCase):
    def test_contents(self):
        names = [name for _, name in build_package.files_to_package()]
        self.assertIn("function_app.py", names)
        self.assertIn("host.json", names)
        self.assertIn("fwcal/cloud/web.py", names)
        self.assertIn("static/index.html", names)
        self.assertFalse([n for n in names if n.startswith(("tests/", "static/tests/", "spikes/", "tools/"))])
        self.assertFalse([n for n in names if n.endswith((".toml", ".json")) and n != "host.json"])


if __name__ == "__main__":
    unittest.main()
