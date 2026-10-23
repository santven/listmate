import os
import re
import subprocess
import unittest


INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


class TestNourishM3AppSwitcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_inline_scripts_valid_js_syntax(self):
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
                f"JS syntax error in inline script block #{idx}: {res.stderr}",
            )

    def test_app_switcher_dom_elements_present(self):
        self.assertIn('id="appSwitcherBtn"', self.html)
        self.assertIn('onclick="toggleAppSwitcherMenu(event)"', self.html)
        self.assertIn('id="cartIcon"', self.html)
        self.assertIn('id="appSwitcherSgIcon"', self.html)
        self.assertIn('id="appSwitcherNourishIcon"', self.html)
        self.assertIn('id="headerTitle"', self.html)
        self.assertIn('id="appSwitcherChevron"', self.html)
        self.assertIn('id="appSwitcherUrgentDot"', self.html)
        self.assertIn('id="appSwitcherMenu"', self.html)
        self.assertIn('id="appSwitchItemHome"', self.html)
        self.assertIn("selectSuiteApp('home')", self.html)
        self.assertIn("Smart Store Grocery Lists", self.html)
        self.assertIn('id="appSwitchItemStillGood"', self.html)
        self.assertIn("selectSuiteApp('stillGood')", self.html)
        self.assertIn('id="appSwitcherSgBadge"', self.html)
        self.assertIn('id="sgHomeBadge"', self.html)
        self.assertIn("Fridge, Freezer &amp; Leftover Freshness", self.html)
        self.assertIn('id="appSwitchItemNourish"', self.html)
        self.assertIn("selectSuiteApp('nourish')", self.html)
        self.assertIn("Private Daily Food &amp; Macro Log", self.html)
        self.assertIn('id="appSwitcherSpotlight"', self.html)
        self.assertIn("lm_app_switcher_seen_v1", self.html)
        self.assertIn("dismissAppSwitcherSpotlight", self.html)
        self.assertIn("fireStillGoodConfetti", self.html)

    def test_screen_nourish_and_burger_menu_present(self):
        self.assertIn('<div id="screenNourish" class="screen"', self.html)
        self.assertIn(
            '<button onclick="showNourishScreen()">🍎 Nourish (Food Log)</button>',
            self.html,
        )

    def test_js_functions_and_paywall_modal_contracts(self):
        self.assertIn("async function showNourishScreen()", self.html)
        self.assertIn("showPremiumModal('Nourish')", self.html)
        self.assertIn("Nourish is a Premium Feature", self.html)
        self.assertIn(
            "Track daily calories, protein, and macros effortlessly for your whole household with AI meal parsing, 4-unit scaling, and 100% private personal logs.",
            self.html,
        )
        self.assertIn("else if(name==='nourish')", self.html)
        self.assertIn("$('#headerTitle').textContent='Nourish';", self.html)
        self.assertIn("if (typeof loadNourishDay === 'function')", self.html)

    def test_runtime_behavior_in_node_sandbox(self):
        node_test = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

function extractFunction(src, name) {
  const idx = src.indexOf('function ' + name);
  const asyncIdx = src.indexOf('async function ' + name);
  const start = (asyncIdx !== -1 && (idx === -1 || asyncIdx < idx)) ? asyncIdx : idx;
  if (start === -1) throw new Error('Function not found: ' + name);
  let braceDepth = 0;
  let started = false;
  for (let i = start; i < src.length; i++) {
    if (src[i] === '{') { braceDepth++; started = true; }
    else if (src[i] === '}') {
      braceDepth--;
      if (started && braceDepth === 0) {
        return src.slice(start, i + 1);
      }
    }
  }
  throw new Error('Unbalanced braces for ' + name);
}

const fns = [
  'toggleBurger',
  'closeBurger',
  'closeAppSwitcherMenu',
  'dismissAppSwitcherSpotlight',
  'initAppSwitcherSpotlight',
  'toggleAppSwitcherMenu',
  'updateAppSwitcherActiveState',
  'syncStillGoodSwitcherBadges',
  'selectSuiteApp',
  'canAccessStillGood',
  'showStillGoodScreen',
  'showNourishScreen',
  'showPremiumModal',
  'showScreen',
  'updateFabVisibility',
  'fireStillGoodConfetti'
].map(n => extractFunction(html, n)).join('\n\n');

const elements = {};
function makeEl(id) {
  const classes = new Set();
  return {
    id,
    textContent: '',
    innerHTML: '',
    value: '',
    style: { display: '' },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    classList: {
      add(c) { classes.add(c); },
      remove(c) { classes.delete(c); },
      contains(c) { return classes.has(c); },
      toggle(c, force) {
        const next = typeof force === 'boolean' ? force : !classes.has(c);
        if (next) classes.add(c); else classes.delete(c);
        return next;
      }
    },
    getBoundingClientRect() { return { top: 500, left: 100, width: 60, height: 30 }; }
  };
}

[
  'burgerMenu', 'burgerOverlay', 'appSwitcherMenu', 'appSwitcherOverlay',
  'appSwitcherBtn', 'appSwitcherChevron', 'appSwitcherSpotlight',
  'appSwitchItemHome', 'appSwitchItemStillGood', 'appSwitchItemNourish',
  'sgHomeBadge', 'appSwitcherSgBadge', 'appSwitcherUrgentDot',
  'headerTitle', 'screenHome', 'screenCatalog', 'screenRecipes',
  'screenStillGood', 'screenNourish', 'screenGlobalVisits',
  'screenVisitDetail', 'screenAnalytics', 'catalogSearch', 'catalogQty',
  'premiumModal', 'premiumModalTitle', 'premiumModalDesc', 'fabStores', 'storeGrid',
  'cartIcon', 'appSwitcherSgIcon', 'appSwitcherNourishIcon'
].forEach(id => { elements[id] = makeEl(id); });
const headerEl = makeEl('header');

const storage = {};
global.localStorage = {
  getItem(k) { return Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null; },
  setItem(k, v) { storage[k] = String(v); }
};
global.window = global;
global.window.scrollTo = () => {};
global.window.innerHeight = 800;
global.window.innerWidth = 400;
global.currentNourishDate = '2026-10-22';
let confettiCalls = [];
global.window.confetti = Object.assign(
  function(opts) { confettiCalls.push(opts); },
  {
    create: function() {
      return function(opts) { confettiCalls.push(opts); };
    }
  }
);
global.document = {
  body: { scrollTop: 0 },
  documentElement: { scrollTop: 0 },
  getElementById(id) { return elements[id] || null; },
  querySelector(sel) {
    if (sel === '.header') return headerEl;
    if (sel.startsWith('#')) return elements[sel.slice(1)] || null;
    return null;
  }
};
global.$ = (sel) => global.document.querySelector(sel);
global.currentScreen = 'home';
global.currentStore = null;
global.sgItems = [];
global.loadData = () => Promise.resolve();
global.loadStillGood = () => {};
let nourishLoaded = 0;
global.loadNourishDay = () => { nourishLoaded++; };

eval(fns);

(async () => {
  // 1. Spotlight initializes visible when unseen, then dismisses on toggle
  initAppSwitcherSpotlight();
  if (!elements.appSwitcherSpotlight.classList.contains('show')) throw new Error('Spotlight should show initially');
  toggleAppSwitcherMenu({ stopPropagation() {} });
  if (!elements.appSwitcherMenu.classList.contains('show')) throw new Error('Menu should open');
  if (localStorage.getItem('lm_app_switcher_seen_v1') !== '1') throw new Error('Spotlight should mark seen');

  // 2. Urgent badge sync
  global.sgItems = [{ status: 'active', urgency: 'urgent' }, { status: 'active', urgency: 'fresh' }];
  syncStillGoodSwitcherBadges();
  if (elements.sgHomeBadge.textContent !== '1') throw new Error('Expected sgHomeBadge=1');
  if (elements.appSwitcherSgBadge.textContent !== '1 urgent') throw new Error('Expected appSwitcherSgBadge="1 urgent"');
  if (elements.appSwitcherUrgentDot.style.display !== 'block') throw new Error('Expected urgent dot visible');

  // 3. Free user gating on Nourish
  global.window.currentCfg = { subscription_status: 'free', is_premium: false };
  await showNourishScreen();
  if (!elements.premiumModal.classList.contains('active')) throw new Error('Paywall modal should open for free user');
  if (elements.premiumModalTitle.textContent !== 'Nourish is a Premium Feature') throw new Error('Unexpected modal title');

  // 4. Premium user navigation to Nourish via selectSuiteApp and logo visibility
  elements.premiumModal.classList.remove('active');
  global.window.currentCfg = { subscription_status: 'active', is_premium: true };
  selectSuiteApp('nourish');
  await new Promise(r => setTimeout(r, 10));
  if (global.currentScreen !== 'nourish') throw new Error('Expected currentScreen=nourish');
  if (elements.headerTitle.textContent !== 'Nourish') throw new Error('Expected headerTitle=Nourish');
  if (elements.screenNourish.style.display !== 'block') throw new Error('Expected #screenNourish visible');
  if (elements.screenHome.style.display !== 'none') throw new Error('Expected #screenHome hidden');
  if (!elements.appSwitchItemNourish.classList.contains('active')) throw new Error('Expected Nourish menu item active');
  if (nourishLoaded !== 1) throw new Error('Expected loadNourishDay() to be called');
  if (elements.cartIcon.style.display !== 'none') throw new Error('Expected cartIcon hidden on nourish screen');
  if (elements.appSwitcherSgIcon.style.display !== 'none') throw new Error('Expected sgIcon hidden on nourish screen');
  if (elements.appSwitcherNourishIcon.style.display !== 'block') throw new Error('Expected nourishIcon visible on nourish screen');

  // 5. Still Good active state logo visibility
  updateAppSwitcherActiveState('stillGood');
  if (elements.cartIcon.style.display !== 'none') throw new Error('Expected cartIcon hidden on stillGood');
  if (elements.appSwitcherSgIcon.style.display !== 'flex') throw new Error('Expected sgIcon flex on stillGood');
  if (elements.appSwitcherNourishIcon.style.display !== 'none') throw new Error('Expected nourishIcon hidden on stillGood');

  // 6. Home active state logo visibility
  updateAppSwitcherActiveState('home');
  if (elements.cartIcon.style.display !== 'block') throw new Error('Expected cartIcon block on home');
  if (elements.appSwitcherSgIcon.style.display !== 'none') throw new Error('Expected sgIcon hidden on home');
  if (elements.appSwitcherNourishIcon.style.display !== 'none') throw new Error('Expected nourishIcon hidden on home');

  // 7. Confetti triggering
  fireStillGoodConfetti(elements.appSwitcherBtn);
  if (confettiCalls.length === 0) throw new Error('Expected confetti to fire');
})();

"""
        res = subprocess.run(
            ["node", "-e", node_test, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode, 0, f"Runtime sandbox test failed: {res.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
