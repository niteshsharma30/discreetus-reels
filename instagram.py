"""Posts Reels through the Instagram API with Instagram Login (graph.instagram.com).

No Facebook Page is needed: only an Instagram Business or Creator account and an Instagram access
token (IG_ACCESS_TOKEN). Posting is three steps: create a media container, wait until Instagram has
processed the video, publish it.

The token lasts 60 days. `refresh_token()` swaps it for a fresh 60-day one; the GitHub workflow does
this every day, so it never expires while the automation runs.

In dry-run nothing is sent: each request is written to data/requests.jsonl (token masked) and a
fake reply comes back.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import REQUEST_LOG, SETTINGS, ConfigError

BASE = "https://graph.instagram.com"


def _api(path: str) -> str:
    version = SETTINGS.ig_api_version.strip("/")
    return f"{BASE}/{version}/{path}" if version else f"{BASE}/{path}"


def media_link(media_path: str) -> str:
    """Turn "media/2026-11-13.mp4" into the public link Instagram downloads it from."""
    if media_path.startswith(("http://", "https://")):
        return media_path
    base = SETTINGS.media_base_url.rstrip("/")
    if not base:
        if not SETTINGS.dry_run:
            raise ConfigError("Set MEDIA_BASE_URL so Instagram can download the media (the GitHub workflow does this)")
        base = "https://example.com/media"
    return f"{base}/{Path(media_path).name}"


def publish(media_url: str, caption: str) -> str:
    """Post one Reel (.mp4) or image and return the Instagram media ID."""
    if not SETTINGS.dry_run and not SETTINGS.ig_access_token:
        raise ConfigError("Set IG_ACCESS_TOKEN (see README, 'Instagram access')")
    token = SETTINGS.ig_access_token
    ig = SETTINGS.ig_user_id or ("me" if SETTINGS.dry_run else _user_id(token))

    params = {"caption": caption, "access_token": token}
    if media_url.lower().split("?")[0].endswith((".mp4", ".mov")):
        params.update(media_type="REELS", video_url=media_url)
    else:
        params.update(image_url=media_url)
    container = _call("POST", _api(f"{ig}/media"), params)["id"]

    for _ in range(60):  # videos usually take 30-90 seconds to process
        code = _call("GET", _api(container), {"fields": "status_code", "access_token": token}).get("status_code")
        if code == "FINISHED":
            break
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram could not process the media ({code})")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram was still processing the media after 10 minutes")

    return _call("POST", _api(f"{ig}/media_publish"), {"creation_id": container, "access_token": token})["id"]


def refresh_token() -> tuple[str, int]:
    """Exchange the current long-lived token for a new 60-day one. Returns (token, seconds_valid).

    Instagram allows this once the token is at least 24 hours old and not yet expired.
    """
    if not SETTINGS.ig_access_token:
        raise ConfigError("IG_ACCESS_TOKEN is not set")
    body = _call("GET", f"{BASE}/refresh_access_token",
                 {"grant_type": "ig_refresh_token", "access_token": SETTINGS.ig_access_token}, log_response=False)
    return body["access_token"], int(body.get("expires_in", 0))


def _user_id(token: str) -> str:
    return str(_call("GET", _api("me"), {"fields": "user_id,username", "access_token": token})["user_id"])


def _call(method: str, url: str, params: dict, log_response: bool = True) -> dict:
    entry = {"dry_run": SETTINGS.dry_run, "method": method, "url": url,
             "params": {k: ("***" if k == "access_token" else v) for k, v in params.items()}}
    if SETTINGS.dry_run:
        fake = "dry_" + hashlib.sha1(f"{url}{params}".encode()).hexdigest()[:10]
        if url.endswith("refresh_access_token"):
            body = {"access_token": "dry-run-token", "token_type": "bearer", "expires_in": 5184000}
        elif method == "GET" and url.endswith("/me"):
            body = {"user_id": "dry_user", "username": "dry_run"}
        else:
            body = {"status_code": "FINISHED"} if method == "GET" else {"id": fake}
    else:
        r = requests.request(method, url, params=params, timeout=60)
        body = r.json() if r.content else {}
        entry["status"] = r.status_code
        if r.status_code >= 400:
            _log({**entry, "response": body})
            err = body.get("error", body)
            if isinstance(err, dict) and err.get("code") == 190:
                raise ConfigError("IG_ACCESS_TOKEN is invalid or expired; generate a new one (README, 'Instagram access')")
            raise RuntimeError(f"Instagram API error {r.status_code}: {err}")
    _log({**entry, "response": body if log_response else "(hidden: contains a token)"})
    return body


def _log(entry: dict) -> None:
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with REQUEST_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
