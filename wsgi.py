#!/usr/bin/env python3
"""Gunicorn entrypoint."""
import db_pg
db_pg.init_db()
from app import app
