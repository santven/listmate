import os

# Update app.py
with open("/tmp/lm/app.py", "r") as f:
    app_code = f.read()
app_code = app_code.replace("'projectId': 'srp-timezone-api-1522941345463'", "'projectId': 'listmate-58e1a'")
with open("/tmp/lm/app.py", "w") as f:
    f.write(app_code)

# Update shared/auth.py
with open("/tmp/lm/shared/auth.py", "r") as f:
    auth_code = f.read()
auth_code = auth_code.replace("'projectId': 'srp-timezone-api-1522941345463'", "'projectId': 'listmate-58e1a'")
with open("/tmp/lm/shared/auth.py", "w") as f:
    f.write(auth_code)

# Update static/login.html
with open("/tmp/lm/static/login.html", "r") as f:
    login_code = f.read()

old_config = """  const firebaseConfig = {
    apiKey: "AIzaSyDuNcxOFLFJ1o3ScGnHsf1MY9OaIjMNgHI",
    authDomain: "srp-timezone-api-1522941345463.firebaseapp.com",
    projectId: "srp-timezone-api-1522941345463",
    storageBucket: "srp-timezone-api-1522941345463.appspot.com",
    messagingSenderId: "366597861699",
    appId: "1:366597861699:web:708b146f82a90ad05afff6"
  };"""

new_config = """  const firebaseConfig = {
    apiKey: "AIzaSyCeJfIMxeoqSXergNSLnk8vKy_b-60P0cM",
    authDomain: "listmate-58e1a.firebaseapp.com",
    projectId: "listmate-58e1a",
    storageBucket: "listmate-58e1a.firebasestorage.app",
    messagingSenderId: "822823530036",
    appId: "1:822823530036:web:YOUR_WEB_APP_ID"
  };"""

login_code = login_code.replace(old_config, new_config)

# Update fallback Client ID
old_client_id = "client_id: '366597861699-l8k2r9adgtm9sgipbmo4idgu5dm6vluq.apps.googleusercontent.com'"
new_client_id = "client_id: '822823530036-6iv0vumnlekal4u1kepre8fd2efbueqa.apps.googleusercontent.com'"
login_code = login_code.replace(old_client_id, new_client_id)

with open("/tmp/lm/static/login.html", "w") as f:
    f.write(login_code)

print("Patching complete.")
