import unittest
from unittest.mock import patch, MagicMock
import os
import json
import sys

# Ensure local postgres socket hang is avoided during import
os.environ["DATABASE_URL"] = "postgresql://dummy:5432/test"
os.environ["SSO_APPLE_CLIENT_ID"] = "com.pvkslabs.listmate.web"
os.environ["APPLE_CLIENT_ID"] = "com.pvkslabs.listmate.web"

# Defensive mocking of external C-extensions if missing locally
for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

if "jwt" not in sys.modules:
    mock_jwt = MagicMock()
    sys.modules["jwt"] = mock_jwt
    sys.modules["jwt.PyJWKClient"] = mock_jwt.PyJWKClient

import shared.auth as authmod


class TestAppleAuthVerification(unittest.TestCase):

    def test_missing_or_invalid_token_raises_error(self):
        with self.assertRaises(ValueError):
            authmod.verify_apple_id_token(None)

        with self.assertRaises(ValueError):
            authmod.verify_apple_id_token("")

        with self.assertRaises(ValueError):
            authmod.verify_apple_id_token(12345)

    def test_allowed_audiences_includes_ios_and_web(self):
        audiences = authmod.get_allowed_apple_audiences()
        self.assertIn("com.pvkslabs.listmate", audiences)
        self.assertIn("com.pvkslabs.listmate.web", audiences)

    @patch("jwt.PyJWKClient")
    @patch("jwt.decode")
    def test_verify_apple_id_token_valid_ios(self, mock_jwt_decode, mock_jwk_client_cls):
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_key.key = "fake_rsa_public_key"
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        expected_claims = {
            "sub": "001234.abcdef.5678",
            "email": "user@example.com",
            "email_verified": True,
            "aud": "com.pvkslabs.listmate",
            "iss": "https://appleid.apple.com"
        }
        mock_jwt_decode.return_value = expected_claims

        with patch("shared.auth.get_apple_jwk_client", return_value=mock_client):
            claims = authmod.verify_apple_id_token("valid_token_ios")
            self.assertEqual(claims["sub"], "001234.abcdef.5678")
            self.assertEqual(claims["email"], "user@example.com")
            self.assertTrue(claims["email_verified"])

            mock_jwt_decode.assert_called_once()
            args, kwargs = mock_jwt_decode.call_args
            self.assertEqual(args[0], "valid_token_ios")
            self.assertEqual(args[1], "fake_rsa_public_key")
            self.assertEqual(kwargs["algorithms"], ["RS256"])
            self.assertEqual(kwargs["issuer"], "https://appleid.apple.com")
            self.assertTrue(kwargs["options"]["verify_signature"])
            self.assertTrue(kwargs["options"]["verify_exp"])

    @patch("jwt.PyJWKClient")
    @patch("jwt.decode")
    def test_verify_apple_id_token_invalid_signature_raises(self, mock_jwt_decode, mock_jwk_client_cls):
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_key.key = "fake_rsa_public_key"
        mock_client.get_signing_key_from_jwt.return_value = mock_key

        import jwt
        # Simulate PyJWT signature verification failure
        mock_jwt_decode.side_effect = Exception("Signature verification failed")

        with patch("shared.auth.get_apple_jwk_client", return_value=mock_client):
            with self.assertRaises(Exception) as ctx:
                authmod.verify_apple_id_token("forged_token")
            self.assertIn("Signature verification failed", str(ctx.exception))

    @patch("shared.auth.verify_apple_id_token")
    @patch("shared.auth._one")
    @patch("shared.auth._run")
    @patch("shared.auth._resolve_user_household")
    def test_auth_apple_rejects_unverified_email_for_account_takeover(
        self, mock_resolve_hh, mock_run, mock_one, mock_verify
    ):
        """If email_verified is FALSE, an existing account with that email MUST NOT be linked."""
        import app as flask_app
        client = flask_app.app.test_client()

        # Attacker tries to impersonate admin@example.com, but email_verified is False
        mock_verify.return_value = {
            "sub": "attacker_sub_999",
            "email": "admin@example.com",
            "email_verified": False,
            "aud": "com.pvkslabs.listmate"
        }

        # _one responses:
        # 1. lookup by apple_id: None
        # 2. lookup by gid: None
        # 3. lookup after insert: newly created user
        mock_one.side_effect = [
            None,  # apple_sub not found
            None,  # gid_alias not found
            {"id": 42, "email": "admin@example.com", "name": "Admin", "google_id": "apple_attacker_sub_999", "apple_id": "attacker_sub_999"},  # user inserted
        ]
        mock_resolve_hh.return_value = (10, "Admin Household")

        resp = client.post("/api/auth/apple", json={"id_token": "token_with_unverified_email"})
        self.assertEqual(resp.status_code, 200)

        # Assert that _one was NOT queried for SELECT ... WHERE LOWER(email) = LOWER('admin@example.com')
        # Because email_verified was False!
        queries = [call[0][0] for call in mock_one.call_args_list]
        self.assertFalse(
            any("LOWER(email) = LOWER(?)" in q for q in queries),
            "VULNERABILITY: Account was matched by email even though email_verified is False!"
        )

    @patch("shared.auth.verify_apple_id_token")
    def test_auth_apple_returns_401_on_failed_verification(self, mock_verify):
        import app as flask_app
        client = flask_app.app.test_client()

        mock_verify.side_effect = Exception("Invalid Apple token signature")

        resp = client.post("/api/auth/apple", json={"id_token": "bad_token"})
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get("ok", True))
        self.assertIn("Invalid or unverified Apple id_token", data.get("error", ""))


if __name__ == "__main__":
    unittest.main()
