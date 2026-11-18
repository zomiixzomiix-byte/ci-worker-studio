"""Dual-mode AEGIS NEXUS & Standalone 61-Key Quality-Mix Client (Text, JSON, Multimodal, Free TTS)."""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AISTUDIO_BASE = "https://generativelanguage.googleapis.com/v1beta"
QUALITY_FLAGSHIP_CHAIN = [
    "gemini-4-hydrogen",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
]
QUALITY_MIX_SCHEDULE = [
    "gemini-4-hydrogen",
    "gemini-4-hydrogen",
    "gemini-3-flash-preview",
    "gemini-4-hydrogen",
    "gemini-3-flash-preview",
]
TTS_MODELS = [
    "gemini-3.8-flash-tts",
]
BLOCKED_DOWNGRADE_RE = re.compile(r"(?:^|[-_.])(lite|mini|nano)(?:$|[-_.])", re.I)
_KEY_LEAK_RE = re.compile(r"(AIza[0-9A-Za-z_-]{15,}|(?<=key=)[^&\s\"']+)")
_MASK_LOCK = threading.Lock()
_MASKED_KEYS: set[str] = set()


def _sanitize_error(msg: str) -> str:
    """Strip any Google API key or ?key= query token before logging or raising."""
    return _KEY_LEAK_RE.sub("[REDACTED]", str(msg or ""))


def _register_actions_masks(keys: list[dict[str, Any]]) -> None:
    """Register every parsed key with GitHub Actions log masking on Public runners."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    with _MASK_LOCK:
        for k in keys:
            val = str(k.get("apiKey") or "").strip()
            if val and val not in _MASKED_KEYS:
                _MASKED_KEYS.add(val)
                print(f"::add-mask::{val}", flush=True)


def extract_json_text(raw: str) -> str:
    """Extract clean JSON object or array from markdown-wrapped model text."""
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt, flags=re.I)
        txt = re.sub(r"\s*```$", "", txt)
    starts = [x for x in (txt.find("{"), txt.find("[")) if x != -1]
    if not starts:
        return txt
    s = min(starts)
    closer = "}" if txt[s] == "{" else "]"
    e = txt.rfind(closer)
    return txt[s : e + 1] if e > s else txt


def is_strong_flagship_model(model_name: str) -> bool:
    """Reject accidental lite/2.5-flash/2.0-flash downgrades."""
    m = (model_name or "").lower().strip()
    if not m:
        return True
    if BLOCKED_DOWNGRADE_RE.search(m) or any(b in m for b in ("2.5-flash", "2.0-flash")):
        return False
    return any(
        ok in m
        for ok in (
            "hydrogen",
            "flagship-mix",
            "3-flash",
            "3.5-flash",
            "3.6-flash",
            "3.7-flash",
            "3.8-flash",
            "3.1-pro",
        )
    )


def _adapt_thinking_config(gen_cfg: dict[str, Any], model_id: str) -> None:
    """Preserve deep reasoning across Gemini 4.x and 3.x endpoints."""
    tc = gen_cfg.get("thinkingConfig")
    if not isinstance(tc, dict):
        return
    m = model_id.lower()
    if any(x in m for x in ("-tts", "-image", "lite")):
        gen_cfg.pop("thinkingConfig", None)
        return
    if m.startswith(("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash")):
        budget = int(tc.pop("thinkingBudget", 0) or 0)
        if not tc.get("thinkingLevel"):
            tc["thinkingLevel"] = "HIGH" if budget >= 2048 else ("MEDIUM" if budget >= 1024 else "LOW")
        elif str(tc["thinkingLevel"]).upper() == "XHIGH":
            tc["thinkingLevel"] = "HIGH"


def _parse_keys_payload(raw_value: str | list[Any]) -> list[dict[str, Any]]:
    """Accept JSON array (full aistudio_keys.json or string list) or newline-separated keys."""
    if not raw_value:
        return []
    parsed: Any = raw_value
    if isinstance(raw_value, str):
        txt = raw_value.strip()
        if not txt:
            return []
        if txt.startswith("[") or txt.startswith("{"):
            parsed = json.loads(txt)
            if isinstance(parsed, dict) and "keys" in parsed:
                parsed = parsed["keys"]
        else:
            parsed = [line.strip() for line in txt.splitlines() if line.strip() and not line.strip().startswith("#")]

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(parsed):
        if isinstance(item, str) and item.strip():
            out.append({"id": f"k_{idx+1}", "label": f"Key #{idx+1}", "apiKey": item.strip()})
        elif isinstance(item, dict) and item.get("apiKey") and item.get("enabled", True) and item.get("status") != "invalid":
            out.append({
                "id": item.get("id") or f"k_{idx+1}",
                "label": item.get("label") or f"Key #{idx+1}",
                "apiKey": str(item["apiKey"]).strip(),
            })
    return out


class AegisStudioClient:
    """Unified AEGIS NEXUS client supporting both local/tunneled Gateway and Cloud Standalone Vault."""

    def __init__(
        self,
        base_url: str | None = None,
        keys_json: str | None = None,
        keys_file: str | Path | None = None,
        gateway_key: str | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.environ.get("AEGIS_BASE_URL", "http://127.0.0.1:20128")).rstrip("/")
        self.gateway_key = gateway_key or os.environ.get("AEGIS_GATEWAY_KEY", "")
        raw_keys = keys_json if keys_json is not None else os.environ.get("AISTUDIO_KEYS_JSON", "")
        if not raw_keys and keys_file and Path(keys_file).exists():
            raw_keys = Path(keys_file).read_text(encoding="utf-8")
        self.keys = _parse_keys_payload(raw_keys)
        random.shuffle(self.keys)
        _register_actions_masks(self.keys)
        self._lock = threading.Lock()
        self._mix_cursor = 0
        self._tts_cursor = random.randrange(len(TTS_MODELS))
        self._tts_pool_cooldown_until = 0.0
        self._rr_ts: dict[str, float] = {}
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._mode = self._detect_mode()

    def _detect_mode(self) -> str:
        if self.base_url:
            try:
                req = urllib.request.Request(f"{self.base_url}/api/settings", method="GET")
                with urllib.request.urlopen(req, timeout=2.5) as resp:
                    if resp.status == 200:
                        return "gateway"
            except Exception:
                pass
        if self.keys:
            return "standalone"
        return "gateway"

    @property
    def mode(self) -> str:
        return self._mode

    def next_quality_chain(self, preferred: str | None = None) -> list[str]:
        """Build zero-downgrade Quality Mix model chain with 60/40 rotation."""
        if preferred and preferred in QUALITY_FLAGSHIP_CHAIN:
            rest = [m for m in QUALITY_FLAGSHIP_CHAIN if m != preferred]
            return [preferred, *rest]
        with self._lock:
            lead = QUALITY_MIX_SCHEDULE[self._mix_cursor % len(QUALITY_MIX_SCHEDULE)]
            self._mix_cursor = (self._mix_cursor + 1) % len(QUALITY_MIX_SCHEDULE)
        return [lead, *[m for m in QUALITY_FLAGSHIP_CHAIN if m != lead]]

    def _pick_standalone_key(self, model_id: str, exclude: set[str]) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            ready = [
                k for k in self.keys
                if k["id"] not in exclude and self._cooldowns.get((k["id"], model_id), 0.0) <= now
            ]
            if not ready:
                return None
            ready.sort(key=lambda k: self._rr_ts.get(k["id"], 0.0))
            chosen = ready[0]
            self._rr_ts[chosen["id"]] = now
            return chosen

    def _mark_cooldown(self, key_id: str, model_id: str, status: int | None, err_msg: str) -> None:
        now = time.time()
        msg_l = err_msg.lower()
        if status in (401, 403):
            dur = 86400.0
        elif status == 429 and ("perday" in msg_l or "per day" in msg_l or "per_day" in msg_l or "daily" in msg_l or "limit: 0" in msg_l):
            dur = 4 * 3600.0
        elif status == 429:
            dur = 30.0 if "-tts" in model_id else 22.0
        elif status in (500, 502, 503, 504):
            dur = 12.0
        else:
            dur = 75.0
        with self._lock:
            self._cooldowns[(key_id, model_id)] = now + dur

    def _gateway_headers(self) -> dict[str, str]:
        hdrs = {"Content-Type": "application/json"}
        if self.gateway_key:
            hdrs["x-goog-api-key"] = self.gateway_key
        return hdrs

    def _standalone_headers(self, api_key: str) -> dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": api_key}

    def _attempt_timeout(self, model_id: str, chain: list[str], default_sec: int) -> int:
        if "4-hydrogen" in model_id:
            return max(default_sec, 180)
        if model_id != chain[-1] and any(x in model_id for x in ("3.6-flash", "3.7-flash", "3.8-flash")):
            return 22
        return default_sec

    def _post_native_gemini(self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 16384,
        thinking_budget: int = 2048,
        temperature: float = 0.25,
        timeout_sec: int = 180,
        preferred_model: str | None = None,
        extra_parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate structured JSON using AEGIS Gateway or Standalone 61-key Quality Mix."""
        parts = list(extra_parts or []) + [{"text": user_prompt}]
        base_payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        if thinking_budget > 0:
            base_payload["generationConfig"]["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingBudget": thinking_budget,
            }

        if self._mode == "gateway":
            model_name = preferred_model or "gemini-flagship-mix"
            last_err: Exception | None = None
            for attempt in range(4):
                try:
                    raw = self._post_native_gemini(
                        f"{self.base_url}/v1beta/models/{model_name}:generateContent",
                        self._gateway_headers(),
                        base_payload,
                        timeout_sec,
                    )
                    mv = str(raw.get("modelVersion") or model_name)
                    if not is_strong_flagship_model(mv):
                        raise RuntimeError(f"Blocked downgraded model: {mv}")
                    txt = _extract_parts_text(raw)
                    return {"data": json.loads(extract_json_text(txt)), "model": mv, "usage": raw.get("usageMetadata", {})}
                except Exception as exc:
                    last_err = exc
                    time.sleep(min(20.0, 2.5 * (attempt + 1)))
            raise RuntimeError(f"AEGIS Gateway JSON generation failed: {last_err}")

        if not self.keys:
            raise RuntimeError("No AEGIS Gateway running and no AISTUDIO_KEYS_JSON keys provided.")

        chain = self.next_quality_chain(preferred_model)
        last_err = None
        for model_id in chain:
            tried: set[str] = set()
            max_tries = min(len(self.keys), 15)
            for _ in range(max_tries):
                key_obj = self._pick_standalone_key(model_id, tried)
                if not key_obj:
                    break
                tried.add(key_obj["id"])
                payload = json.loads(json.dumps(base_payload))
                _adapt_thinking_config(payload["generationConfig"], model_id)
                url = f"{AISTUDIO_BASE}/models/{urllib.parse.quote(model_id)}:generateContent"
                tmo = self._attempt_timeout(model_id, chain, timeout_sec)
                try:
                    raw = self._post_native_gemini(url, self._standalone_headers(key_obj["apiKey"]), payload, tmo)
                    txt = _extract_parts_text(raw)
                    mv = str(raw.get("modelVersion") or model_id)
                    if not is_strong_flagship_model(mv):
                        raise RuntimeError(f"Blocked downgraded model: {mv}")
                    return {"data": json.loads(extract_json_text(txt)), "model": mv, "key": key_obj["label"], "usage": raw.get("usageMetadata", {})}
                except urllib.error.HTTPError as he:
                    msg = _sanitize_error(he.read().decode("utf-8", "ignore")[:240])
                    self._mark_cooldown(key_obj["id"], model_id, he.code, msg)
                    last_err = RuntimeError(f"{model_id} HTTP {he.code}: {msg}")
                except Exception as exc:
                    safe_msg = _sanitize_error(str(exc))
                    self._mark_cooldown(key_obj["id"], model_id, None, safe_msg)
                    last_err = RuntimeError(safe_msg)
        raise RuntimeError(f"All standalone flagship attempts failed: {_sanitize_error(str(last_err))}")

    def _min_cooldown_remaining(self, model_id: str) -> float:
        now = time.time()
        with self._lock:
            vals = [max(0.0, self._cooldowns.get((k["id"], model_id), 0.0) - now) for k in self.keys]
        return min(vals) if vals else 0.0

    def synthesize_tts(self, spoken_text: str, voice_name: str = "Charon", timeout_sec: int = 36) -> tuple[bytes, str, str]:
        """Synthesize natural neural audio strictly via gemini-3.8-flash-tts across key pool."""
        model_id = "gemini-3.8-flash-tts"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": spoken_text.strip()}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}},
            },
        }
        eff_tmo = min(int(timeout_sec), 36)
        last_err: Exception | None = None
        if self._mode == "gateway":
            for attempt in range(4):
                try:
                    raw = self._post_native_gemini(
                        f"{self.base_url}/v1beta/models/{model_id}:generateContent",
                        self._gateway_headers(),
                        payload,
                        eff_tmo,
                    )
                    audio_bytes, mime = _extract_audio_bytes(raw)
                    if audio_bytes:
                        return audio_bytes, mime, model_id
                except Exception as exc:
                    last_err = exc
                    time.sleep(1.0 * (attempt + 1))
            raise RuntimeError(f"TTS gateway synthesis failed ({model_id}): {_sanitize_error(str(last_err))}")

        for wave in range(5):
            tried: set[str] = set()
            max_tries = min(len(self.keys), 25)
            for _ in range(max_tries):
                key_obj = self._pick_standalone_key(model_id, tried)
                if not key_obj:
                    break
                tried.add(key_obj["id"])
                url = f"{AISTUDIO_BASE}/models/{urllib.parse.quote(model_id)}:generateContent"
                try:
                    raw = self._post_native_gemini(url, self._standalone_headers(key_obj["apiKey"]), payload, eff_tmo)
                    audio_bytes, mime = _extract_audio_bytes(raw)
                    if audio_bytes:
                        return audio_bytes, mime, model_id
                except urllib.error.HTTPError as he:
                    msg = _sanitize_error(he.read().decode("utf-8", "ignore")[:240])
                    self._mark_cooldown(key_obj["id"], model_id, he.code, msg)
                    last_err = RuntimeError(f"{model_id} HTTP {he.code}: {msg}")
                except Exception as exc:
                    safe_msg = _sanitize_error(str(exc))
                    self._mark_cooldown(key_obj["id"], model_id, None, safe_msg)
                    last_err = RuntimeError(safe_msg)
            if wave < 4:
                wait_s = self._min_cooldown_remaining(model_id)
                time.sleep(min(max(wait_s + 0.5, 2.0), 32.0))
        raise RuntimeError(f"All gemini-3.8-flash-tts attempts failed: {_sanitize_error(str(last_err))}")


def _extract_parts_text(raw: dict[str, Any]) -> str:
    cands = raw.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Empty Gemini candidates: {str(raw)[:200]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    txt = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    return txt or "".join(p.get("text", "") for p in parts).strip()


def _extract_audio_bytes(raw: dict[str, Any]) -> tuple[bytes, str]:
    import base64

    cands = raw.get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    for p in parts:
        inline = p.get("inlineData") or {}
        if inline.get("data"):
            return base64.b64decode(inline["data"]), str(inline.get("mimeType") or "audio/L16")
    return b"", ""
