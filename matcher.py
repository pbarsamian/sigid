"""
sigid/matcher.py — Signal matching and scoring

Three tiers:
  1. Hard filters  — frequency, modulation (fast, offline)
  2. Scored match  — weighted field similarity (offline)
  3. LLM assist    — Claude API vision on waterfall screenshot (needs connectivity)
"""

import base64
import json
import os
import urllib.request

from db import get_conn, search_signals

CLAUDE_API = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-6"


def _load_api_key():
    """Load Claude API key from .env file or environment variable."""
    # check environment first
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # fall back to .env file next to this script
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
# Tier 1 + 2: local DB matching
# ---------------------------------------------------------------------------

MODULATION_ALIASES = {
    "fm":    ["FM", "NFM", "WFM", "F3E"],
    "am":    ["AM", "DSB", "A3E"],
    "ssb":   ["SSB", "LSB", "USB", "J3E"],
    "fsk":   ["FSK", "AFSK", "GFSK", "2FSK", "4FSK"],
    "psk":   ["PSK", "BPSK", "QPSK", "8PSK"],
    "ofdm":  ["OFDM"],
    "lora":  ["LORA", "CSS"],
    "cw":    ["CW", "OOK", "ASK"],
    "digi":  ["DIGITAL", "DATA"],
}


def normalise_modulation(mod_str):
    """Map user-friendly modulation input to a list of DB patterns to match."""
    if not mod_str:
        return []
    key = mod_str.strip().lower()
    return MODULATION_ALIASES.get(key, [mod_str.upper()])


def score_signal(signal, freq_mhz=None, modulation=None, bandwidth_khz=None):
    """
    Return a 0-100 relevance score for a signal dict.
    Higher = better match.
    """
    score = 0

    # --- frequency match (40 pts) ---
    if freq_mhz is not None:
        lo = signal.get("freq_lower_mhz")
        hi = signal.get("freq_upper_mhz")
        if lo is not None and hi is not None:
            if lo <= freq_mhz <= hi:
                score += 40
            else:
                # partial credit for being close
                dist = min(abs(freq_mhz - lo), abs(freq_mhz - hi))
                if dist < 1:
                    score += 20
                elif dist < 10:
                    score += 5
        elif lo is not None:
            if abs(lo - freq_mhz) < 1:
                score += 20
        elif hi is not None:
            if abs(hi - freq_mhz) < 1:
                score += 20
        else:
            # no frequency data on this signal — neutral
            score += 10

    # --- modulation match (40 pts) ---
    if modulation:
        patterns = normalise_modulation(modulation)
        db_mod = (signal.get("modulation") or "").upper()
        if any(p in db_mod for p in patterns):
            score += 40
        elif db_mod:
            score += 0
        else:
            score += 10   # unknown modulation in DB — don't penalise

    # --- has media (10 pts each) ---
    if signal.get("waterfall_local") or signal.get("waterfall_url"):
        score += 5
    if signal.get("audio_local") or signal.get("audio_url"):
        score += 5

    return min(score, 100)


def match_signals(freq_mhz=None, modulation=None, bandwidth_khz=None,
                  name_fragment=None, limit=10):
    """
    Return top matching signals with scores, sorted best-first.
    All parameters optional.
    """
    # Pull candidates from DB (broad filter)
    candidates = search_signals(
        freq_mhz=freq_mhz,
        modulation=modulation,
        name_fragment=name_fragment,
        limit=200,   # score from a wide pool
    )

    # Score and sort
    scored = []
    for sig in candidates:
        s = score_signal(sig, freq_mhz=freq_mhz, modulation=modulation,
                         bandwidth_khz=bandwidth_khz)
        scored.append((s, sig))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(score, sig) for score, sig in scored[:limit]]


# ---------------------------------------------------------------------------
# Tier 3: LLM vision assist
# ---------------------------------------------------------------------------

def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def llm_identify(image_path=None, image_b64=None, context_text=None,
                 top_candidates=None):
    """
    Send a waterfall screenshot to Claude and ask for signal identification.

    image_path     : local path to the screenshot
    image_b64      : pre-encoded base64 string (alternative to image_path)
    context_text   : optional string with known context (freq, modulation hint)
    top_candidates : optional list of DB candidate signal names to hint at

    Returns dict with keys: identification, confidence, reasoning, next_steps
    """
    if image_path:
        image_b64 = encode_image(image_path)
    if not image_b64:
        return {"error": "No image supplied"}

    # Build the prompt
    candidate_hint = ""
    if top_candidates:
        names = ", ".join(top_candidates[:5])
        candidate_hint = (
            f"\n\nThe local Signal ID Wiki database suggests these as possible "
            f"matches based on frequency/modulation: {names}. "
            f"Consider these but don't be limited to them."
        )

    context_hint = f"\n\nKnown context: {context_text}" if context_text else ""

    prompt = f"""You are an expert RF signal analyst. 
Examine this waterfall / spectrum screenshot from an SDR receiver and identify the signal.

Provide your response as JSON with these exact keys:
{{
  "identification": "Signal name or type",
  "confidence": "high | medium | low",
  "reasoning": "Brief explanation of key visual features that led to this identification",
  "frequency_range": "Estimated frequency range if visible",
  "modulation": "Modulation type if identifiable",
  "next_steps": "What to try next to confirm or decode this signal",
  "wiki_search": "Suggested search term for Signal ID Wiki"
}}
{context_hint}{candidate_hint}

Return only the JSON object, no preamble."""

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 1000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }).encode()

    api_key = _load_api_key()
    if not api_key:
        return {"error": "No API key found. Create a .env file with ANTHROPIC_API_KEY=sk-ant-..."}

    req = urllib.request.Request(
        CLAUDE_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        text = data["content"][0]["text"].strip()
        # strip markdown fences if present
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------

def identify(freq_mhz=None, modulation=None, bandwidth_khz=None,
             name_fragment=None, image_path=None, image_b64=None,
             use_llm=False):
    """
    Full identification pipeline.
    Returns dict with:
        db_matches  : list of (score, signal_dict)
        llm_result  : dict or None
    """
    db_matches = match_signals(
        freq_mhz=freq_mhz,
        modulation=modulation,
        bandwidth_khz=bandwidth_khz,
        name_fragment=name_fragment,
    )

    llm_result = None
    if use_llm and (image_path or image_b64):
        context_parts = []
        if freq_mhz:
            context_parts.append(f"Frequency: {freq_mhz} MHz")
        if modulation:
            context_parts.append(f"Modulation hint: {modulation}")
        if bandwidth_khz:
            context_parts.append(f"Bandwidth: {bandwidth_khz} kHz")
        context_text = ", ".join(context_parts) or None

        top_names = [s["name"] for _, s in db_matches[:5]]

        llm_result = llm_identify(
            image_path=image_path,
            image_b64=image_b64,
            context_text=context_text,
            top_candidates=top_names,
        )

    return {
        "db_matches": db_matches,
        "llm_result": llm_result,
    }
