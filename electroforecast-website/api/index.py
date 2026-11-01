"""Vercel entry point for the demo deploy.

Vercel's files are read-only, so each server instance copies deploy/demo.db to /tmp and works on that copy.
Changes (sign-ups, submissions, reviews, bill pictures) last only until the instance is shut down.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP_DB = Path("/tmp/electroforecast.db")

if not TMP_DB.exists():
    shutil.copyfile(ROOT / "deploy" / "demo.db", TMP_DB)
os.environ.setdefault("ELECTROFORECAST_DB", str(TMP_DB))
os.environ.setdefault("ELECTROFORECAST_UPLOADS", "/tmp/uploads/bills")
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402  (Vercel serves this WSGI app)
