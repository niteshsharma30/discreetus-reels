"""Posts Reels to Instagram through Meta's Graph API (graph.facebook.com).

Needs two settings, both from your Meta app (README, "Instagram access"):
    IG_ACCESS_TOKEN  a system-user token made with "API setup with Unified login". It doesn't expire.
    IG_USER_ID       the Instagram account's ID, shown next to the account when you add it.
No Facebook Page is involved. Posting is: check the daily quota, create a media container,
wait until Instagram has processed the video, publish it.

In dry-run nothing is sent: each request is written to data/requests.jsonl (token masked)
and a fake reply comes back.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import REQUEST_LOG, SETTINGS, ConfigError

BASE = "https://graph.facebook.com"


def _api(path: str) -> str:
    version = SETTINGS.graph_api_version.strip("/")
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
    if not SETTINGS.dry_run and not (SETTINGS.ig_access_token and SETTINGS.ig_user_id):
        raise ConfigError("Set IG_ACCESS_TOKEN and IG_USER_ID (see README, 'Instagram access')")
    token = SETTINGS.ig_access_token
    ig = SETTINGS.ig_user_id or "{IG_USER_ID}"

    # Instagram allows a limited number of posts per 24 hours; don't try past it.
    limit = _call("GET", _api(f"{ig}/content_publishing_limit"),
                  {"fields": "quota_usage,config", "access_token": token})
    info = (limit.get("data") or [{}])[0]
    if info.get("quota_usage", 0) >= info.get("config", {}).get("quota_total", 100):
        raise RuntimeError("Instagram's 24-hour posting limit is reached; try again later")

    params = {"caption": caption, "access_token": token}
    if media_url.lower().split("?")[0].endswith((".mp4", ".mov")):
        params.update(media_type="REELS", video_url=media_url, share_to_feed="true")
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


def _call(method: str, url: str, params: dict) -> dict:
    entry = {"dry_run": SETTINGS.dry_run, "method": method, "url": url,
             "params": {k: ("***" if k == "access_token" else v) for k, v in params.items()}}
    if SETTINGS.dry_run:
        fake = "dry_" + hashlib.sha1(f"{url}{params}".encode()).hexdigest()[:10]
        if url.endswith("/content_publishing_limit"):
            body = {"data": [{"quota_usage": 0, "config": {"quota_total": 100, "quota_duration": 86400}}]}
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
                raise ConfigError("IG_ACCESS_TOKEN is invalid or was revoked; generate a new one "
                                  "(README, 'Instagram access')")
            raise RuntimeError(f"Instagram API error {r.status_code}: {err}")
    _log({**entry, "response": body})
    return body


def _log(entry: dict) -> None:
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with REQUEST_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
