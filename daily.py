"""One cinematic Instagram Reel a day.

    python daily.py prepare    # AI writes today's post and the Reel is rendered into media/
    python daily.py publish    # posts today's Reel to Instagram
    python daily.py status     # what has been posted
    python daily.py refresh-token --out FILE   # renew the 60-day Instagram token (used by the workflow)

Every post is recorded in data/posts.csv (opens in Excel or Google Sheets).
DRY_RUN=true (the default) sends nothing; data/requests.jsonl shows the calls it would make.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import instagram
from config import POSTS_PATH, ROOT, SETTINGS, ConfigError
from writer import engine_name, policy_check, write_post

FIELDS = ["date", "status", "topic", "lines", "end_line", "motif", "palette",
          "caption", "hashtags", "media", "post_id", "notes"]
READY, BLOCKED, PUBLISHED, FAILED = "Ready", "Blocked", "Published", "Failed"


def load() -> list[dict]:
    if not POSTS_PATH.exists():
        return []
    with POSTS_PATH.open(newline="", encoding="utf-8") as f:
        return [{k: (r.get(k) or "") for k in FIELDS} for r in csv.DictReader(f)]


def save(rows: list[dict]) -> None:
    tmp = POSTS_PATH.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(POSTS_PATH)


def today() -> str:
    return datetime.now(ZoneInfo(SETTINGS.timezone)).strftime("%Y-%m-%d")


def render(row: dict) -> None:
    name = row["date"]
    if SETTINGS.post_format == "card":
        from media_cards import render_card
        path = render_card(row.get("card_text") or row["lines"].replace(" / ", " "), row["palette"], name)
    else:
        from media_reels import render_reel
        print(f"Rendering Reel ({row['motif']}, {row['palette']})...")
        path = render_reel({"lines": row["lines"].split(" / "), "end_line": row["end_line"],
                            "motif": row["motif"], "palette": row["palette"]}, name)
    row["media"] = f"media/{path.name}"
    print(f"Media: {row['media']} ({path.stat().st_size / 1e6:.1f} MB)")


def cmd_prepare(_args) -> None:
    rows = load()
    date = today()
    row = next((r for r in rows if r["date"] == date), None)

    if row and row["status"] == PUBLISHED:
        print(f"Today's post is already published ({row['post_id']}).")
        return
    if row and row["status"] == BLOCKED:
        print(f"Today's post was blocked: {row['notes']}. Delete its row in data/posts.csv to write a new one.")
        return

    if row is None:
        print(f"Writing today's post with {engine_name()}...")
        post = write_post([r["topic"] for r in rows], [r["motif"] for r in rows])
        row = {k: "" for k in FIELDS}
        row.update(date=date, topic=post["topic"], lines=" / ".join(post["lines"]), end_line=post["end_line"],
                   motif=post["motif"], palette=post["palette"], caption=post["caption"],
                   hashtags=post["hashtags"])
        row["card_text"] = post["card_text"]
        rows.append(row)

    hits = policy_check(" ".join([row["lines"], row["end_line"], row["caption"], row["hashtags"]]))
    if hits:
        row["status"], row["notes"] = BLOCKED, f"policy words: {', '.join(hits)}"
        save(rows)
        sys.exit(f"Blocked by the policy check ({', '.join(hits)}). Nothing will be posted today.")

    if not (row["media"] and (ROOT / row["media"]).exists()):
        render(row)                     # also re-renders after a failed run, from the saved script
    row["status"], row["notes"] = READY, ""
    save(rows)
    print(f"\n{'-' * 60}\nOn screen: {row['lines']}  //  {row['end_line']}\n\n{row['caption']}\n{row['hashtags']}\n{'-' * 60}")


def cmd_publish(_args) -> None:
    rows = load()
    row = next((r for r in rows if r["date"] == today()), None)
    if not row or row["status"] not in (READY, FAILED):
        print("Nothing to publish today." if not row else f"Today's post is {row['status']}.")
        return
    try:
        url = instagram.media_link(row["media"])
        row["post_id"] = instagram.publish(url, f"{row['caption']}\n\n{row['hashtags']}".strip())
        row["status"], row["notes"] = PUBLISHED, url
        print(f"Published to Instagram: {row['post_id']}")
    except ConfigError as e:
        sys.exit(f"Not posted, setup needed: {e}")
    except Exception as e:
        row["status"], row["notes"] = FAILED, str(e)[:300]
        save(rows)
        sys.exit(f"Instagram post failed: {e}")
    save(rows)


def cmd_status(_args) -> None:
    rows = load()
    if not rows:
        print("No posts yet.")
    for r in rows:
        print(f"{r['date']}  {r['status']:<9} {r['motif']:<11} {r['topic'][:50]}  {r['notes'][:40]}")


def cmd_refresh_token(args) -> None:
    """Write a fresh 60-day token to a file (never to the screen: workflow logs are public)."""
    if not args.out:
        sys.exit("Give --out FILE; the new token is written there, not printed")
    try:
        token, seconds = instagram.refresh_token()
    except Exception as e:
        sys.exit(f"Token not renewed: {e}")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(token)
    print(f"Token renewed; valid for {seconds // 86400} more days.")


def main() -> None:
    p = argparse.ArgumentParser(description="Daily Instagram Reel")
    p.add_argument("command", choices=["prepare", "publish", "status", "refresh-token"])
    p.add_argument("--out", help="refresh-token: file to write the new token to")
    args = p.parse_args()
    print(f"[{'DRY RUN, nothing is sent' if SETTINGS.dry_run else 'LIVE'}]")
    {"prepare": cmd_prepare, "publish": cmd_publish, "status": cmd_status,
     "refresh-token": cmd_refresh_token}[args.command](args)


if __name__ == "__main__":
    main()
