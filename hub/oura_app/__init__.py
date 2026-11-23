"""Oura API v2 integration (task 5, REQ-OURA-01..07).

Sign in once with OAuth2 (authorization code + PKCE, localhost callback), keep the tokens in
Windows Credential Manager, pull sleep periods (with the 30 s and 5 min hypnograms), daily sleep
and heart rate, convert every timestamp to UTC, and store them locally under data/oura/
(git-ignored: it is personal health data). Run it from the repo root:

    .\\venv\\Scripts\\python.exe -m hub.oura_app login
    .\\venv\\Scripts\\python.exe -m hub.oura_app pull --days 30
    .\\venv\\Scripts\\python.exe -m hub.oura_app nights
"""
