import unittest
import os
import sys
import time
import json
from unittest.mock import patch, MagicMock

# Ensure database mock during import
os.environ["DATABASE_URL"] = "postgresql://dummy:5432/test"
os.environ["SSO_APPLE_CLIENT_ID"] = "com.pvkslabs.listmate.web"
os.environ["APPLE_CLIENT_ID"] = "com.pvkslabs.listmate.web"

# Defensive mocking of external DB / google libs if needed
for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

import shared.auth as authmod
import app as flask_app


class TestAppleAuthRealCrypto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generate real RSA private/public keypair
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()
        
        # Generate a separate wrong private key to test signature mismatch
        cls.wrong_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        cls.key_id = "apple-test-key-2026"
        cls.client = flask_app.app.test_client()

    def _create_token(self, claims, kid=None, key=None):
        if kid is None:
            kid = self.key_id
        if key is None:
            key = self.private_key
        headers = {"kid": kid, "alg": "RS256"}
        return jwt.encode(claims, key, algorithm="RS256", headers=headers)

    def _mock_jwk_client(self, signing_key=None):
        if signing_key is None:
            signing_key = self.public_key
        mock_client = MagicMock()
        mock_key_obj = MagicMock()
        mock_key_obj.key = signing_key
        mock_client.get_signing_key_from_jwt.return_value = mock_key_obj
        return mock_client

    def test_valid_ios_token_real_verification(self):
        """Valid iOS token with valid RSA signature succeeds."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "iat": now,
            "sub": "apple.user.ios.123",
            "email": "iosuser@example.com",
            "email_verified": True
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            verified = authmod.verify_apple_id_token(token)
            self.assertEqual(verified["sub"], "apple.user.ios.123")
            self.assertEqual(verified["email"], "iosuser@example.com")
            self.assertTrue(verified["email_verified"])

    def test_valid_web_token_real_verification(self):
        """Valid web token with Services ID audience succeeds."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate.web",
            "exp": now + 3600,
            "iat": now,
            "sub": "apple.user.web.456",
            "email": "webuser@example.com",
            "email_verified": "true"
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            verified = authmod.verify_apple_id_token(token)
            self.assertEqual(verified["sub"], "apple.user.web.456")
            self.assertEqual(verified["email"], "webuser@example.com")

    def test_signature_mismatch_rejected(self):
        """Token signed by wrong RSA key is rejected by real RS256 verification."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "iat": now,
            "sub": "apple.user.forged",
            "email": "forged@example.com"
        }
        token = self._create_token(claims, key=self.wrong_private_key)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client(self.public_key)):
            with self.assertRaises(jwt.InvalidSignatureError):
                authmod.verify_apple_id_token(token)

    def test_expired_token_rejected(self):
        """Expired token is rejected."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now - 3600,  # Expired 1 hour ago
            "iat": now - 7200,
            "sub": "apple.user.expired",
            "email": "expired@example.com"
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            with self.assertRaises(jwt.ExpiredSignatureError):
                authmod.verify_apple_id_token(token)

    def test_wrong_issuer_rejected(self):
        """Token from fraudulent issuer is rejected."""
        now = int(time.time())
        claims = {
            "iss": "https://evil-issuer.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "iat": now,
            "sub": "apple.user.fakeiss"
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            with self.assertRaises(jwt.InvalidIssuerError):
                authmod.verify_apple_id_token(token)

    def test_wrong_audience_rejected(self):
        """Token intended for another app is rejected."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.otherapp.bundle",
            "exp": now + 3600,
            "iat": now,
            "sub": "apple.user.wrongaud"
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            with self.assertRaises(jwt.InvalidAudienceError):
                authmod.verify_apple_id_token(token)

    def test_missing_required_claim_rejected(self):
        """Token missing required 'exp' or 'sub' claim is rejected."""
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "sub": "apple.user.noexp"
            # exp missing
        }
        token = self._create_token(claims)
        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            with self.assertRaises(jwt.MissingRequiredClaimError):
                authmod.verify_apple_id_token(token)

    # ── SECURITY REGRESSION TESTS: B1 & B2 ───────────────────────────────────

    @patch("shared.auth._one")
    @patch("shared.auth._run")
    @patch("shared.auth._resolve_user_household")
    def test_b1_account_takeover_via_client_email_prevented(self, mock_hh, mock_run, mock_one):
        """
        B1 / S1 Defense: An attacker with their own valid Apple ID attempts to take over
        a victim account by injecting client_user = {"email": "victim@example.com"}.
        The endpoint MUST ignore client_email and bind strictly to the token email.
        """
        now = int(time.time())
        attacker_claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "iat": now,
            "sub": "attacker.apple.sub.999",
            "email": "attacker@example.com",
            "email_verified": True
        }
        token = self._create_token(attacker_claims)

        # Mock DB returns None for apple_id, None for gid
        mock_one.side_effect = [
            None,  # apple_sub
            None,  # gid_alias
            {"id": 88, "google_id": "apple_attacker.apple.sub.999", "apple_id": "attacker.apple.sub.999", "email": "attacker@example.com", "name": "Attacker", "household_id": 12}
        ]
        mock_hh.return_value = (12, "Attacker Household")

        with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client()):
            resp = self.client.post("/api/auth/apple", json={
                "id_token": token,
                "user": {"email": "victim@example.com", "name": {"firstName": "Victim", "lastName": "Spoofed"}}
            })

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("email"), "attacker@example.com")
            
            # Verify no query ever looked up victim@example.com
            for call_args in [call[0] for call in mock_one.call_args_list]:
                if len(call_args) > 1 and call_args[1]:
                    params = call_args[1]
                    if isinstance(params, (list, tuple)) and "victim@example.com" in params:
                        self.fail("SECURITY VIOLATION: Database was queried with attacker-supplied client email!")

    def test_b2_reflected_xss_prevention_in_login_page(self):
        """
        B2 / S2 Defense: Attacker posts a malicious token with script injection in kid or claims.
        The 401 response MUST NOT reflect raw exception strings or script tags into HTML.
        """
        malicious_kid = 'test-key"><script>alert("xss")</script>'
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "sub": "test.sub"
        }
        token = self._create_token(claims, kid=malicious_kid)

        resp = self.client.post("/login", data={"id_token": token})
        self.assertEqual(resp.status_code, 401)
        html = resp.data.decode("utf-8")
        
        # Verify script tag is NOT reflected
        self.assertNotIn("<script>alert", html)
        self.assertNotIn(malicious_kid, html)
        self.assertIn("Invalid or unverified Apple identity token.", html)

    # ── ENFORCEMENT MODES: APPLE_JWT_ENFORCE ─────────────────────────────────

    def test_apple_jwt_enforce_off_mode(self):
        """When APPLE_JWT_ENFORCE='off', signature check is bypassed."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "sub": "unverified.user"
        }
        # Token signed by wrong key
        token = self._create_token(claims, key=self.wrong_private_key)

        with patch.dict(os.environ, {"APPLE_JWT_ENFORCE": "off"}):
            verified = authmod.verify_apple_id_token(token)
            self.assertEqual(verified["sub"], "unverified.user")

    def test_apple_jwt_enforce_report_mode(self):
        """When APPLE_JWT_ENFORCE='report', verification failure logs and falls back without raising."""
        now = int(time.time())
        claims = {
            "iss": "https://appleid.apple.com",
            "aud": "com.pvkslabs.listmate",
            "exp": now + 3600,
            "sub": "shadow.user"
        }
        token = self._create_token(claims, key=self.wrong_private_key)

        with patch.dict(os.environ, {"APPLE_JWT_ENFORCE": "report"}):
            with patch("shared.auth.get_apple_jwk_client", return_value=self._mock_jwk_client(self.public_key)):
                verified = authmod.verify_apple_id_token(token)
                self.assertEqual(verified["sub"], "shadow.user")


if __name__ == "__main__":
    unittest.main()
