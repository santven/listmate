import os
with open("/tmp/lm/static/login.html", "r") as f:
    code = f.read()

old_web_try = """  } else {
    try {
      const provider = new window._GoogleAuthProvider();"""

new_web_try = """  } else {
    try {
      console.log("Firebase Auth checking from origin:", window.location.origin);
      if (!window._GoogleAuthProvider) throw new Error("Firebase SDK is still loading.");
      const provider = new window._GoogleAuthProvider();"""

code = code.replace(old_web_try, new_web_try)

old_web_catch = """    } catch (error) {
      showError('Web sign in error: ' + error.message);
    }"""

new_web_catch = """    } catch (error) {
      console.error("Firebase Web Login Error:", error);
      if (error.code === 'auth/unauthorized-domain') {
        showError('Domain (' + window.location.hostname + ') is not authorized. Please check Firebase AND Google Cloud API Key restrictions. Falling back...');
        setTimeout(function() {
            var intentId = Math.random().toString(36).slice(2) + Date.now().toString(36);
            startPollingIntent(intentId);
            var params = new URLSearchParams({
              client_id: '366597861699-l8k2r9adgtm9sgipbmo4idgu5dm6vluq.apps.googleusercontent.com',
              redirect_uri: location.origin + '/login',
              response_type: 'id_token',
              scope: 'openid email profile',
              prompt: 'select_account',
              nonce: Math.random().toString(36).slice(2),
              state: 'intent_' + intentId
            });
            window.location.href = 'https://accounts.google.com/o/oauth2/v2/auth?' + params.toString();
        }, 3000);
      } else {
        showError('Web sign in error: ' + error.message);
      }
    }"""

code = code.replace(old_web_catch, new_web_catch)

with open("/tmp/lm/static/login.html", "w") as f:
    f.write(code)
