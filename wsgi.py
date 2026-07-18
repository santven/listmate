#!/usr/bin/env python3
"""Gunicorn entrypoint — ensure DB is initialized before serving."""
from db import init_db
init_db()
from app import app
