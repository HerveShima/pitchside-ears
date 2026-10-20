import os
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

CACHE_FILE = Path(__file__).parent / "cache" / "narration_cache.json"
CACHE_ONLY = os.getenv("CACHE_ONLY", "false").lower() == "true"

_client = None
_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        if CACHE_FILE.exists():
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        else:
            _cache = {}
    return _cache


def _save_cache():
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_client():
    global _client
    if _client is None:
        project = AIProjectClient(
            endpoint=os.getenv("AZURE_AI_ENDPOINT"),
            credential=DefaultAzureCredential(),
        )
        _client = project.get_openai_client()
    return _client


def generate_text(prompt, system=None, max_tokens=200, fallback="[narration unavailable]"):
    """Single entry point for all model calls. Cached, with a safe fallback."""
    key = hashlib.sha256(f"{system}|{prompt}|{max_tokens}".encode("utf-8")).hexdigest()
    cache = _load_cache()

    if key in cache:
        return cache[key]

    if CACHE_ONLY:
        return fallback

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = _get_client().chat.completions.create(
            model=os.getenv("AZURE_AI_DEPLOYMENT"),
            messages=messages,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content
    except Exception as e:
        print(f"[llm] model call failed: {e}")
        return fallback

    cache[key] = text
    _save_cache()
    return text