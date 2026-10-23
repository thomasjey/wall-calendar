"""The cloud service (fwcal.cloud) without Azure: fake HTTP, no network."""

import base64
import importlib.util
import json
import unittest
from datetime import UTC, datetime, timedelta

from fwcal import store
from fwcal.config import ConfigError
from tests.fakes import FakeResponse

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("requests", "tzdata"))
OID_A = "00000000-0000-0000-aaaa-000000000001"
OID_B = "00000000-0000-0000-bbbb-000000000002"
OID_X = "00000000-0000-0000-cccc-000000000003"
CONSUMER = "9188040d-6c67-4c5b-b112-36a304b66dad"
HOST = "app.example.net"
VAULT = "https://kv-test.vault.azure.net"
CONTAINER = "https://sttest.blob.core.windows.net/data"
CLIENT = "11111111-2222-3333-4444-555555555555"
NOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)

CONFIG_TOML = f"""
expected_account = "viewer@example.com"
timezone = "America/New_York"
[[calendars]]
key = "home"
name = "Home"
color = "#7FB3FF"
graph_id = "ID-HOME"
[[calendars]]
key = "health"
name = "Health"
color = "#AFA9EC"
graph_id = "ID-HEALTH"
detail = "titles"
[access]
allowed = ["{OID_A}", "{OID_B}"]
admins = ["{OID_A}"]
max_allowed = 3
"""


class FakeHTTP:
    """routes: list of (method, url predicate, response or callable(method, url, kwargs))."""

    def __init__(self, routes=()):
        self.routes = list(routes)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for m, match, resp in self.routes:
            if m == method and match(url):
                return resp(method, url, kw) if callable(resp) else resp
        return FakeResponse(404, {"error": "not found"})

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


def principal_header(oid=OID_A, tid=CONSUMER, auth_typ="aad"):
    data = {"auth_typ": auth_typ, "claims": [
        {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": oid},
        {"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": tid},
        {"typ": "name", "val": "Someone"}]}
    return base64.b64encode(json.dumps(data).encode()).decode()


def id_token(**claims):
    base = {"iss": f"https://login.microsoftonline.com/{CONSUMER}/v2.0", "tid": CONSUMER, "aud": CLIENT,
            "nonce": "n1", "exp": NOW.timestamp() + 600, "preferred_username": "Viewer@Example.com"}
    base.update(claims)
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc(base)}.sig"


class FakeIdentity:
    client_id = None

    def __init__(self, name="sync"):
        self.name = name

    def token(self, resource):
        return f"tok-{self.name}-{resource}"

    def assertion(self):
        return f"assertion-{self.name}"


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class AzureRestTest(unittest.TestCase):
    def setUp(self):
        from fwcal.cloud import azure

        self.az = azure

    def test_urls_must_stay_on_the_service(self):
        ok = self.az.https_url(VAULT + "/", ".vault.azure.net")
        self.assertEqual(ok, VAULT)
        for bad in ("http://kv.vault.azure.net", "https://evil.example/x.vault.azure.net", "https://kv.vault.azure.net.evil.example",
                    "https://u@kv.vault.azure.net", "https://kv.vault.azure.net:8443", "https://kv.vault.azure.net/?x=1"):
            with self.subTest(bad=bad), self.assertRaises(self.az.AzureError):
                self.az.https_url(bad, ".vault.azure.net")

    def test_identity_endpoint_must_be_loopback_or_link_local(self):
        for ok in ("http://localhost:4141/msi", "http://127.0.0.1:8081/msi/token", "http://169.254.255.2:8081/msi/token",
                   "http://[fe80::1]:8081/msi/token"):
            with self.subTest(ok=ok):
                self.az.ManagedIdentity(FakeHTTP(), ok, "h")
        for bad in ("https://evil.example/msi", "http://10.0.0.4/msi", "http://20.1.2.3/msi", "http://169.254.1.1.evil.example/",
                    "ftp://127.0.0.1/msi", "http:///msi"):
            with self.subTest(bad=bad), self.assertRaises(self.az.AzureError):
                self.az.ManagedIdentity(FakeHTTP(), bad, "h")
        with self.assertRaises(self.az.AzureError) as cm:
            self.az.ManagedIdentity(FakeHTTP(), "https://evil.example/msi", "h")
        self.assertIn("evil.example", str(cm.exception))  # the host is named; the header never is

    def test_identity_tokens_are_cached(self):
        http = FakeHTTP([("GET", lambda u: u.startswith("http://localhost:4141/msi"),
                          FakeResponse(200, dict(access_token="AT", expires_on="2000003600")))])
        mi = self.az.ManagedIdentity(http, "http://localhost:4141/msi", "secret-header", OID_B, clock=lambda: 2000000000)
        self.assertEqual(mi.token(self.az.KEY_VAULT), "AT")
        self.assertEqual(mi.token(self.az.KEY_VAULT), "AT")
        self.assertEqual(len(http.calls), 1)
        _, url, kw = http.calls[0]
        self.assertIn("client_id=" + OID_B, url)
        self.assertEqual(kw["headers"], {"X-IDENTITY-HEADER": "secret-header"})
        self.assertFalse(kw["allow_redirects"])

    def test_key_vault_get_set_disable(self):
        http = FakeHTTP([
            ("GET", lambda u: "/secrets/cfg?" in u, FakeResponse(200, {"value": "V", "id": f"{VAULT}/secrets/cfg/{'a' * 32}"})),
            ("PUT", lambda u: "/secrets/cfg?" in u, FakeResponse(200, {"id": f"{VAULT}/secrets/cfg/{'b' * 32}"})),
            ("PATCH", lambda u: f"/secrets/cfg/{'a' * 32}?" in u, FakeResponse(200, {})),
        ])
        kv = self.az.KeyVault(http, VAULT, FakeIdentity())
        self.assertEqual(kv.get("cfg"), self.az.Secret("V", "a" * 32))
        self.assertEqual(kv.set("cfg", "new", "text"), "b" * 32)
        kv.disable("cfg", "a" * 32)
        self.assertEqual(http.calls[2][2]["json"], {"attributes": {"enabled": False}})
        self.assertTrue(all(c[2]["headers"]["Authorization"].startswith("Bearer tok-") for c in http.calls))
        for bad in ("../x", "a/b", ""):
            with self.subTest(bad=bad), self.assertRaises(self.az.AzureError):
                kv.get(bad)
        with self.assertRaises(self.az.AzureError) as cm:
            self.az.KeyVault(FakeHTTP(), VAULT, FakeIdentity()).get("missing")
        self.assertEqual(cm.exception.status, 404)

    def test_blobs(self):
        http = FakeHTTP([
            ("GET", lambda u: u.endswith("/data/a.json"),
             lambda m, u, kw: FakeResponse(304, raw=b"") if kw["headers"].get("If-None-Match") == '"e1"'
             else FakeResponse(200, raw=b"{}", headers={"ETag": '"e1"'})),
            ("PUT", lambda u: u.endswith("/data/a.json"), FakeResponse(201, raw=b"")),
            ("DELETE", lambda u: u.endswith("/data/a.json"), FakeResponse(202, raw=b"")),
        ])
        blobs = self.az.BlobContainer(http, CONTAINER, FakeIdentity())
        self.assertEqual(blobs.get("a.json"), (b"{}", '"e1"'))
        self.assertEqual(blobs.get("a.json", '"e1"'), (None, '"e1"'))
        self.assertEqual(blobs.get("b.json"), (None, None))
        blobs.put("a.json", b"{}")
        self.assertTrue(blobs.delete("a.json"))
        self.assertFalse(blobs.delete("b.json"))
        for bad in ("../x", "A.json", "/x"):
            with self.subTest(bad=bad), self.assertRaises(self.az.AzureError):
                blobs.get(bad)
        with self.assertRaises(self.az.AzureError):
            self.az.BlobContainer(http, "https://sttest.blob.core.windows.net/a/b", FakeIdentity())


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class OAuthTest(unittest.TestCase):
    def setUp(self):
        from fwcal import netauth
        from fwcal.cloud import oauth

        self.oauth, self.netauth = oauth, netauth

    def token_http(self, status, body):
        return FakeHTTP([("POST", lambda u: u == self.oauth.TOKEN_URL, FakeResponse(status, body))])

    def test_authorize_url(self):
        url = self.oauth.authorize_url(CLIENT, f"https://{HOST}/admin/consent/callback", state="s", nonce="n",
                                       challenge="c", login_hint="viewer@example.com")
        self.assertTrue(url.startswith("https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"))
        for part in ("code_challenge_method=S256", "response_type=code", "state=s", "nonce=n",
                     "scope=Calendars.Read+offline_access+openid+profile"):
            self.assertIn(part, url)

    def test_refresh_sends_the_assertion_and_checks_scopes(self):
        http = self.token_http(200, dict(access_token="AT", refresh_token="RT2", scope="Calendars.Read openid profile"))
        tokens = self.oauth.refresh(http, CLIENT, "RT1", "ASSERT")
        self.assertEqual((tokens.access_token, tokens.refresh_token), ("AT", "RT2"))
        form = http.calls[0][2]["data"]
        self.assertEqual((form["client_assertion"], form["grant_type"], form["refresh_token"]), ("ASSERT", "refresh_token", "RT1"))
        self.assertNotIn("client_secret", form)
        with self.assertRaises(self.netauth.AuthError):
            self.oauth.refresh(self.token_http(200, dict(access_token="AT", scope="Calendars.Read Mail.Read")),
                               CLIENT, "RT1", "A")

    def test_refresh_errors(self):
        with self.assertRaises(self.netauth.ReauthRequired):
            self.oauth.refresh(self.token_http(400, {"error": "invalid_grant", "error_codes": [70000],
                                                     "error_description": "secret detail"}), CLIENT, "RT", "A")
        with self.assertRaises(self.netauth.AuthError) as cm:
            self.oauth.refresh(self.token_http(401, {"error": "invalid_client", "error_codes": [700027],
                                                     "error_description": "secret detail"}), CLIENT, "RT", "A")
        self.assertNotIsInstance(cm.exception, self.netauth.ReauthRequired)
        self.assertNotIn("secret detail", str(cm.exception))

    def consent(self, **over):
        fields = dict(access_token="AT", refresh_token="RT", scope="Calendars.Read openid profile", id_token=id_token())
        fields.update(over)
        return self.oauth.Tokens(**fields)

    def test_verify_consent_accepts_only_the_viewer(self):
        verify = lambda t, nonce="n1": self.oauth.verify_consent(
            t, client_id=CLIENT, nonce=nonce, expected_account="viewer@example.com", now=NOW.timestamp())
        self.assertEqual(verify(self.consent()), "viewer@example.com")
        bad = {
            "other account": self.consent(id_token=id_token(preferred_username="someone@example.com")),
            "work tenant": self.consent(id_token=id_token(tid="72f988bf-86f1-41af-91ab-2d7cd011db47")),
            "issuer": self.consent(id_token=id_token(iss="https://evil.example/v2.0")),
            "audience": self.consent(id_token=id_token(aud=OID_X)),
            "expired": self.consent(id_token=id_token(exp=NOW.timestamp() - 1)),
            "extra scope": self.consent(scope="Calendars.Read Mail.Read"),
            "no refresh token": self.consent(refresh_token=None),
            "no id token": self.consent(id_token=None),
            "malformed": self.consent(id_token="abc"),
        }
        for name, tokens in bad.items():
            with self.subTest(name), self.assertRaises(self.netauth.AuthError):
                verify(tokens)
        with self.assertRaises(self.netauth.AuthError):
            verify(self.consent(), nonce="other")

    def test_pkce(self):
        import hashlib

        v, c = self.oauth.pkce_pair()
        self.assertGreaterEqual(len(v), 43)
        self.assertEqual(c, self.oauth.b64url(hashlib.sha256(v.encode()).digest()))


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class SettingsTest(unittest.TestCase):
    def setUp(self):
        from fwcal.cloud import settings

        self.s = settings

    def test_parse(self):
        st = self.s.parse_settings(CONFIG_TOML)
        self.assertEqual(st.access.allowed, {OID_A, OID_B})
        self.assertEqual(st.access.admins, {OID_A})
        self.assertEqual([c.key for c in st.config.calendars], ["home", "health"])
        self.assertEqual(st.tz.key, "America/New_York")

    def test_invalid_documents_are_refused(self):
        cases = {
            "no access": CONFIG_TOML.split("[access]")[0],
            "empty list": CONFIG_TOML.replace(f'["{OID_A}", "{OID_B}"]', "[]"),
            "too many": CONFIG_TOML.replace("max_allowed = 3", "max_allowed = 1"),
            "cap": CONFIG_TOML.replace("max_allowed = 3", "max_allowed = 50"),
            "upper case": CONFIG_TOML.replace(f'"{OID_B}"]', f'"{OID_B.upper()}"]'),
            "not an ID": CONFIG_TOML.replace(f'"{OID_B}"]', '"bob"]'),
            "admin not allowed": CONFIG_TOML.replace(f'admins = ["{OID_A}"]', f'admins = ["{OID_X}"]'),
            "unknown key": CONFIG_TOML.replace("max_allowed = 3", "max_allowed = 3\nopen = true"),
            "no timezone": CONFIG_TOML.replace('timezone = "America/New_York"\n', ""),
            "bad timezone": CONFIG_TOML.replace("America/New_York", "Nowhere/Land"),
            "no viewer": CONFIG_TOML.replace('expected_account = "viewer@example.com"\n', ""),
            "bad detail": CONFIG_TOML.replace('detail = "titles"', 'detail = "everything"'),
            "not toml": "[[",
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ConfigError):
                self.s.parse_settings(text)

    def test_enrolment_window(self):
        until = (NOW + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        st = self.s.parse_settings(CONFIG_TOML + f'enrolment_until = "{until}"\n')
        self.assertTrue(st.access.enrolment_active(NOW))
        self.assertFalse(st.access.enrolment_active(NOW + timedelta(minutes=21)))
        far = (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertFalse(self.s.parse_settings(CONFIG_TOML + f'enrolment_until = "{far}"\n')
                         .access.enrolment_active(NOW))
        self.assertFalse(self.s.parse_settings(CONFIG_TOML).access.enrolment_active(NOW))

    def test_cache_refreshes_keeps_last_good_briefly_then_fails_closed(self):
        t = [0.0]
        texts = [CONFIG_TOML]

        def load():
            if isinstance(texts[0], Exception):
                raise texts[0]
            return texts[0]

        cache = self.s.SettingsCache(load, ttl=300, grace=1800, clock=lambda: t[0])
        first = cache.get()
        t[0] = 100
        self.assertIs(cache.get(), first)
        texts[0] = RuntimeError("vault down")
        t[0] = 400
        self.assertIs(cache.get(), first)  # within grace
        t[0] = 2000
        with self.assertRaises(self.s.SettingsUnavailable):
            cache.get()
        texts[0] = "[["  # an invalid document never replaces a good one silently: it fails closed
        t[0] = 2100
        with self.assertRaises(self.s.SettingsUnavailable):
            cache.get()


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class PrincipalTest(unittest.TestCase):
    def test_parse(self):
        from fwcal.cloud import principal as p

        self.assertEqual(p.parse(principal_header()), p.Principal(OID_A, CONSUMER))
        self.assertEqual(p.parse(principal_header(oid=OID_A.upper())).oid, OID_A)
        for bad in (None, "", "not base64!", base64.b64encode(b"[]").decode(), principal_header(auth_typ="google"),
                    principal_header(oid="bob"), principal_header(tid=""), "A" * 20000):
            with self.subTest(bad=str(bad)[:20]):
                self.assertIsNone(p.parse(bad))
        self.assertNotIn(OID_A, p.Principal(OID_A, CONSUMER).log_id())


class MemoryBlobs:
    def __init__(self):
        self.data, self.n = {}, 0
        self.fail = False

    def get(self, name, etag=None):
        if self.fail:
            from fwcal.cloud.azure import AzureError

            raise AzureError("down", 503)
        if name not in self.data:
            return None, None
        body, tag = self.data[name]
        return (None, tag) if etag == tag else (body, tag)

    def put(self, name, data, content_type="application/json"):
        self.n += 1
        self.data[name] = (data, f'"{self.n}"')

    def delete(self, name):
        return self.data.pop(name, None) is not None


class MemoryVault:
    def __init__(self, secrets=None):
        self.versions = {}  # name -> list of [value, version, enabled]
        for name, value in (secrets or {}).items():
            self.set(name, value, "x")

    def get(self, name):
        from fwcal.cloud.azure import AzureError, Secret

        live = [v for v in self.versions.get(name, []) if v[2]]
        if not live:
            raise AzureError("missing", 404)
        return Secret(live[-1][0], live[-1][1])

    def set(self, name, value, content_type):
        version = f"{len(self.versions.get(name, [])) + 1:032x}"
        self.versions.setdefault(name, []).append([value, version, True])
        return version

    def disable(self, name, version):
        for v in self.versions[name]:
            if v[1] == version:
                v[2] = False


def payload(generated="2026-10-22T17:58:00Z", status="ok", auth="ok"):
    return {"schema": 1, "source": "graph", "generatedAt": generated, "auth": auth,
            "window": {"start": "2026-10-15", "end": "2026-11-27"},
            "calendars": [{"key": "home", "name": "Home", "color": "#7FB3FF", "status": status,
                           "lastSuccessAt": generated, "truncated": False}],
            "events": [{"id": "0123456789abcdef", "cal": "home", "title": "Dinner", "location": "", "notes": "",
                        "private": False, "allDay": False, "start": "2026-10-22T23:00:00Z", "end": "2026-10-23T00:00:00Z"}]}


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class StorageAndTokensTest(unittest.TestCase):
    def test_events_cache(self):
        from fwcal.cloud.storage import BlobEventStore, EventsCache

        blobs = MemoryBlobs()
        cache = EventsCache(blobs)
        self.assertIn(b'"no_data"', cache.get()[0])
        BlobEventStore(blobs).save(payload())
        body, etag = cache.get()
        self.assertEqual(json.loads(body), store.validate(payload()))
        self.assertEqual(cache.get(), (body, etag))
        blobs.fail = True
        self.assertEqual(cache.get(), (body, etag))  # last good copy through a storage blip
        blobs.fail = False
        blobs.put("events.json", b'{"schema": 99}')
        self.assertEqual(cache.get(), (body, etag))  # an invalid blob never replaces good data

    def test_consent_state_is_single_use(self):
        from fwcal.cloud.storage import ConsentStates

        states = ConsentStates(MemoryBlobs())
        states.put("s1", {"oid": OID_A})
        self.assertEqual(states.take("s1"), {"oid": OID_A})
        self.assertIsNone(states.take("s1"))
        self.assertIsNone(states.take("unknown"))
        self.assertIsNone(states.take(""))

    def test_tokens_rotate_and_errors(self):
        from fwcal import netauth
        from fwcal.cloud import oauth, tokens

        vault = MemoryVault({tokens.REFRESH_SECRET: "RT1"})
        seen = {}

        def fake_refresh(session, client_id, refresh_token, assertion):
            seen.update(rt=refresh_token, assertion=assertion)
            return oauth.Tokens("AT", "RT2", "Calendars.Read")

        orig, oauth.refresh = oauth.refresh, fake_refresh
        try:
            provider = tokens.CloudTokens(vault, FakeIdentity(), CLIENT)
            self.assertEqual(provider(None, None), "AT")
        finally:
            oauth.refresh = orig
        self.assertEqual(seen, {"rt": "RT1", "assertion": "assertion-sync"})
        self.assertEqual([(v[0], v[2]) for v in vault.versions[tokens.REFRESH_SECRET]], [("RT1", False), ("RT2", True)])
        with self.assertRaises(netauth.ReauthRequired):
            tokens.CloudTokens(MemoryVault(), FakeIdentity(), CLIENT)(None, None)


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class WebTest(unittest.TestCase):
    def setUp(self):
        from fwcal.cloud import settings, web
        from fwcal.cloud.storage import BlobEventStore, EventsCache

        self.web_mod = web
        self.blobs = MemoryBlobs()
        BlobEventStore(self.blobs).save(payload())
        self.config_text = [CONFIG_TOML]
        self.consent = FakeConsent()
        self.web = web.Web(
            static={"/": (b"<html>page</html>", "text/html; charset=utf-8"), "/js/app.js": (b"js", "text/javascript")},
            settings=settings.SettingsCache(lambda: self.config_text[0], ttl=0, grace=0),
            events=EventsCache(self.blobs), hostnames=frozenset({HOST}), consent=self.consent, now=lambda: NOW)

    def get(self, path, oid=OID_A, method="GET", **headers):
        h = {"host": HOST, **{k.replace("_", "-"): v for k, v in headers.items()}}
        if oid is not None:
            h["x-ms-client-principal"] = principal_header(oid) if isinstance(oid, str) else oid
        return self.web.handle(self.web_mod.Request(method, path, h, headers.pop("query", {}) if False else {}))

    def test_allowed_person_gets_the_page_and_data(self):
        r = self.get("/")
        self.assertEqual((r.status, r.body), (200, b"<html>page</html>"))
        self.assertIn("require-trusted-types-for 'script'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        events = self.get("/api/events")
        self.assertEqual(events.status, 200)
        self.assertEqual(self.get("/api/events", if_none_match=events.headers["ETag"]).status, 304)
        self.assertEqual(json.loads(self.get("/api/photos").body), {"photos": []})
        self.assertEqual(json.loads(self.get("/api/settings").body)["clock"], "12h")
        self.assertEqual(self.get("/nope").status, 404)

    def test_deny_by_default(self):
        cases = {
            "no principal": self.get("/", oid=None),
            "malformed principal": self.get("/", oid="garbage"),
            "not allowlisted": self.get("/", oid=OID_X),
            "wrong tenant": self.get("/", oid=principal_header(tid="72f988bf-86f1-41af-91ab-2d7cd011db47")),
            "cross-site API": self.get("/api/events", sec_fetch_site="cross-site", sec_fetch_mode="cors",
                                       sec_fetch_dest="empty"),
            "cross-site embed": self.get("/", sec_fetch_site="cross-site", sec_fetch_mode="no-cors",
                                         sec_fetch_dest="iframe"),
        }
        for name, r in cases.items():
            with self.subTest(name):
                self.assertEqual(r.status, 403)
                self.assertNotIn(b"Dinner", r.body)
        self.assertEqual(self.get("/", host="evil.example").status, 421)
        self.assertEqual(self.get("/", method="POST").status, 405)

    def test_navigation_back_from_sign_in_is_allowed(self):
        r = self.get("/", sec_fetch_site="cross-site", sec_fetch_mode="navigate", sec_fetch_dest="document")
        self.assertEqual(r.status, 200)

    def test_unreadable_config_denies_everyone(self):
        self.config_text[0] = "[["
        r = self.get("/api/events")
        self.assertEqual(r.status, 503)
        self.assertNotIn(b"Dinner", r.body)

    def test_head(self):
        r = self.get("/", method="HEAD")
        self.assertEqual((r.status, r.body, r.headers["Content-Length"]), (200, b"", "17"))

    def test_enrolment(self):
        self.assertEqual(self.get("/enrol", oid=OID_X).status, 403)
        until = (NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.config_text[0] = CONFIG_TOML + f'enrolment_until = "{until}"\n'
        r = self.get("/enrol", oid=OID_X)
        self.assertEqual(r.status, 200)
        self.assertIn(OID_X.encode(), r.body)
        self.assertEqual(self.get("/api/events", oid=OID_X).status, 403)  # still no data

    def test_admin_routes(self):
        self.assertEqual(self.get("/admin/consent", oid=OID_B).status, 403)
        r = self.get("/admin/consent")
        self.assertEqual((r.status, r.headers["Location"]), (302, "https://login.example/authorize"))
        ok = self.web.handle(self.web_mod.Request("GET", "/admin/consent/callback",
                                                  {"host": HOST, "x-ms-client-principal": principal_header()},
                                                  {"state": "s", "code": "c"}))
        self.assertEqual(ok.status, 200)
        self.consent.fail = True
        bad = self.web.handle(self.web_mod.Request("GET", "/admin/consent/callback",
                                                   {"host": HOST, "x-ms-client-principal": principal_header()},
                                                   {"state": "s", "code": "c"}))
        self.assertEqual(bad.status, 400)

    def test_health_has_no_content(self):
        h = json.loads(self.get("/api/health").body)
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["syncAgeSeconds"], 120)
        self.assertNotIn("Dinner", json.dumps(h))


class FakeConsent:
    fail = False

    def start(self, who, host, viewer):
        return "https://login.example/authorize"

    def finish(self, who, host, query, viewer):
        from fwcal.cloud.consent import ConsentError

        if self.fail:
            raise ConsentError("Not connected.")
        return viewer


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class ConsentTest(unittest.TestCase):
    def setUp(self):
        from fwcal.cloud import consent, oauth, tokens
        from fwcal.cloud.principal import Principal
        from fwcal.cloud.storage import ConsentStates

        self.c_mod, self.oauth, self.tokens = consent, oauth, tokens
        self.admin, self.other = Principal(OID_A, CONSUMER), Principal(OID_B, CONSUMER)
        self.vault = MemoryVault({tokens.REFRESH_SECRET: "OLD"})
        self.t = [NOW.timestamp()]
        self.redeemed = []
        self.consent = consent.Consent(states=ConsentStates(MemoryBlobs()), vault=self.vault,
                                       sync_identity=FakeIdentity(), client_id=CLIENT, session=None,
                                       clock=lambda: self.t[0])

    def start(self):
        from urllib.parse import parse_qs, urlsplit

        url = self.consent.start(self.admin, HOST, "viewer@example.com")
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.assertEqual(q["redirect_uri"], f"https://{HOST}/admin/consent/callback")
        return q

    def finish(self, q, who=None, account="Viewer@Example.com", **query):
        def fake_redeem(session, client_id, *, code, redirect_uri, verifier, assertion):
            self.redeemed.append((code, verifier, assertion))
            return self.oauth.Tokens("AT", "NEWRT", "Calendars.Read openid profile",
                                     id_token(nonce=q["nonce"], preferred_username=account))

        orig, self.oauth.redeem_code = self.oauth.redeem_code, fake_redeem
        try:
            return self.consent.finish(who or self.admin, HOST, {"state": q["state"], "code": "CODE", **query},
                                       "viewer@example.com")
        finally:
            self.oauth.redeem_code = orig

    def test_success_stores_token_and_disables_previous(self):
        q = self.start()
        self.assertEqual(self.finish(q), "viewer@example.com")
        self.assertEqual(self.redeemed[0][2], "assertion-sync")
        versions = self.vault.versions[self.tokens.REFRESH_SECRET]
        self.assertEqual([(v[0], v[2]) for v in versions], [("OLD", False), ("NEWRT", True)])

    def refused(self, name, call):
        with self.subTest(name), self.assertRaises(self.c_mod.ConsentError):
            call()

    def test_refusals(self):
        q = self.start()
        self.refused("another admin's state", lambda: self.finish(q, who=self.other))
        q = self.start()
        self.finish(q)
        self.refused("reused state", lambda: self.finish(q))
        q = self.start()
        self.t[0] += 601
        self.refused("expired", lambda: self.finish(q))
        self.t[0] = NOW.timestamp()
        q = self.start()
        self.refused("wrong account", lambda: self.finish(q, account="someone@example.com"))
        q = self.start()
        self.refused("sign-in error", lambda: self.finish(q, error="access_denied"))
        self.refused("forged state", lambda: self.finish({"state": "forged", "nonce": "n"}))
        live = [v[0] for v in self.vault.versions[self.tokens.REFRESH_SECRET] if v[2]]
        self.assertEqual(live, ["NEWRT"])  # only the one legitimate consent was stored


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class RunSyncTest(unittest.TestCase):
    def test_no_calendars_is_a_deliberate_skip(self):
        from fwcal.cloud import app
        from fwcal.cloud.settings import SettingsCache

        no_calendars = CONFIG_TOML.split("[[calendars]]")[0] + "[access]" + CONFIG_TOML.split("[access]")[1]

        class Services:
            settings = SettingsCache(lambda: no_calendars)
            events_store = tokens = session = None

        orig, app._services = app._services, Services()
        try:
            with self.assertLogs("fwcal.cloud", "INFO") as logs:
                self.assertEqual(app.run_sync(), 0)
        finally:
            app._services = orig
        self.assertIn("sync skipped: no calendars configured", logs.output[0])


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class StartupFailureTest(unittest.TestCase):
    def test_setup_failure_is_a_short_answer_with_headers(self):
        from fwcal.cloud import app

        def broken():
            raise RuntimeError("app setting FWCAL_X is not set")

        orig_build, orig_services = app.build, app._services
        app.build, app._services = broken, None
        try:
            with self.assertLogs("fwcal.cloud", "ERROR"):
                r = app._handle(None)
        finally:
            app.build, app._services = orig_build, orig_services
        self.assertEqual((r.status, r.body), (503, b"Not available right now\n"))
        self.assertIn("Content-Security-Policy", r.headers)
        self.assertNotIn(b"FWCAL", r.body)


@unittest.skipUnless(HAVE_DEPS, "requests/tzdata not installed")
class NoMsalTest(unittest.TestCase):
    def test_cloud_never_imports_msal(self):
        # ADR-30: a fresh interpreter loads the whole cloud package and the sync.
        import subprocess
        import sys

        from fwcal.paths import REPO_ROOT

        code = ("import sys; import fwcal.cloud.app, fwcal.sync; "
                "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('msal', 'fwcal.auth') or m == 'fwcal.auth'); "
                "print(bad); sys.exit(1 if bad else 0)")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
                                check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
