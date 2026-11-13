"""Writes each day's post: on-screen lines for the Reel, its look, the caption and hashtags.

Uses the Google Gemini API free tier, steered by your creative direction in
prompts/instagram_prompt.md. Every result goes through `policy_check`, which blocks
words that get dating content restricted or make the brand read as an affair app.
"""
from __future__ import annotations

import json
import re
import time

import requests

from config import PROMPT_PATH, SETTINGS, ConfigError

MOTIFS = ["two_figures", "window", "orbit", "veil"]      # must match media_reels.py
PALETTES = ["midnight", "dusk", "rose", "teal"]

RULES = """You write daily Instagram posts for {brand}, a dating app that has not launched yet.
The goal of every post is curiosity: hint at what {brand} is bringing to dating, never explain it.

HARD RULES (Instagram policies and brand safety, these always win):
- Never imply secrecy from a partner, cheating or affairs. Say "private", "your terms", "in control",
  never "secret", "no one will know" or "discreet affair".
- Nothing sexual or suggestive. No hookup language. Everything is for adults.
- Never invent features, statistics, user numbers, reviews or testimonials.
- Captions can't hold clickable links, so point to the "link in bio".
"""

# Words that get dating content restricted or read as an affair app.
BANNED = [
    r"\bsecret\w*", r"no one will (ever )?know", r"\baffair\w*", r"\bcheat\w*", r"\bhook ?ups?\b",
    r"\bsugar (daddy|baby|dating)", r"\bescort\w*", r"\bsexy\b", r"\bnsfw\b", r"\bone[- ]night\b",
    r"\bmarried\b", r"\binfidel\w*", r"\bdtf\b",
]

# Used only in dry-run without an AI key, so you can try the pipeline without signing up for anything.
SAMPLE = {
    "topic": "Being seen only by who you choose",
    "lines": ["Every room has a hundred eyes.", "Only one pair matters.", "What if only they could see you?"],
    "end_line": "Dating, reimagined. Quietly.",
    "motif": "two_figures", "palette": "midnight",
    "caption": "Every room has a hundred eyes.\n\nWe're building something for the one pair that matters.\n\n"
               "Join the waitlist, link in bio.",
    "hashtags": "#ComingSoon #ModernDating #DatingOnYourTerms",
    "card_text": "Every room has a hundred eyes. Only one pair matters.",
}


def policy_check(text: str) -> list[str]:
    """Return the banned phrases found (empty list = clean)."""
    return [m.group(0) for p in BANNED if (m := re.search(p, text, flags=re.IGNORECASE))]


def engine_name() -> str:
    if SETTINGS.gemini_api_key:
        return f"Gemini free tier ({SETTINGS.gemini_model})"
    return "built-in sample (no GEMINI_API_KEY)"


# The shape the reply must have. Gemini is asked for JSON in exactly this form.
POST_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "string"}},
        "end_line": {"type": "string"},
        "motif": {"type": "string", "enum": MOTIFS},
        "palette": {"type": "string", "enum": PALETTES},
        "card_text": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "string"},
    },
    "required": ["topic", "lines", "end_line", "motif", "palette", "card_text", "caption", "hashtags"],
    "additionalProperties": False,
}


def write_post(recent_topics: list[str], recent_motifs: list[str]) -> dict:
    """Return {'topic','lines','end_line','motif','palette','caption','hashtags','card_text'}."""
    if not SETTINGS.gemini_api_key:
        if SETTINGS.dry_run:
            return dict(SAMPLE)
        raise ConfigError("Set GEMINI_API_KEY (free at aistudio.google.com/apikey)")

    direction = "\n".join(l for l in PROMPT_PATH.read_text(encoding="utf-8").splitlines()
                          if not l.lstrip().startswith("<!--")).strip()
    system = RULES.format(brand=SETTINGS.brand_name) + "\nCREATIVE DIRECTION:\n" + direction
    avoid = "\n".join(f"- {t}" for t in recent_topics[-30:]) or "- (none yet)"
    user = f"""Create today's Instagram post.

The video is a 10-17 second cinematic animated Reel, rendered automatically from your script, so you only
choose words and a look:
- lines: 2 to 4 short on-screen lines (each under 42 characters) that tell a tiny, emotionally relatable
  story and build curiosity. They appear one at a time in an elegant serif. Hint, don't explain.
- end_line: one line under 40 characters shown under the brand name at the end.
- motif: two_figures (two silhouettes drift toward each other and a thread of light joins them),
  window (one figure backlit by a glowing city window), orbit (two lights circle closer and merge),
  or veil (a figure behind frosted glass slowly comes into focus). Pick the one that fits the story.
  Recently used: {", ".join(recent_motifs[-3:]) or "none"}.
- palette: midnight, dusk, rose or teal.
- card_text: the same idea in one line under 90 characters (used if a still image is posted instead).
- caption: 60-150 words, short lines, first line under 125 characters, continues the mystery, ends with
  a call to join the waitlist (link in bio). Waitlist: {SETTINGS.waitlist_url or "link in bio"}.
- hashtags: 5-8 relevant hashtags in one string, separated by spaces.
- topic: a few words naming today's idea, so future posts can avoid repeating it.

Topics already posted, pick something clearly different:
{avoid}"""

    data = _ask(system, user)
    post = {k: str(data.get(k, "")).strip() for k in
            ("topic", "end_line", "motif", "palette", "caption", "hashtags", "card_text")}
    post["lines"] = [str(l).strip() for l in (data.get("lines") or []) if str(l).strip()][:4]
    if not post["caption"] or not post["lines"]:
        raise ValueError(f"Gemini's reply was missing lines or caption: {str(data)[:200]}")
    post["motif"] = post["motif"] if post["motif"] in MOTIFS else MOTIFS[len(recent_motifs) % len(MOTIFS)]
    post["palette"] = post["palette"] if post["palette"] in PALETTES else PALETTES[0]
    post["card_text"] = post["card_text"] or " ".join(post["lines"])
    post["hashtags"] = " ".join(post["hashtags"].split()[:30])            # Instagram's limit
    post["caption"] = post["caption"][: 2150 - len(post["hashtags"])]     # 2,200 characters in total
    return post


# Tried in order. Newer models are sometimes overloaded or closed to new accounts, so fall back.
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]


def _ask(system: str, user: str) -> dict:
    user += "\n\nReply with JSON only, in exactly this shape:\n" + json.dumps(POST_SCHEMA)
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    models = list(dict.fromkeys([SETTINGS.gemini_model, *FALLBACK_MODELS]))
    problems = []
    for model in models:
        for attempt in (1, 2):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": SETTINGS.gemini_api_key, "content-type": "application/json"},
                    json=body, timeout=90,
                )
            except requests.RequestException as e:
                problems.append(f"{model}: {type(e).__name__}")
                continue                                   # timeout or network blip: retry once
            if r.status_code in (400, 401, 403) and "API key" in r.text:
                raise ConfigError("GEMINI_API_KEY was rejected; create a new key at aistudio.google.com/apikey")
            if r.status_code in (500, 502, 503, 504):      # Google is busy: wait, retry once, then next model
                problems.append(f"{model}: busy ({r.status_code})")
                if attempt == 1:
                    time.sleep(15)
                continue
            if r.status_code in (404, 429):                # model unavailable or its free quota used up
                problems.append(f"{model}: {_message(r)}")
                break
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini error {r.status_code} on {model}: {_message(r)}")

            candidate = (r.json().get("candidates") or [{}])[0]
            if candidate.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
                raise RuntimeError("Gemini declined to write today's post (safety filter). Nothing is posted.")
            text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                problems.append(f"{model}: reply was not JSON")
                continue
            print(f"  (written by {model})")
            return json.loads(match.group(0))
    raise RuntimeError("No Gemini model could write today's post: " + "; ".join(problems))


def _message(r) -> str:
    try:
        return r.json()["error"]["message"][:160]
    except Exception:
        return r.text[:160]
