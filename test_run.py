import sys, os
from shared.auth import _run, _USERS
hhid = 1
try:
    members = _run(f"SELECT id FROM {_USERS} WHERE household_id = ?", (hhid,))
    print(members)
except Exception as e:
    print(e)
