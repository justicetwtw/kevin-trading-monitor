"""Provider-neutral translation service for Trump Truth Social delivery.

Design red lines (see ``docs/trump_truth_zh_tw_translation_v1.md``):

- The Telegram runner never binds to a provider SDK; it depends only on the
  ``Translator`` contract and ``TranslationResult`` here.
- Reuse only the already-approved Gemini product path
  (``GEMINI_API_KEY`` / ``GEMINI_MODEL``); no new provider, secret or SDK.
- Already-Chinese, URL-only, media-only and empty text are a deterministic
  no-op — no model call.
- One translation per post per process: retries, chunks and multiple
  recipients reuse a process cache instead of re-translating.
- Never log or persist post text, translation text, the prompt, the raw
  provider response or credentials. Failures surface only a generic code.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Protocol

from src.config import trump_translation_config as cfg
from src.config.settings import GEMINI_API_KEY, GEMINI_MODEL

TranslationStatus = Literal["ok", "noop", "failed"]


@dataclass(frozen=True)
class TranslationResult:
    """Result of translating one post's text.

    ``text`` holds the Traditional Chinese translation for ``ok``, the original
    text for a non-empty ``noop`` (already Chinese / URL-only), and ``None`` for
    an empty ``noop`` or a ``failed`` attempt. ``error_code`` is a generic,
    log-safe code — never a provider message, URL or credential.
    """

    text: str | None
    status: TranslationStatus
    source: str
    error_code: str | None = None


class Translator(Protocol):
    """Minimal provider-neutral contract the runner depends on."""

    name: str

    def translate(self, text: str) -> TranslationResult:
        ...


# --- Deterministic no-op detection -----------------------------------------

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# CJK Unified Ideographs (basic block); enough to detect already-Chinese text.
_HAN_RE = re.compile("[一-鿿]")
# A "substantial" English word: 4+ consecutive ASCII letters. Short tokens like
# Fed / FOMC embedded in Chinese text should not force a translation call.
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _is_url_only(text: str) -> bool:
    """True when the text is nothing but URLs and whitespace."""
    remainder = _URL_RE.sub(" ", text)
    return remainder.strip() == ""


def _is_already_chinese(text: str) -> bool:
    """True when the text is Chinese with no substantial English to translate."""
    return bool(_HAN_RE.search(text)) and not _LATIN_WORD_RE.search(text)


def is_noop_text(text: str) -> bool:
    """Deterministic no-op guard; no model call for these inputs."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    if _is_url_only(stripped):
        return True
    if _is_already_chinese(stripped):
        return True
    return False


def _noop_result(text: str) -> TranslationResult:
    stripped = (text or "").strip()
    # Empty / media-only: no text to carry forward.
    if not stripped:
        return TranslationResult(None, "noop", "deterministic_noop", None)
    # Already-Chinese or URL-only: keep the original, rendered once.
    return TranslationResult(text, "noop", "deterministic_noop", None)


# --- Fidelity validation of protected tokens --------------------------------
# A faithful translation must preserve high-signal, verbatim-kept values: URLs,
# stock tickers, dates and numeric values (which cover currency amounts and
# percentages). We extract *typed canonical tokens* from both the source and the
# translation and compare them as multisets with token boundaries — never by
# substring membership — so a value change like 25% -> 125% or $1,000 -> $11,000,
# a swapped date component, or a dropped duplicate is caught, while faithful
# reformatting ($100 -> 100 美元, 25% -> 百分之 25, 2026-07-21 -> 2026 年 7 月 21 日)
# is not falsely flagged. Numbers are matched by value, so unit/symbol wording is
# free to change but the value itself must survive. Only high-signal tokens are
# protected, so prose (including Trump's all-caps words) is never flagged.

# Restrict to RFC 3986 URL characters so a URL immediately followed by CJK text
# or full-width punctuation (common in Chinese, no space) is not over-captured.
_URL_TOKEN_RE = re.compile(
    r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE
)
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})\b")
_ISO_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_CJK_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_URL_TRAILING = ".,;:!?)]}\"'>"

# Full-width -> ASCII for digits, '%', '$' and ',' so a translation that emits
# full-width forms still matches. Thousands separators are stripped between
# digits so "1,000" and "1000" compare equal.
_FULLWIDTH_MAP = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH_MAP.update({ord("％"): ord("%"), ord("＄"): ord("$"), ord("，"): ord(",")})


def _normalize_for_match(text: str) -> str:
    normalized = (text or "").translate(_FULLWIDTH_MAP)
    return re.sub(r"(?<=\d),(?=\d)", "", normalized)


def _canonical_number(raw: str) -> str:
    """Canonicalize a numeric literal so 007 == 7 and 1000 == 1,000."""
    if "." in raw:
        return raw
    return str(int(raw))


def _extract_value_tokens(text: str) -> Counter:
    """Typed multiset of URLs, dates (y, m, d) and numeric values.

    Extraction order removes each matched span before the next pattern so a
    URL's or date's own digits are never re-counted as bare numbers.
    """
    tokens: Counter = Counter()
    work = text or ""

    def _url_repl(match: re.Match) -> str:
        tokens[("url", match.group(0).rstrip(_URL_TRAILING))] += 1
        return " "

    work = _URL_TOKEN_RE.sub(_url_repl, work)
    work = _normalize_for_match(work)

    def _date_repl(match: re.Match) -> str:
        y, m, d = (int(match.group(i)) for i in (1, 2, 3))
        tokens[("date", (y, m, d))] += 1
        return " "

    work = _ISO_DATE_RE.sub(_date_repl, work)
    work = _CJK_DATE_RE.sub(_date_repl, work)

    for number in _NUMBER_RE.findall(work):
        tokens[("number", _canonical_number(number))] += 1
    return tokens


def _ticker_counts(text: str) -> Counter:
    """Cashtag tickers in the source, e.g. ``$NVDA`` -> ``NVDA``."""
    return Counter(sym.upper() for sym in _CASHTAG_RE.findall(text or ""))


def fidelity_error(source: str, translation: str) -> str | None:
    """Return an error code when a protected source value is missing/changed.

    Compares typed multisets: every URL, date and numeric value in the source
    must appear at least as many times in the translation, and every source
    ticker must appear as a whole word at least as often. Returns ``None`` when
    fidelity holds or the source carries no protected value.
    """
    source_values = _extract_value_tokens(source)
    source_tickers = _ticker_counts(source)
    if not source_values and not source_tickers:
        return None

    translation_values = _extract_value_tokens(translation)
    for token, count in source_values.items():
        if translation_values[token] < count:
            return "fidelity_mismatch"

    for ticker, count in source_tickers.items():
        found = len(re.findall(rf"\b{re.escape(ticker)}\b", translation or ""))
        if found < count:
            return "fidelity_mismatch"
    return None


# --- Process cache ----------------------------------------------------------
# Keyed by exact input text so identical posts, retries, chunk rebuilds and
# multiple recipients within one workflow process translate at most once.
_CACHE: dict[str, TranslationResult] = {}


def reset_translation_cache() -> None:
    """Clear the per-process translation cache (call once per workflow run)."""
    _CACHE.clear()


def translate_text(text: str, translator: Translator | None) -> TranslationResult:
    """Translate one post's text with no-op short-circuit and process cache.

    ``translator is None`` means translation is disabled/unconfigured; callers
    render the existing English-only notification and mark health unavailable.
    """
    source = text or ""
    if is_noop_text(source):
        return _noop_result(source)
    if translator is None:
        # Disabled path: do not fabricate a failure; the runner renders the
        # existing English notification and reports health unavailable.
        return TranslationResult(None, "noop", "translation_disabled", None)
    cached = _CACHE.get(source)
    if cached is not None:
        return cached
    result = translator.translate(source)
    _CACHE[source] = result
    return result


# --- Gemini adapter (reuse the approved product path) -----------------------


class _TranslationIncomplete(Exception):
    """The provider stopped before a complete, clean translation.

    Raised when the response finished for a non-STOP reason (truncation at the
    output-token limit, safety block, recitation, etc). Such output is a partial
    result and must fall back to English rather than masquerade as success.
    """


def _generic_error_code(exc: BaseException) -> str:
    """Map any provider exception to a small, log-safe, generic code.

    Only the exception *class name* is inspected; the message (which may embed
    a Bot/API URL, quota detail or request echo) is never used.
    """
    name = type(exc).__name__.lower()
    if "timeout" in name or "deadline" in name:
        return "timeout"
    if "quota" in name or "resourceexhausted" in name or "ratelimit" in name:
        return "quota"
    if "json" in name or "decode" in name or "value" in name or "parse" in name:
        return "invalid_response"
    if "connect" in name or "unavailable" in name or "network" in name:
        return "provider_unavailable"
    return "provider_error"


def _raise_if_incomplete(finish_reason_name: str | None) -> None:
    """Reject any non-STOP terminal finish reason as an incomplete translation.

    A truncated (MAX_TOKENS) or blocked (SAFETY / RECITATION) response yields
    only partial Chinese; treating it as ``ok`` would deliver a silently
    cut-off translation and mislabel health as healthy.
    """
    name = (finish_reason_name or "").upper()
    # Empty / unknown is treated as complete: the SDK shape may vary and we do
    # not want a false failure when a clean response simply lacks the field.
    if name and name not in {"STOP", "FINISH_REASON_STOP", "FINISH_REASON_UNSPECIFIED"}:
        raise _TranslationIncomplete(name)


def _gemini_generate(
    *,
    api_key: str,
    model: str,
    system_instruction: str,
    prompt: str,
) -> str | None:
    """Call the Gemini product path. Lazy import keeps the module importable
    even where the SDK is absent (tests / non-Gemini environments)."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        # Bounded timeout so a hung upstream raises instead of blocking every
        # post's delivery until the Actions job is SIGKILLed (§6.4).
        http_options=types.HttpOptions(timeout=cfg.TRANSLATION_TIMEOUT_MS),
    )
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=cfg.TRANSLATION_MAX_OUTPUT_TOKENS,
            temperature=cfg.TRANSLATION_TEMPERATURE,
        ),
    )
    # A translation cut off at the token limit (or blocked) is not a success.
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        finish_reason = getattr(candidates[0], "finish_reason", None)
        _raise_if_incomplete(getattr(finish_reason, "name", None) or (
            str(finish_reason) if finish_reason is not None else None
        ))
    return response.text


class GeminiTranslator:
    """Thin Gemini adapter behind the provider-neutral ``Translator`` contract.

    The fixed injection-resistant system instruction is always sent separately
    from the post text, which is passed only as a collision-safe JSON data
    field. ``generate_fn`` is injectable for deterministic testing without the
    live SDK.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        generate_fn=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._generate = generate_fn or _gemini_generate

    def translate(self, text: str) -> TranslationResult:
        try:
            output = self._generate(
                api_key=self._api_key,
                model=self._model,
                system_instruction=cfg.TRANSLATION_SYSTEM_INSTRUCTION,
                prompt=cfg.build_translation_prompt(text),
            )
        except _TranslationIncomplete:
            # Truncated / blocked output → fall back to English, mark degraded.
            return TranslationResult(
                None, "failed", self.name, "incomplete_response"
            )
        except Exception as exc:  # noqa: BLE001 - map to a generic code
            return TranslationResult(
                None, "failed", self.name, _generic_error_code(exc)
            )
        cleaned = (output or "").strip()
        if not cleaned:
            return TranslationResult(None, "failed", self.name, "empty_response")
        # Never accept a translation that dropped or altered a protected token
        # (URL, ticker, amount, percentage, date); fall back to English instead.
        mismatch = fidelity_error(text, cleaned)
        if mismatch:
            return TranslationResult(None, "failed", self.name, mismatch)
        return TranslationResult(cleaned, "ok", self.name, None)


def get_default_translator() -> Translator | None:
    """Resolve the configured translator, or ``None`` when disabled.

    Translation is on by default and requires the approved ``GEMINI_API_KEY``.
    Setting ``TRUMP_TRANSLATION_ENABLED=0`` provides an explicit off switch that
    preserves the existing English-only Trump notification.
    """
    import os

    if os.getenv("TRUMP_TRANSLATION_ENABLED", "1").strip().lower() in {
        "0",
        "false",
        "off",
        "no",
    }:
        return None
    if not GEMINI_API_KEY:
        return None
    return GeminiTranslator(GEMINI_API_KEY, GEMINI_MODEL)
