"""Keeps the Raspberry Pi deployment files consistent with the code (DESIGN §9)."""

import json
import re
import unittest

from fwcal.config import Config
from fwcal.paths import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
PORT = Config().port


def read(rel):
    return (DEPLOY / rel).read_text(encoding="utf-8")


class Deploy(unittest.TestCase):
    def test_socket_is_loopback_on_configured_port(self):
        self.assertRegex(read("systemd/fwcal-web.socket"), rf"(?m)^ListenStream=127\.0\.0\.1:{PORT}$")

    def test_kiosk_and_policy_point_at_the_same_origin(self):
        origin = f"http://127.0.0.1:{PORT}"
        policy = json.loads(read("chromium/fwcal-policy.json"))
        self.assertEqual(policy["URLBlocklist"], ["*"])
        self.assertEqual(policy["URLAllowlist"], [origin])
        self.assertEqual(policy["DeveloperToolsAvailability"], 2)
        self.assertIn(f"--app={origin}/", read("kiosk/autostart"))

    def test_no_remote_debugging(self):
        code = [line for line in read("kiosk/autostart").splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if "remote-debugging" in line])

    def test_web_service_sandbox(self):
        unit = read("systemd/fwcal-web.service")
        for line in ("User=fwcal-web", "PrivateNetwork=yes", "IPAddressDeny=any", "ProtectSystem=strict",
                     "InaccessiblePaths=-/var/lib/fwcal/auth", "NoNewPrivileges=yes", "CapabilityBoundingSet=",
                     "Requires=fwcal-web.socket"):
            self.assertIn(line, unit.splitlines(), line)
        self.assertNotIn("ReadWritePaths", unit)

    def test_sync_service_writes_only_its_directories(self):
        unit = read("systemd/fwcal-sync.service")
        self.assertIn("User=fwcal-sync", unit.splitlines())
        self.assertIn("ReadWritePaths=/var/lib/fwcal/auth /var/lib/fwcal/data", unit.splitlines())
        self.assertIn("UMask=0027", unit.splitlines())

    def test_directory_modes(self):
        rows = {parts[1]: parts[2:5] for parts in (line.split() for line in read("tmpfiles.d/fwcal.conf").splitlines())
                if parts and parts[0] == "d"}
        self.assertEqual(rows["/var/lib/fwcal/auth"], ["0700", "fwcal-sync", "fwcal-sync"])
        self.assertEqual(rows["/var/lib/fwcal/data"], ["2750", "fwcal-sync", "fwcal-web"])
        self.assertEqual(rows["/etc/fwcal"], ["0750", "root", "fwcal"])

    def test_firewall_default_drop(self):
        rules = read("nftables.conf")
        self.assertRegex(rules, r"hook input priority filter; policy drop;")
        self.assertNotRegex(rules, rf"dport {PORT}\b")

    def test_ssh_keys_only(self):
        conf = read("sshd_config.d/fwcal.conf").splitlines()
        for line in ("PasswordAuthentication no", "PermitRootLogin no", "AuthenticationMethods publickey"):
            self.assertIn(line, conf)

    def test_setup_mentions_every_deploy_file(self):
        setup = read("SETUP.md")
        for path in DEPLOY.rglob("*"):
            if path.is_file() and path.name != "SETUP.md":
                rel = path.relative_to(DEPLOY).as_posix()
                with self.subTest(file=rel):
                    self.assertTrue(re.search(re.escape(rel), setup), rel)


if __name__ == "__main__":
    unittest.main()
