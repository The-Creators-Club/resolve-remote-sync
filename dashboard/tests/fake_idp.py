"""A tiny, real OIDC provider on a real socket, for test_oidc.py.

A threaded http.server rather than a mocked transport, the same choice
fake_truenas.py and fake_synology.py make: the point is to exercise
`requests`, the discovery document, the JWKS fetch and PyJWT's verification
end to end, and a mock of the HTTP layer would exercise none of it.

It signs with a freshly generated RS256 key, so nothing here is a credential
and nothing has to be checked in.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


class FakeIdP:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"
        # What the next code exchange hands back. Tests mutate this to model a
        # provider that omits a claim, signs with the wrong key, and so on.
        self.claims: dict = {}
        self.issued_forms: list[dict] = []
        self.token_status = 200
        self.sign_with_wrong_key = False
        self.base_url = ""
        self._server = None
        self._thread = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> "FakeIdP":
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):        # keep pytest output clean
                pass

            def _send(self, status: int, body: dict) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    return self._send(200, idp.discovery_document())
                if self.path == "/jwks":
                    return self._send(200, idp.jwks())
                self._send(404, {"error": "not_found"})

            def do_POST(self):
                if self.path != "/token":
                    return self._send(404, {"error": "not_found"})
                length = int(self.headers.get("content-length") or 0)
                form = {k: v[0] for k, v in
                        parse_qs(self.rfile.read(length).decode()).items()}
                form["_authorization"] = self.headers.get("authorization", "")
                idp.issued_forms.append(form)
                if idp.token_status != 200:
                    return self._send(idp.token_status, {"error": "invalid_grant"})
                self._send(200, {"access_token": "at", "token_type": "Bearer",
                                 "id_token": idp.id_token()})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # ---------------------------------------------------------------- content

    def discovery_document(self) -> dict:
        return {
            "issuer": self.base_url,
            "authorization_endpoint": f"{self.base_url}/authorize",
            "token_endpoint": f"{self.base_url}/token",
            "jwks_uri": f"{self.base_url}/jwks",
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    def jwks(self) -> dict:
        numbers = self.key.public_key().public_numbers()

        def b64(value: int) -> str:
            import base64
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
                          "n": b64(numbers.n), "e": b64(numbers.e)}]}

    def id_token(self) -> str:
        now = int(time.time())
        claims = {"iss": self.base_url, "iat": now, "exp": now + 300, **self.claims}
        key = self.key
        if self.sign_with_wrong_key:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": self.kid})
