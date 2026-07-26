#!/usr/bin/env python3
"""Gunicorn entrypoint."""
import db
db.init_db()
from app import app
