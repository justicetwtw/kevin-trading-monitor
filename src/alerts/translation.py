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
from decimal import Decimal, InvalidOperation
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
# stock tickers, dates and numeric values (currency amounts and percentages).
# We extract *typed canonical tokens* from both sides and compare them as
# *symmetric* multisets with token boundaries — never substring membership — so
# a value change (25%->125%), a dropped/added value ($1,000->$11,000, an invented
# amount), a swapped date component, or a dropped duplicate is caught in BOTH
# directions. Numbers are matched by canonical value so faithful unit/format
# reformatting ($100->100 美元, 25%->百分之 25, 2026-07-21->2026 年 7 月 21 日) is not
# flagged, while polarity (a negative that flips positive), currency substitution
# ($->foreign) and percentage->currency type changes ARE rejected. Scale-word
# magnitudes (million->億) and ordinals are excluded because a faithful rendering
# legitimately rescales their digits. Only high-signal tokens are protected, so
# prose (including Trump's all-caps words) is never flagged.

# Restrict to RFC 3986 URL characters so a URL immediately followed by CJK text
# or full-width punctuation (common in Chinese, no space) is not over-captured.
_URL_TOKEN_RE = re.compile(
    r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE
)
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})\b")
_ISO_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_CJK_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# A standalone number not glued to a letter/digit (so "MP3"/"COVID19" are skipped).
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")
# A minus sign that is a real polarity marker, not a range hyphen "3-5".
_NEGATIVE_RE = re.compile(r"(?<![\d.])[\-−]\s?(\d+(?:\.\d+)?)")
_URL_TRAILING = ".,;:!?)]}\"'>"
# Ordinals are skipped: "1st" -> "第一" legitimately drops the digit.
_ORDINAL_RE = re.compile(r"(?:st|nd|rd|th)\b", re.IGNORECASE)
# Scaled quantities are CANONICALIZED to a base value, not skipped, so a wrong
# rescale ($100 million -> 9 億) is caught while a faithful one ($100 million ->
# 1 億) matches.
_SCALE_EN_RE = re.compile(
    r"\s*(hundred|thousand|million|billion|trillion)\b", re.IGNORECASE
)
_SCALE_EN_MULT = {
    "hundred": 100, "thousand": 1000, "million": 10 ** 6,
    "billion": 10 ** 9, "trillion": 10 ** 12,
}
_SCALE_CJK_MULT = {
    "百": 100, "千": 1000, "萬": 10 ** 4, "万": 10 ** 4,
    "億": 10 ** 8, "亿": 10 ** 8, "兆": 10 ** 12,
}
# Direction / negation markers, English source and accepted zh-TW equivalents.
_SRC_UP_RE = re.compile(
    r"(?<![\d.])\+\s?\d|\b(?:up|rise|rises|rose|risen|gain|gains|gained|"
    r"increase|increases|increased|grow|grows|grew|surge|surged|jump|jumped|"
    r"higher|climb|climbed)\b",
    re.IGNORECASE,
)
_SRC_DOWN_RE = re.compile(
    r"(?<![\d.])[\-−]\s?\d|\b(?:down|fall|falls|fell|fallen|drop|drops|dropped|"
    r"decrease|decreases|decreased|decline|declines|declined|plunge|plunged|"
    r"lower|cut|cuts|sink|sank|tumble|tumbled)\b",
    re.IGNORECASE,
)
_SRC_NEG_RE = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|won't|wont|don't|dont|doesn't|"
    r"didn't|isn't|aren't|neither|nor|none|deny|denies|denied|refuse|refuses)\b",
    re.IGNORECASE,
)
_ZH_UP_RE = re.compile(
    r"\+\s?\d|上漲|上升|增加|提高|成長|走高|攀升|漲|升|擴大|走揚|上揚"
)
_ZH_DOWN_RE = re.compile(
    r"(?<![\d.])[\-−]\s?\d|下跌|下降|減少|降低|下滑|衰退|縮減|走低|下修|調降|跌|負"
)
_ZH_NEG_RE = re.compile(r"不|未|無|沒有|沒|並非|非|否認|拒絕|別|勿|毫無")
# Currency / percentage source and accepted-marker forms.
_USD_SRC_RE = re.compile(r"\$|\bUSD\b|\bdollars?\b", re.IGNORECASE)
_USD_MARK_RE = re.compile(r"美元|美金|\$|\bUSD\b|\bdollars?\b", re.IGNORECASE)
_FOREIGN_CURRENCY_RE = re.compile(
    r"日圓|日元|歐元|英鎊|人民幣|韓元|韓圜|港幣|港元|盧布|盧比|加元|澳元|瑞郎|"
    r"新台幣|新臺幣|台幣"
)
_PCT_SRC_RE = re.compile(r"%|％|\bpercent\b|\bpercentage\b|\bpct\b", re.IGNORECASE)
_PERCENT_MARK_RE = re.compile(r"%|％|百分|趴|個百分點")
_UPPER_WORD_RE = re.compile(r"\b[A-Z]{2,6}\b")
# All-caps English that is also a ticker symbol but is overwhelmingly prose in a
# Trump post; never treat these as bare tickers (cashtags like $ALL still count).
_TICKER_STOPWORDS = frozenset(
    {
        "ALL", "ARE", "AND", "THE", "FOR", "NOT", "YOU", "NOW", "NEW", "BIG",
        "WIN", "OUT", "OUR", "WHO", "WHY", "HOW", "CAN", "GET", "GOT", "HAS",
        "USA", "CEO", "GDP", "FBI", "CIA", "DOJ", "FED", "USD", "NATO", "GO",
    }
)

# Full-width -> ASCII for digits, '%', '$' and ',' so a translation that emits
# full-width forms still matches. Thousands separators are stripped between
# digits so "1,000" and "1000" compare equal.
_FULLWIDTH_MAP = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH_MAP.update({ord("％"): ord("%"), ord("＄"): ord("$"), ord("，"): ord(",")})


def _normalize_for_match(text: str) -> str:
    normalized = (text or "").translate(_FULLWIDTH_MAP)
    return re.sub(r"(?<=\d),(?=\d)", "", normalized)


def _canonical_number(raw: str, multiplier: int = 1) -> str:
    """Canonical base value so 007==7, 1000==1,000 and 100 million==1 億."""
    try:
        value = Decimal(raw) * multiplier
    except (InvalidOperation, ValueError):
        return raw
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _known_tickers() -> frozenset:
    cached = getattr(_known_tickers, "_cache", None)
    if cached is None:
        try:
            from src.config import universe

            cached = frozenset(
                sym
                for sym in universe.ALL_TICKERS_SCAN
                if len(sym) >= 3 and sym.isalpha() and sym not in _TICKER_STOPWORDS
            )
        except Exception:
            cached = frozenset()
        _known_tickers._cache = cached  # type: ignore[attr-defined]
    return cached


def _extract_value_tokens(text: str) -> tuple[Counter, str]:
    """Typed multiset of URLs, dates (y, m, d) and exact numeric values.

    Returns the token multiset and the URL/date-stripped working text (used for
    polarity checks so an ISO date's own hyphen is never read as a minus sign).
    Extraction order removes each matched span before the next pattern so a
    URL's or date's own digits are never re-counted as bare numbers. Scale-word
    magnitudes and ordinals are skipped.
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

    for match in _NUMBER_RE.finditer(work):
        tail = work[match.end():match.end() + 16]
        stripped_tail = tail.lstrip()
        if _ORDINAL_RE.match(stripped_tail):
            continue  # "1st" -> "第一" legitimately drops the digit
        multiplier = 1
        scale_en = _SCALE_EN_RE.match(tail)
        cjk_next = stripped_tail[:1]
        if scale_en:
            multiplier = _SCALE_EN_MULT[scale_en.group(1).lower()]
        elif cjk_next in _SCALE_CJK_MULT:
            multiplier = _SCALE_CJK_MULT[cjk_next]
        tokens[("number", _canonical_number(match.group(0), multiplier))] += 1
    return tokens, work


def _ticker_counts(text: str) -> Counter:
    """Cashtag plus known-symbol bare tickers, e.g. ``$NVDA`` / ``NVDA``.

    All-caps prose is not treated as a ticker: a bare upper word counts only
    when it is a known symbol in the observation universe.
    """
    counts: Counter = Counter()
    work = _CASHTAG_RE.sub(
        lambda m: counts.update([m.group(1).upper()]) or " ", text or ""
    )
    known = _known_tickers()
    for word in _UPPER_WORD_RE.findall(work):
        if word in known:
            counts[word] += 1
    return counts


def _looks_untranslated(source: str, output: str) -> bool:
    """True when the output is an English echo / wrapper, not a translation.

    ``translate_text`` only invokes the provider for substantive non-Chinese
    input, so a clean zh-TW translation is dominated by Han script. Rejects
    output with no Han, output equal to or containing the normalized source
    (a Chinese-prefixed/suffixed or JSON/markdown wrapper), and output whose
    non-ticker English words still overlap most of the source (a paraphrased
    English echo carrying one or two Han characters).
    """
    stripped = (output or "").strip()
    if not stripped:
        return True
    if not _HAN_RE.search(stripped):
        return True
    src_norm = " ".join((source or "").split()).lower()
    out_norm = " ".join(stripped.split()).lower()
    if src_norm and (out_norm == src_norm or src_norm in out_norm):
        return True

    tickers = set(_ticker_counts(source))

    def _content_words(text: str) -> list[str]:
        return [
            word.lower()
            for word in re.findall(r"[A-Za-z]{3,}", text or "")
            if word.upper() not in tickers
        ]

    source_words = _content_words(source)
    if len(source_words) >= 3:
        output_words = set(_content_words(stripped))
        overlap = sum(1 for word in source_words if word in output_words)
        if overlap >= max(3, int(0.6 * len(source_words))):
            return True
    return False


def _has_up(text: str, zh: bool) -> bool:
    pattern = _ZH_UP_RE if zh else _SRC_UP_RE
    return bool(pattern.search(text or ""))


def _has_down(text: str, zh: bool) -> bool:
    pattern = _ZH_DOWN_RE if zh else _SRC_DOWN_RE
    return bool(pattern.search(text or ""))


def fidelity_error(source: str, translation: str) -> str | None:
    """Return an error code when protected source values are corrupted.

    Symmetric multiset comparison rejects both dropped/changed and invented
    URLs, dates and numeric values (scaled quantities canonicalized to a base
    value) and tickers; direction/negation reversal, currency substitution and
    percentage type loss are rejected too. Returns ``None`` when fidelity holds
    or neither side carries a protected value.
    """
    source_values, source_work = _extract_value_tokens(source)
    translation_values, translation_work = _extract_value_tokens(translation)
    source_tickers = _ticker_counts(source)
    translation_tickers = _ticker_counts(translation)
    directional = (
        _has_up(source_work, False)
        or _has_down(source_work, False)
        or _SRC_NEG_RE.search(source or "")
    )
    if not any(
        (
            source_values,
            translation_values,
            source_tickers,
            translation_tickers,
            directional,
        )
    ):
        return None

    # Symmetric: preservation AND no invented values, in both directions.
    if source_values != translation_values:
        return "fidelity_mismatch"
    if source_tickers != translation_tickers:
        return "fidelity_mismatch"

    # Direction: a clearly-up (or down) source must not be rendered as the
    # opposite; catches +3% -> 下跌 3%, rose -> 下跌, fell -> 上漲.
    src_up = _has_up(source_work, False)
    src_down = _has_down(source_work, False)
    tr_up = _has_up(translation_work, True)
    tr_down = _has_down(translation_work, True)
    if src_up and not src_down and tr_down and not tr_up:
        return "fidelity_mismatch"
    if src_down and not src_up and tr_up and not tr_down:
        return "fidelity_mismatch"

    # Negation: a negated source must keep an explicit zh negation.
    if _SRC_NEG_RE.search(source or "") and not _ZH_NEG_RE.search(translation or ""):
        return "fidelity_mismatch"

    # Currency: a USD source must be rendered with a USD marker, not a foreign
    # currency (catches $100 -> 100 日圓, and a silent unit drop).
    if _USD_SRC_RE.search(source or "") and not _FOREIGN_CURRENCY_RE.search(source or ""):
        if _FOREIGN_CURRENCY_RE.search(translation or "") or not _USD_MARK_RE.search(
            translation or ""
        ):
            return "fidelity_mismatch"

    # Percentage must not silently become a non-percentage (e.g. currency).
    if _PCT_SRC_RE.search(source or "") and not _PERCENT_MARK_RE.search(
        _normalize_for_match(translation)
    ):
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
        # Reject an English echo / wrapper rendered as if it were Chinese.
        if _looks_untranslated(text, cleaned):
            return TranslationResult(
                None, "failed", self.name, "invalid_response"
            )
        # Never accept a translation that dropped, altered or invented a
        # protected token (URL, ticker, amount, percentage, date, polarity,
        # currency); fall back to English instead.
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
