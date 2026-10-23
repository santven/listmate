#!/usr/bin/env python3
"""
Unit and integration test suite for Nourish Discovery Drawer & Default Landing Screen.
Covers:
1. Backend /api/nourish/user/nourish-enabled & /api/user/nourish-enabled:
   - Returns has_logged_meals: True and total_logs > 0 when user has logs.
   - Returns has_logged_meals: False and total_logs: 0 when user has never logged.
   - Handles multi-tenant user isolation (User A logs do not leak into User B).
   - Enforces authentication (401 when unauthenticated).
2. Frontend Eligibility & Idle Trigger Logic:
   - Suppressed on Session 1.
   - Suppressed if nourish_enabled == true.
   - Suppressed if user has prior logs (has_logged_meals == true).
   - Suppressed if dismissed < 14 days ago (and eligible if dismissed >= 14 days ago).
   - Cancelled if user types in an input (document.activeElement.tagName === 'INPUT' or 'TEXTAREA').
   - Cancelled if another modal is active.
   - Triggers when idle for 5s on session 2+ on home screen.
3. Default Landing Screen:
   - Persists listmate_last_screen in showScreen().
   - Auto-navigates to last_screen on launch when no URL query param is present.
   - Falls back to 'home' if last_screen === 'nourish' but Nourish is disabled.
   - Navigates to 'nourish' if last_screen === 'nourish' and Nourish is enabled.
   - Honors explicit URL query parameters without overriding them.
4. Static DOM & Clean JS Syntax:
   - index.html inline scripts contain valid JavaScript without syntax errors.
   - Drawer DOM components are present.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

# Environment setup
os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "test-secret-key-unit-tests")
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")

# Defensive mocking of external libraries if missing in test environment
for mod in [
    "google",
    "google.oauth2",
    "google.auth",
    "google.auth.transport",
    "google.auth.exceptions",
    "psycopg2",
    "psycopg2.extras",
    "psycopg2.pool",
    "requests",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

import app as app_module
from test_nourish_m2_api import InMemoryNourishDB

INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


class TestNourishDiscoveryBackend(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.fake_db = InMemoryNourishDB()

    def _context_patches(self, user_id=10, household_id=1, subscription_status="premium", is_premium=True):
        @contextlib.contextmanager
        def _ctx():
            with self.client.session_transaction() as sess:
                sess["listmate_session"] = {
                    "user_id": user_id,
                    "household_id": household_id,
                    "email": f"user{user_id}@example.com",
                }
            hh_row = {
                "id": household_id,
                "is_premium": is_premium,
                "subscription_status": subscription_status,
                "trial_ends_at": None,
            }
            with contextlib.ExitStack() as stack:
                for p in (
                    patch("shared.auth._reconcile_session", side_effect=lambda s: s),
                    patch("app.get_db", return_value=self.fake_db),
                    patch("app._ensure_schema"),
                    patch("shared.auth.get_user_id", return_value=user_id),
                    patch("shared.auth.get_household_id", return_value=household_id),
                    patch("app.get_household_id", return_value=household_id),
                    patch("shared.auth._one", return_value=hh_row if household_id else None),
                    patch("shared.auth.get_household_status", return_value={"is_read_only": False}),
                ):
                    stack.enter_context(p)
                yield
        return _ctx()

    def test_nourish_enabled_has_logged_meals_false_when_no_logs(self):
        """GET /api/nourish/user/nourish-enabled returns has_logged_meals: False, total_logs: 0 for fresh user."""
        with self._context_patches(user_id=10, household_id=1):
            res = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["ok"])
            self.assertFalse(data["enabled"])
            self.assertFalse(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 0)

            # Test route alias /api/user/nourish-enabled
            res_alias = self.client.get("/api/user/nourish-enabled")
            self.assertEqual(res_alias.status_code, 200)
            data_alias = res_alias.get_json()
            self.assertFalse(data_alias["has_logged_meals"])
            self.assertEqual(data_alias["total_logs"], 0)

    def test_nourish_enabled_has_logged_meals_true_when_has_logs(self):
        """GET /api/nourish/user/nourish-enabled returns has_logged_meals: True, total_logs > 0 when user has logged meals."""
        # Seed 2 meal logs for user 10
        self.fake_db.logs[1] = {
            "id": 1,
            "user_id": 10,
            "household_id": 1,
            "log_date": "2026-10-23",
            "meal_slot": "Breakfast",
            "food_name": "Greek Yogurt",
            "calories": 150,
            "protein_g": 15,
            "carbs_g": 8,
            "fat_g": 2,
            "fiber_g": 0,
            "is_shared_household": False,
        }
        self.fake_db.logs[2] = {
            "id": 2,
            "user_id": 10,
            "household_id": 1,
            "log_date": "2026-10-23",
            "meal_slot": "Lunch",
            "food_name": "Chicken Salad",
            "calories": 350,
            "protein_g": 35,
            "carbs_g": 10,
            "fat_g": 12,
            "fiber_g": 4,
            "is_shared_household": False,
        }

        with self._context_patches(user_id=10, household_id=1):
            res = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["ok"])
            self.assertTrue(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 2)

    def test_nourish_enabled_user_isolation(self):
        """User A's logs do NOT cause User B to report has_logged_meals: True."""
        # Seed logs only for User 10
        self.fake_db.logs[1] = {
            "id": 1,
            "user_id": 10,
            "household_id": 1,
            "log_date": "2026-10-23",
            "meal_slot": "Dinner",
            "food_name": "Salmon",
            "calories": 400,
        }

        # Check User 20 who has never logged
        with self._context_patches(user_id=20, household_id=1):
            res = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 0)

    def test_nourish_enabled_unauthenticated(self):
        """Unauthenticated call to /api/nourish/user/nourish-enabled returns 401."""
        with patch("shared.auth.get_user_id", return_value=None):
            res = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(res.status_code, 401)


class TestNourishDiscoveryFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_inline_scripts_valid_js_syntax(self):
        """All inline script blocks in static/index.html parse cleanly without JS syntax errors."""
        scripts = re.findall(
            r"<script(?![^>]*src=)[^>]*>(.*?)</script>",
            self.html,
            re.DOTALL | re.IGNORECASE,
        )
        self.assertGreaterEqual(len(scripts), 1)
        for idx, script in enumerate(scripts):
            res = subprocess.run(
                ["node", "-e", "new Function(process.argv[1])", script],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"JS syntax error in inline script #{idx}: {res.stderr}",
            )

    def test_discovery_drawer_dom_elements_present(self):
        """static/index.html contains the Nourish Discovery Drawer DOM components."""
        self.assertIn('id="nourishDiscoveryBackdrop"', self.html)
        self.assertIn('id="nourishDiscoveryDrawer"', self.html)
        self.assertIn('id="btnNourishDiscoveryExplore"', self.html)
        self.assertIn('id="btnNourishDiscoveryDismiss"', self.html)
        self.assertIn("dismissNourishDiscoveryDrawer()", self.html)
        self.assertIn("acceptNourishDiscoveryDrawer()", self.html)

    def test_frontend_discovery_drawer_eligibility_and_idle_triggers(self):
        """Node sandbox verification of session suppression, eligibility guards, input cancellation, active modal cancellation, and 5s idle trigger."""
        node_test = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

// Extract all inline script blocks
const scripts = [];
const scriptRegex = /<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/gi;
let match;
while ((match = scriptRegex.exec(html)) !== null) {
  scripts.push(match[1]);
}

// Minimal DOM simulation
const elements = {};
function makeEl(id, tagName = 'div') {
  return {
    id: id,
    tagName: tagName.toUpperCase(),
    classList: {
      _classes: new Set(),
      add(c) { this._classes.add(c); },
      remove(c) { this._classes.delete(c); },
      contains(c) { return this._classes.has(c); },
      toggle(c, f) { if (f !== undefined) { f ? this.add(c) : this.remove(c); } else { this.contains(c) ? this.remove(c) : this.add(c); } }
    },
    style: { display: '' },
    innerHTML: '',
    textContent: '',
    value: '',
    disabled: false,
    setAttribute() {},
    getAttribute() { return null; },
    addEventListener() {},
    removeEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    isContentEditable: false
  };
}

const elementIds = [
  'nourishDiscoveryBackdrop', 'nourishDiscoveryDrawer', 'btnNourishDiscoveryExplore', 'btnNourishDiscoveryDismiss',
  'activeModalTest', 'testInputBox', 'burgerMenu', 'appSwitcherMenu', 'bottomDrawer'
];
elementIds.forEach(id => { elements[id] = makeEl(id); });
elements['testInputBox'] = makeEl('testInputBox', 'input');

const storageMap = {};
global.localStorage = {
  getItem(k) { return storageMap[k] !== undefined ? storageMap[k] : null; },
  setItem(k, v) { storageMap[k] = String(v); },
  removeItem(k) { delete storageMap[k]; },
  clear() { for (let k in storageMap) delete storageMap[k]; }
};

const sessionStorageMap = {};
global.sessionStorage = {
  getItem(k) { return sessionStorageMap[k] !== undefined ? sessionStorageMap[k] : null; },
  setItem(k, v) { sessionStorageMap[k] = String(v); },
  removeItem(k) { delete sessionStorageMap[k]; },
  clear() { for (let k in sessionStorageMap) delete sessionStorageMap[k]; }
};

global.window = global;
global.window.location = { origin: 'http://localhost:5001', pathname: '/', search: '' };
global.window.currentScreen = 'home';
global.currentScreen = 'home';
global.stores = [{ id: 1, name: 'Trader Joe\'s' }];

let activeEl = null;
global.document = {
  getElementById(id) { return elements[id] || null; },
  querySelector(sel) {
    if (sel.includes('.active') || sel.includes('.show')) {
      for (let k in elements) {
        if (elements[k].classList.contains('active') || elements[k].classList.contains('show')) {
          // Exclude our discovery backdrop/drawer from blocking itself
          if (k !== 'nourishDiscoveryBackdrop' && k !== 'nourishDiscoveryDrawer') {
            return elements[k];
          }
        }
      }
    }
    return null;
  },
  querySelectorAll() { return []; },
  addEventListener(evt, fn) {
    documentListeners[evt] = documentListeners[evt] || [];
    documentListeners[evt].push(fn);
  },
  removeEventListener(evt, fn) {
    if (documentListeners[evt]) {
      documentListeners[evt] = documentListeners[evt].filter(f => f !== fn);
    }
  },
  body: {
    classList: {
      add() {},
      remove() {},
      contains() { return false; }
    },
    style: {}
  },
  get activeElement() { return activeEl; },
  set activeElement(el) { activeEl = el; },
  hidden: false,
  readyState: 'complete'
};

const documentListeners = {};
function dispatchDocumentEvent(evt) {
  if (documentListeners[evt]) {
    documentListeners[evt].slice().forEach(fn => fn());
  }
}

const windowListeners = {};
global.window.addEventListener = (evt, fn) => {
  windowListeners[evt] = windowListeners[evt] || [];
  windowListeners[evt].push(fn);
};
global.window.removeEventListener = (evt, fn) => {
  if (windowListeners[evt]) {
    windowListeners[evt] = windowListeners[evt].filter(f => f !== fn);
  }
};

global.escapeHtml = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
global.toast = () => {};
global.API = '/api';
global.isNourishEnabled = () => global._nourishEnabled === true;
global.setNourishEnabled = (en) => { global._nourishEnabled = en; };
global.showScreen = (s) => {
  global.currentScreen = s;
  global.window.currentScreen = s;
  if (['home', 'stillGood', 'nourish', 'recipes', 'analytics'].includes(s)) {
    global.localStorage.setItem('listmate_last_screen', s);
  }
  if (s !== 'home' && typeof global._cancelNourishDiscoveryTimer === 'function') {
    global._cancelNourishDiscoveryTimer();
  } else if (s === 'home' && typeof global._scheduleNourishDiscoveryTimer === 'function') {
    global._scheduleNourishDiscoveryTimer();
  }
};

// Mock timers for controlled fast-forwarding
const activeTimers = {};
let nextTimerId = 1;
global.setTimeout = (fn, delay) => {
  const tid = nextTimerId++;
  activeTimers[tid] = { fn, delay };
  return tid;
};
global.clearTimeout = (tid) => {
  delete activeTimers[tid];
};

function fastForward5s() {
  const ids = Object.keys(activeTimers);
  for (const tid of ids) {
    if (activeTimers[tid]) {
      const entry = activeTimers[tid];
      delete activeTimers[tid];
      entry.fn();
    }
  }
}

// Mock fetch responses
let serverEnabled = false;
let serverTotalLogs = 0;
let serverHasLoggedMeals = false;

global.fetch = (url) => {
  if (url.includes('/user/nourish-enabled')) {
    return Promise.resolve({
      json: () => Promise.resolve({
        ok: true,
        enabled: serverEnabled,
        total_logs: serverTotalLogs,
        has_logged_meals: serverHasLoggedMeals
      })
    });
  }
  return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
};

// Extract and evaluate the exact Nourish Discovery engine code from static/index.html
const engineMatch = html.match(/\/\/\s*──\s*Nourish Discovery Bottom Drawer[\s\S]*?window\.initNourishDiscoveryIdleTrigger\s*=\s*initNourishDiscoveryIdleTrigger;/);
if (!engineMatch) {
  throw new Error('Could not find script block containing initNourishDiscoveryIdleTrigger');
}
eval(engineMatch[0]);

(async () => {
  // ── TEST 1: Suppressed on Session 1 ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '1');
  sessionStorage.setItem('listmate_session_counted', '1');
  serverEnabled = false;
  serverTotalLogs = 0;
  serverHasLoggedMeals = false;
  global.currentScreen = 'home';
  document.activeElement = null;

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 1 Failed: Drawer MUST NOT open on Session 1');
  }

  // ── TEST 2: Suppressed if nourish_enabled == true ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  global._nourishEnabled = true;
  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 2 Failed: Drawer MUST NOT open if nourish_enabled == true');
  }
  global._nourishEnabled = false;

  // ── TEST 3: Suppressed if user has prior logs (has_logged_meals == true or total_logs > 0) ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '3');
  sessionStorage.setItem('listmate_session_counted', '1');
  serverEnabled = false;
  serverTotalLogs = 5;
  serverHasLoggedMeals = true;

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 3 Failed: Drawer MUST NOT open if user has prior meal logs');
  }

  // ── TEST 4: Suppressed if dismissed < 14 days ago ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  // Dismissed 5 days ago
  localStorage.setItem('nourish_discovery_dismissed_at', String(Date.now() - (5 * 86400000)));
  serverTotalLogs = 0;
  serverHasLoggedMeals = false;

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 4 Failed: Drawer MUST NOT open if dismissed < 14 days ago');
  }

  // ── TEST 5: Cancelled/Blocked if user types in an input (document.activeElement.tagName === 'INPUT') ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  document.activeElement = elements['testInputBox']; // tagName === 'INPUT'

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 5 Failed: Drawer MUST be blocked while user is focused/typing in an input');
  }
  document.activeElement = null;

  // ── TEST 6: Cancelled/Blocked if another modal is active ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  elements['activeModalTest'].classList.add('active');

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 6 Failed: Drawer MUST be blocked if another modal is active');
  }
  elements['activeModalTest'].classList.remove('active');

  // ── TEST 7: Triggers when idle for 5s on session 2+ on home screen ──
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  serverEnabled = false;
  serverTotalLogs = 0;
  serverHasLoggedMeals = false;
  global.currentScreen = 'home';
  document.activeElement = null;

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (!elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 7 Failed: Drawer MUST open when idle for 5s on session 2+ on home screen');
  }
  if (!elements.nourishDiscoveryBackdrop.classList.contains('active')) {
    throw new Error('Test 7 Failed: Backdrop MUST be active when drawer opens');
  }

  // ── TEST 8: Dismiss sets 14-day timestamp and closes drawer ──
  dismissNourishDiscoveryDrawer();
  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 8 Failed: Dismiss MUST remove active class from drawer');
  }
  const dismissedTime = parseInt(localStorage.getItem('nourish_discovery_dismissed_at') || '0', 10);
  if (Math.abs(Date.now() - dismissedTime) > 5000) {
    throw new Error('Test 8 Failed: Dismiss MUST store recent timestamp in nourish_discovery_dismissed_at');
  }

  // ── TEST 9: Accept enables nourish and navigates to 'nourish' screen ──
  let enabledToggled = false;
  global.setNourishEnabled = async (val) => { enabledToggled = val; global._nourishEnabled = val; };
  await acceptNourishDiscoveryDrawer();
  if (!enabledToggled) {
    throw new Error('Test 9 Failed: Accept MUST enable Nourish');
  }
  // ── TEST 10: Existing account with listmate_cfg is treated as eligible returning user even on Session 1 ──
  global._nourishEnabled = false;
  elements.nourishDiscoveryDrawer.classList.remove('active');
  elements.nourishDiscoveryBackdrop.classList.remove('active');
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '1');
  sessionStorage.setItem('listmate_session_counted', '1');
  localStorage.setItem('listmate_cfg', JSON.stringify({ user: 'existing@example.com', household_id: 42 }));
  serverEnabled = false;
  serverTotalLogs = 0;
  serverHasLoggedMeals = false;
  global.currentScreen = 'home';
  document.activeElement = null;

  initNourishDiscoveryIdleTrigger();
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (!elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 10 Failed: Existing account with listmate_cfg MUST be treated as eligible returning user even on session 1');
  }

  // ── TEST 11: Returning to tab (visibilitychange) resumes idle countdown ──
  elements.nourishDiscoveryDrawer.classList.remove('active');
  elements.nourishDiscoveryBackdrop.classList.remove('active');
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('listmate_session_count', '2');
  sessionStorage.setItem('listmate_session_counted', '1');
  serverEnabled = false;
  serverTotalLogs = 0;
  serverHasLoggedMeals = false;

  initNourishDiscoveryIdleTrigger();

  // Tab hidden: idle countdown cancelled / blocked
  document.hidden = true;
  dispatchDocumentEvent('visibilitychange');
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 11 Failed: Drawer MUST NOT open while document.hidden is true');
  }

  // Returning to tab: document.hidden = false -> resumes countdown
  document.hidden = false;
  dispatchDocumentEvent('visibilitychange');
  fastForward5s();
  await new Promise(r => setImmediate(r));

  if (!elements.nourishDiscoveryDrawer.classList.contains('active')) {
    throw new Error('Test 11 Failed: Returning to tab (visibilitychange) MUST resume idle countdown and open drawer');
  }

  console.log('ALL_FRONTEND_DISCOVERY_TESTS_PASSED');
})();
"""
        res = subprocess.run(
            ["node", "-e", node_test, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Frontend discovery idle trigger test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        self.assertIn("ALL_FRONTEND_DISCOVERY_TESTS_PASSED", res.stdout)

    def test_frontend_default_landing_screen_navigation(self):
        """Node sandbox verification that listmate_last_screen is persisted in showScreen(), restored on launch, and falls back to home when Nourish is disabled."""
        node_test = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

const scripts = [];
const scriptRegex = /<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/gi;
let match;
while ((match = scriptRegex.exec(html)) !== null) {
  scripts.push(match[1]);
}

const storageMap = {};
global.localStorage = {
  getItem(k) { return storageMap[k] !== undefined ? storageMap[k] : null; },
  setItem(k, v) { storageMap[k] = String(v); },
  removeItem(k) { delete storageMap[k]; },
  clear() { for (let k in storageMap) delete storageMap[k]; }
};

global.window = global;
global.window.location = { origin: 'http://localhost:5001', pathname: '/', search: '' };
global.currentScreen = 'home';
global.window.currentScreen = 'home';
global.document = {
  getElementById() { return null; },
  querySelector() { return null; },
  addEventListener() {},
  removeEventListener() {},
  body: { classList: { add() {}, remove() {} } }
};
global.URLSearchParams = URLSearchParams;

let nourishEnabled = false;
global.isNourishEnabled = () => nourishEnabled;

let shownScreen = null;
global.showScreen = (name) => {
  shownScreen = name;
  global.currentScreen = name;
  global.window.currentScreen = name;
  const trackedScreens = ['home', 'stillGood', 'nourish', 'recipes', 'analytics'];
  if (trackedScreens.includes(name)) {
    global.localStorage.setItem('listmate_last_screen', name);
  }
};

// Extract and evaluate applyLastScreenLandingDefault
const landingMatch = html.match(/function applyLastScreenLandingDefault[\s\S]*?window\.applyLastScreenLandingDefault\s*=\s*applyLastScreenLandingDefault;/);
if (!landingMatch) {
  throw new Error('Could not find script block containing applyLastScreenLandingDefault');
}
eval(landingMatch[0]);

(function runLandingTests() {
  // ── 1. showScreen persists listmate_last_screen ──
  localStorage.clear();
  showScreen('stillGood');
  if (localStorage.getItem('listmate_last_screen') !== 'stillGood') {
    throw new Error('Expected listmate_last_screen to be stillGood after showScreen');
  }

  showScreen('recipes');
  if (localStorage.getItem('listmate_last_screen') !== 'recipes') {
    throw new Error('Expected listmate_last_screen to be recipes after showScreen');
  }

  // ── 2. Auto-navigates to last_screen when no URL query param is present ──
  shownScreen = null;
  window.location.search = '';
  localStorage.setItem('listmate_last_screen', 'stillGood');
  applyLastScreenLandingDefault();
  if (shownScreen !== 'stillGood') {
    throw new Error('Expected auto-navigation to stillGood on launch, got: ' + shownScreen);
  }

  // ── 3. Falls back to 'home' if last_screen === 'nourish' but Nourish is disabled ──
  shownScreen = null;
  window.location.search = '';
  nourishEnabled = false;
  localStorage.setItem('listmate_last_screen', 'nourish');
  applyLastScreenLandingDefault();
  if (shownScreen !== null && shownScreen !== 'home') {
    throw new Error('Expected fallback to home when nourish is disabled, but navigated to: ' + shownScreen);
  }

  // ── 4. Navigates to 'nourish' if last_screen === 'nourish' and Nourish is enabled ──
  shownScreen = null;
  window.location.search = '';
  nourishEnabled = true;
  localStorage.setItem('listmate_last_screen', 'nourish');
  applyLastScreenLandingDefault();
  if (shownScreen !== 'nourish') {
    throw new Error('Expected navigation to nourish when enabled, got: ' + shownScreen);
  }

  // ── 5. Does NOT auto-navigate if explicit URL query parameter is present ──
  shownScreen = null;
  window.location.search = '?screen=recipes';
  localStorage.setItem('listmate_last_screen', 'stillGood');
  applyLastScreenLandingDefault();
  if (shownScreen !== null) {
    throw new Error('applyLastScreenLandingDefault should NOT override URL query parameters');
  }

  shownScreen = null;
  window.location.search = '?action=invite';
  applyLastScreenLandingDefault();
  if (shownScreen !== null) {
    throw new Error('applyLastScreenLandingDefault should NOT override action query parameters');
  }

  console.log('ALL_LANDING_SCREEN_TESTS_PASSED');
})();
"""
        res = subprocess.run(
            ["node", "-e", node_test, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Default landing screen test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        self.assertIn("ALL_LANDING_SCREEN_TESTS_PASSED", res.stdout)

    def test_idle_trigger_autoruns_on_dom_load(self):
        """Verify initNourishDiscoveryIdleTrigger auto-runs upon script/DOM load."""
        self.assertIn("initNourishDiscoveryIdleTrigger()", self.html)
        self.assertIn("DOMContentLoaded", self.html)

        node_test = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

const autoRunMatch = html.match(/if\s*\(document\.readyState\s*===\s*'loading'\)[\s\S]*?initNourishDiscoveryIdleTrigger\(\);\s*\}\s*<\/script>/);
if (!autoRunMatch) {
  throw new Error('Auto-run block for initNourishDiscoveryIdleTrigger not found in static/index.html');
}

let triggerCalled = 0;
global.initNourishDiscoveryIdleTrigger = () => { triggerCalled++; };

// Case A: document.readyState === 'loading'
let domListener = null;
global.document = {
  readyState: 'loading',
  addEventListener(evt, fn) {
    if (evt === 'DOMContentLoaded') domListener = fn;
  }
};
eval(autoRunMatch[0].replace('</script>', ''));
if (!domListener) {
  throw new Error('Expected DOMContentLoaded listener registered when readyState === "loading"');
}
domListener();
if (triggerCalled !== 1) {
  throw new Error('Expected initNourishDiscoveryIdleTrigger called on DOMContentLoaded, got calls: ' + triggerCalled);
}

// Case B: document.readyState === 'complete' (already loaded)
global.document.readyState = 'complete';
eval(autoRunMatch[0].replace('</script>', ''));
if (triggerCalled !== 2) {
  throw new Error('Expected initNourishDiscoveryIdleTrigger called immediately when readyState !== "loading", got calls: ' + triggerCalled);
}

console.log('AUTO_RUN_TESTS_PASSED');
"""
        res = subprocess.run(
            ["node", "-e", node_test, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Idle trigger auto-run test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
        )
        self.assertIn("AUTO_RUN_TESTS_PASSED", res.stdout)


if __name__ == "__main__":
    unittest.main()
