#!/bin/bash
# Double-click in Finder to launch the Baton menu bar app.
cd "$(dirname "$0")"
exec .venv/bin/python menubar.py
