import os
import re
import subprocess
import unittest

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_HTML_PATH = os.path.join(REPO_DIR, "static", "login.html")
INDEX_HTML_PATH = os.path.join(REPO_DIR, "static", "index.html")


class TestGtmAnalyticsTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LOGIN_HTML_PATH, "r", encoding="utf-8") as f:
            cls.login_html = f.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.index_html = f.read()

    def test_login_html_gtm_page_view_structure(self):
        """Verify login.html contains GTM loader and pushes page_view event."""
        self.assertIn("window.dataLayer = window.dataLayer || []", self.login_html)
        self.assertIn("GTM_CONTAINER_ID_PLACEHOLDER", self.login_html)
        self.assertIn("'page_view'", self.login_html)
        self.assertIn("'/login'", self.login_html)
        self.assertIn("'ListMate · Login'", self.login_html)

    def test_login_html_script_execution_in_node(self):
        """Execute login.html GTM script block in Node with mocked DOM and verify dataLayer."""
        node_script = """
        const fs = require('fs');
        const html = fs.readFileSync('static/login.html', 'utf8');
        const scriptMatch = html.match(/<script(?![^>]*src=)(?![^>]*type=["']module["'])[^>]*>([\\s\\S]*?)<\\/script>/i);
        if (!scriptMatch) {
            console.error('No script found');
            process.exit(1);
        }

        // Mock browser environment
        const scriptTags = [];
        global.document = {
            getElementsByTagName: (tag) => {
                if (tag === 'script') {
                    return [{
                        parentNode: {
                            insertBefore: (newNode, refNode) => {
                                scriptTags.push(newNode);
                            }
                        }
                    }];
                }
                return [];
            },
            createElement: (tag) => {
                return { tagName: tag, src: '', async: false };
            },
            head: {
                appendChild: (node) => scriptTags.push(node)
            }
        };
        global.window = global;
        global.dataLayer = undefined;
        global._gtmLoaded = undefined;

        // Evaluate script
        eval(scriptMatch[1]);

        // 1. dataLayer should have initial page_view event
        const pageViewEvent = (window.dataLayer || []).find(e => e.event === 'page_view');
        if (!pageViewEvent) {
            console.error('Initial page_view event missing in dataLayer:', window.dataLayer);
            process.exit(2);
        }
        if (pageViewEvent.page_path !== '/login' || pageViewEvent.page_title !== 'ListMate · Login') {
            console.error('Invalid page_view payload:', pageViewEvent);
            process.exit(3);
        }

        // 2. Call initGTM with container id
        window._initGTM('GTM-LOGIN999');
        const gtmJsEvent = (window.dataLayer || []).find(e => e.event === 'gtm.js');
        if (!gtmJsEvent) {
            console.error('gtm.js event missing in dataLayer after initGTM');
            process.exit(4);
        }
        const injectedScript = scriptTags.find(s => s.src && s.src.includes('GTM-LOGIN999'));
        if (!injectedScript) {
            console.error('GTM script tag not injected:', scriptTags);
            process.exit(5);
        }

        // 3. Duplicate init call should not add duplicate script or duplicate page_view
        const scriptCountBefore = scriptTags.length;
        const pageViewCountBefore = window.dataLayer.filter(e => e.event === 'page_view').length;
        window._initGTM('GTM-LOGIN999');
        if (scriptTags.length !== scriptCountBefore) {
            console.error('Duplicate script tag injected on second initGTM call');
            process.exit(6);
        }
        if (window.dataLayer.filter(e => e.event === 'page_view').length !== pageViewCountBefore) {
            console.error('Duplicate page_view pushed on second initGTM call');
            process.exit(7);
        }

        console.log('LOGIN_GTM_OK');
        """
        res = subprocess.run(
            ["node", "-e", node_script],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Node script failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("LOGIN_GTM_OK", res.stdout)

    def test_index_html_title_map_and_tracking_in_node(self):
        """Execute index.html GTM and trackScreenView logic in Node and verify payloads."""
        node_script = """
        const fs = require('fs');
        const html = fs.readFileSync('static/index.html', 'utf8');

        // Extract GTM block
        const gtmBlockMatch = html.match(/const titleMap = \\{([\\s\\S]*?)\\};[\\s\\S]*?window\\.trackScreenView = trackScreenView;/);
        if (!gtmBlockMatch) {
            console.error('GTM tracking block not found in static/index.html');
            process.exit(1);
        }

        // Mock browser environment
        const scriptTags = [];
        global.document = {
            getElementsByTagName: (tag) => {
                if (tag === 'script') {
                    return [{
                        parentNode: {
                            insertBefore: (newNode, refNode) => scriptTags.push(newNode)
                        }
                    }];
                }
                return [];
            },
            createElement: (tag) => ({ tagName: tag, src: '', async: false }),
            head: { appendChild: (n) => scriptTags.push(n) }
        };
        global.window = global;
        global.dataLayer = [];

        eval(gtmBlockMatch[0]);

        // Validate titleMap
        const expectedScreens = {
            'home': { path: '/', title: 'ListMate · Grocery List' },
            'stillGood': { path: '/stillGood', title: 'ListMate · Still Good' },
            'nourish': { path: '/nourish', title: 'ListMate · Nourish' },
            'recipes': { path: '/recipes', title: 'ListMate · Recipe Planner' },
            'analytics': { path: '/analytics', title: 'ListMate · Analytics' },
            'globalVisits': { path: '/globalVisits', title: 'ListMate · Store Visits' },
            'visitDetail': { path: '/visitDetail', title: 'ListMate · Visit Details' }
        };

        for (const [screen, expected] of Object.entries(expectedScreens)) {
            window.trackScreenView(screen);
            const last = window.dataLayer[window.dataLayer.length - 1];
            if (!last || last.event !== 'virtual_page_view') {
                console.error('Wrong event for ' + screen + ':', last);
                process.exit(2);
            }
            if (last.page_path !== expected.path) {
                console.error('Path mismatch for ' + screen + ': expected ' + expected.path + ', got ' + last.page_path);
                process.exit(3);
            }
            if (last.page_title !== expected.title) {
                console.error('Title mismatch for ' + screen + ': expected ' + expected.title + ', got ' + last.page_title);
                process.exit(4);
            }
            if (last.screen_name !== screen || last.authenticated !== true) {
                console.error('screen_name or authenticated mismatch for ' + screen + ':', last);
                process.exit(5);
            }
        }

        // Test fallback to window.currentScreen
        window.currentScreen = 'stillGood';
        window.trackScreenView();
        const fallbackLast = window.dataLayer[window.dataLayer.length - 1];
        if (fallbackLast.screen_name !== 'stillGood' || fallbackLast.page_title !== 'ListMate · Still Good') {
            console.error('Fallback failed:', fallbackLast);
            process.exit(6);
        }

        // Test custom screen
        window.trackScreenView('myCustomScreen');
        const customLast = window.dataLayer[window.dataLayer.length - 1];
        if (customLast.page_path !== '/myCustomScreen' || customLast.page_title !== 'ListMate · myCustomScreen') {
            console.error('Custom screen tracking failed:', customLast);
            process.exit(7);
        }

        // Test GTM script injection
        window.initGTM('GTM-INDEX555');
        const gtmScript = scriptTags.find(s => s.src && s.src.includes('GTM-INDEX555'));
        if (!gtmScript) {
            console.error('GTM script tag not injected for index.html');
            process.exit(8);
        }

        // Test duplicate injection prevention
        const scriptLen = scriptTags.length;
        window.initGTM('GTM-INDEX555');
        if (scriptTags.length !== scriptLen) {
            console.error('Duplicate script injected in index.html');
            process.exit(9);
        }

        console.log('INDEX_GTM_OK');
        """
        res = subprocess.run(
            ["node", "-e", node_script],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Node script failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("INDEX_GTM_OK", res.stdout)

    def test_show_screen_invokes_track_screen_view(self):
        """Verify showScreen(name) calls trackScreenView(name)."""
        show_screen_match = re.search(r"function showScreen\(name\)\s*\{([\s\S]*?)\n\}", self.index_html)
        self.assertIsNotNone(show_screen_match, "function showScreen(name) not found")
        body = show_screen_match.group(1)
        self.assertIn("trackScreenView(name)", body)

    def test_load_config_initializes_gtm_and_tracks_initial_screen(self):
        """Verify loadConfig initializes GTM with cfg.gtm_container_id and tracks initial screen."""
        self.assertIn("cfg.gtm_container_id", self.index_html)
        self.assertIn("initGTM(cfg.gtm_container_id)", self.index_html)
        self.assertIn("trackScreenView(window.currentScreen", self.index_html)


if __name__ == "__main__":
    unittest.main()
