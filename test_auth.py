from app import app
from shared.auth import get_household_status, _run, _HH, _USERS
# We can't easily mock the JWT, but we can verify get_household_status logic manually.
