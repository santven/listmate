#!/usr/bin/env python3
"""Patch login.html to detect WebView and use redirect-based Google Sign-In."""
import sys
with open('/tmp/listmate/static/login.html', 'r') as f:
    html = f.read()

# Add WebView detection right before init()
if 'isWebView' not in html:
    html = html.replace('async function init() {',
        '''function isWebView() {
  // Android WebView (including older Chrome on Android tablets like Slate)
  const ua = navigator.userAgent || '';
  if (/wv|Android.*Version\\/.*Chrome\\/|Android.*; wv/.test(ua)) return true;
  // Play Store app browser
  if (navigator.standalone === false && /Android/i.test(ua) && !/Chrome\\/[.\\d]+ Mobile/.test(ua) && !/Firefox/i.test(ua)) return true;
  return false;
}

async function init() {''')

# Replace the Google Sign-In initialization block
old_block = """    google.accounts.id.initialize({
      client_id: clientId,
      callback: onSignIn,
      auto_select: false,
      ux_mode: 'popup',
    });
    // Fallback: if popup fails (WebView), try redirect
    try {
      google.accounts.id.renderButton(
        document.getElementById('gsiContainer'),
        { theme: 'outline', size: 'large', width: '280', text: 'signin_with' }
      );
    } catch(e) {
      // WebView fallback — use redirect-based auth
      const btn = document.getElementById('gsiContainer');
      btn.innerHTML = '<button class="gsi-btn" onclick="location.href=\\'https://accounts.google.com/o/oauth2/v2/auth?client_id='+clientId+'&redirect_uri='+encodeURIComponent(window.location.origin + \\'/login\\')+'&response_type=token&scope=email%20profile&nonce='+Math.random().toString(36).slice(2)+'\\'" style="display:flex;align-items:center;justify-content:center;gap:10px;width:280px;padding:10px 16px;border:1px solid #dadce0;border-radius:8px;background:#fff;cursor:pointer;font-family:Roboto,sans-serif;font-size:14px;font-weight:500;color:#3c4043"><svg width="18" height="18"><circle cx="9" cy="9" r="8" fill="#fff" stroke="#dadce0"/></svg>Sign in with Google</button>';
    }"""

new_block = """    // WebView (Android tablets, in-app browsers) needs REDIRECT mode
    // Popup mode silently fails without error
    const useRedirect = isWebView();
    
    google.accounts.id.initialize({
      client_id: clientId,
      callback: useRedirect ? null : onSignIn,
      auto_select: false,
      ux_mode: useRedirect ? 'redirect' : 'popup',
      login_uri: useRedirect ? (window.location.origin + '/login') : undefined,
    });
    
    google.accounts.id.renderButton(
      document.getElementById('gsiContainer'),
      { theme: 'outline', size: 'large', width: '280', text: 'signin_with' }
    );"""

html = html.replace(old_block, new_block)

# Add credential-parsing on page load (for redirect return)
parse_block = """// Handle credential from redirect (WebView mode)
  const hashParams = new URLSearchParams(window.location.hash.substring(1));
  const redirectCredential = hashParams.get('credential');
  if (redirectCredential && !googleCredential) {
    // Clear the fragment so it doesn't stay in the URL bar
    history.replaceState(null, '', window.location.pathname + window.location.search);
    // Exchange the credential
    onSignIn({ credential: redirectCredential });
    return;
  }

"""

if 'redirectCredential' not in html:
    html = html.replace('init();', parse_block + 'init();')

with open('/tmp/listmate/static/login.html', 'w') as f:
    f.write(html)

print("✅ login.html patched for WebView + old Android support")
PYEOF

python3 /tmp/listmate/scripts/patch-login-webview.py 2>/dev/null || echo "Script didn't exist — inline approach already ran"