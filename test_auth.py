import os
import sys
import re
import subprocess
import unittest
from unittest.mock import patch, MagicMock

# Environment setup
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")
os.environ["SECRET_KEY"] = "test-secret-key-unit-tests"

# Defensive mocking of external libraries if missing in test environment
for mod in [
    "google", "google.oauth2", "google.auth", "google.auth.transport",
    "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

from app import app


class TestAuthConfigAndGTM(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_ctx = app.app_context()
        self.app_ctx.push()

    def tearDown(self):
        self.app_ctx.pop()

    def test_auth_config_gtm_container_id_unset(self):
        """Verify GET /api/auth/config returns empty string when GTM_CONTAINER_ID is unset."""
        with patch.dict(os.environ, {}, clear=False):
            if "GTM_CONTAINER_ID" in os.environ:
                del os.environ["GTM_CONTAINER_ID"]
            resp = self.client.get("/api/auth/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn("gtm_container_id", data)
            self.assertEqual(data["gtm_container_id"], "")

    def test_auth_config_gtm_container_id_set(self):
        """Verify GET /api/auth/config returns container ID when GTM_CONTAINER_ID is set."""
        with patch.dict(os.environ, {"GTM_CONTAINER_ID": "GTM-TEST1234"}):
            resp = self.client.get("/api/auth/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("gtm_container_id"), "GTM-TEST1234")

    def test_auth_config_gtm_container_id_whitespace_trimmed(self):
        """Verify whitespace around GTM_CONTAINER_ID is properly trimmed."""
        with patch.dict(os.environ, {"GTM_CONTAINER_ID": "  GTM-TRIMMED  "}):
            resp = self.client.get("/api/auth/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("gtm_container_id"), "GTM-TRIMMED")

    def test_login_page_gtm_placeholder_replacement(self):
        """Verify login_page properly replaces GTM_CONTAINER_ID_PLACEHOLDER."""
        # Case A: Unset
        with patch.dict(os.environ, {}, clear=False):
            if "GTM_CONTAINER_ID" in os.environ:
                del os.environ["GTM_CONTAINER_ID"]
            resp = self.client.get("/login")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertNotIn("GTM_CONTAINER_ID_PLACEHOLDER", html)
            self.assertIn("var gtmId = '';", html)

        # Case B: Set
        with patch.dict(os.environ, {"GTM_CONTAINER_ID": "GTM-CONTAINER99"}):
            resp = self.client.get("/login")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertNotIn("GTM_CONTAINER_ID_PLACEHOLDER", html)
            self.assertIn("var gtmId = 'GTM-CONTAINER99';", html)

    def test_html_scripts_clean_js_syntax(self):
        """Verify all inline script tags in index.html and login.html execute cleanly without syntax errors."""
        base_dir = os.path.dirname(__file__)
        for fname in ["index.html", "login.html"]:
            fpath = os.path.join(base_dir, "static", fname)
            with open(fpath, "r", encoding="utf-8") as f:
                html = f.read()

            scripts = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
            self.assertGreater(len(scripts), 0, f"No scripts found in {fname}")
            for idx, script in enumerate(scripts):
                is_module = "import " in script or "export " in script
                if is_module:
                    code = f"""
                    const vm = require("vm");
                    try {{
                        new vm.SourceTextModule({repr(script)});
                    }} catch(e) {{
                        console.error(e);
                        process.exit(1);
                    }}
                    """
                    cmd = ["node", "--experimental-vm-modules", "-e", code]
                else:
                    cmd = ["node", "-e", "new Function(process.argv[1])", script]
                res = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(
                    res.returncode,
                    0,
                    f"Syntax error in {fname} script block #{idx}: {res.stderr}"
                )


if __name__ == "__main__":
    unittest.main()
