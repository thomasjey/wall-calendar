import socket
import unittest

from fwcal import check, server
from fwcal.check import FAIL, OK, WARN

# /proc/net/tcp and tcp6 excerpts: 127.0.0.1:8765, 0.0.0.0:22, 127.0.0.53:53,
# 0.0.0.0:8080, a connected (non-listening) socket, and [::]:22.
TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:223D 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1
   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2 1
   2: 3500007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000   991        0 3 1
   3: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 4 1
   4: 0100007F:223D 0100007F:C350 01 00000000:00000000 00:00000000 00000000     0        0 5 1
"""
TCP6 = """  sl  local_address                         remote_address                        st
   0: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A 0
   1: 00000000000000000000000001000000:1F91 00000000000000000000000000000000:0000 0A 0
"""
UDP = """  sl  local_address rem_address   st
   0: 00000000:0044 00000000:0000 07 0
   1: 00000000:14E9 00000000:0000 07 0
"""


class ProcNet(unittest.TestCase):
    def test_parse_ipv4_and_ipv6(self):
        self.assertEqual(check.parse_proc_net(TCP, udp=False),
                         [("127.0.0.1", 8765), ("0.0.0.0", 22), ("127.0.0.53", 53), ("0.0.0.0", 8080)])
        self.assertEqual(check.parse_proc_net(TCP6, udp=False), [("::", 22), ("::1", 8081)])
        self.assertEqual(check.parse_proc_net(UDP, udp=True), [("0.0.0.0", 68), ("0.0.0.0", 5353)])

    def test_evaluate(self):
        tcp = check.parse_proc_net(TCP, udp=False) + check.parse_proc_net(TCP6, udp=False)
        results = {text: level for level, text in
                   check.evaluate_listeners(tcp, check.parse_proc_net(UDP, udp=True), 8765)}
        self.assertEqual(results["tcp 127.0.0.1:8765 (web)"], OK)
        self.assertEqual(results["tcp 0.0.0.0:22 (ssh)"], OK)
        self.assertEqual(results["tcp 127.0.0.53:53: unexpected loopback listener"], WARN)
        self.assertEqual(results["tcp 0.0.0.0:8080: unexpected network listener"], FAIL)
        self.assertEqual(results["tcp ::1:8081: unexpected loopback listener"], WARN)
        self.assertEqual(results["udp 0.0.0.0:68 (DHCP client)"], OK)
        self.assertEqual(results["udp 0.0.0.0:5353: unexpected network listener"], FAIL)  # avahi

    def test_web_port_on_all_interfaces_fails(self):
        results = check.evaluate_listeners([("0.0.0.0", 8765)], [], 8765)
        self.assertIn((FAIL, "tcp 0.0.0.0:8765: web port not on loopback"), results)
        self.assertIn((WARN, "nothing listening on 127.0.0.1:8765"), results)


class Modes(unittest.TestCase):
    def test_check_mode(self):
        self.assertEqual(check.check_mode("token", 0o100600, forbidden=0o177)[0], OK)
        self.assertEqual(check.check_mode("token", 0o100640, forbidden=0o177)[0], FAIL)
        self.assertEqual(check.check_mode("config", 0o100640, forbidden=0o137)[0], OK)
        self.assertEqual(check.check_mode("config", 0o100644, forbidden=0o137)[0], FAIL)
        self.assertEqual(check.check_mode("dir", 0o040700, forbidden=0o077)[0], OK)


class SocketActivation(unittest.TestCase):
    def test_adopts_loopback_socket(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen()
        adopted = server.adopt_socket(s.detach())
        try:
            self.assertEqual(adopted.getsockname()[0], "127.0.0.1")
        finally:
            adopted.close()

    def test_refuses_non_loopback_and_udp(self):
        for family, kind, addr in ((socket.AF_INET, socket.SOCK_STREAM, "0.0.0.0"),
                                   (socket.AF_INET, socket.SOCK_DGRAM, "127.0.0.1")):
            s = socket.socket(family, kind)
            s.bind((addr, 0))
            with self.subTest(addr=addr, kind=kind), self.assertRaises(RuntimeError):
                server.adopt_socket(s.detach())

    def test_env_must_name_this_process(self):
        import os

        os.environ.update(LISTEN_PID="1", LISTEN_FDS="1")
        with self.assertRaises(RuntimeError):
            server.systemd_socket_fd()
        self.assertNotIn("LISTEN_PID", os.environ)
        self.assertIsNone(server.systemd_socket_fd())


if __name__ == "__main__":
    unittest.main()
