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
# Social handles are verbatim-kept tokens (like URLs/cashtags), so they must be
# stripped before deciding whether translatable English remains.
_HANDLE_RE = re.compile(r"@\w+")
# ASCII letters that still count as *translatable* text after protected tokens
# (URLs, @handles, $cashtags) are removed.
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


def _is_url_only(text: str) -> bool:
    """True when the text is nothing but URLs and whitespace."""
    remainder = _URL_RE.sub(" ", text)
    return remainder.strip() == ""


def _is_already_chinese(text: str) -> bool:
    """True when the text is Chinese with no substantial English to translate.

    URLs, @handles and $cashtags are protected tokens a faithful zh-TW rendering
    keeps verbatim, so they are stripped before measuring residual English.
    Earlier logic flagged *any* 4+ letter run as "needs translation", which sent
    an already-Chinese post that merely contained a link, a handle or a proper
    noun (``川普提到 Nvidia`` / ``發文連結 https://…``) to the provider — wasting
    the run budget and risking a fidelity-fail fallback to English on text that
    was already Chinese. After stripping protected tokens, the post counts as
    already-Chinese when it has Han script and Han characters are at least as
    numerous as the residual ASCII letters, so a short embedded acronym or name
    (``Fed`` / ``Nvidia``) inside Chinese prose no longer forces a call.
    """
    if not _HAN_RE.search(text):
        return False
    cleaned = _URL_RE.sub(" ", text)
    cleaned = _HANDLE_RE.sub(" ", cleaned)
    cleaned = _CASHTAG_RE.sub(" ", cleaned)
    han = len(_HAN_RE.findall(cleaned))
    latin = len(_ASCII_LETTER_RE.findall(cleaned))
    return han >= latin


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
# Direction words (English + zh-TW) used to tag a nearby quantity's polarity and
# to build standalone directional claims. Bare "up"/"down" appear here (used only
# next to a number) but NOT in the claim regexes below (too ambiguous in prose).
_UPWORD_RE = re.compile(
    r"\b(?:up|higher|rise|rises|rose|risen|gain|gains|gained|increase|increases|"
    r"increased|grow|grows|grew|surge|surged|jump|jumped|climb|climbed|soar|"
    r"soared|rally|rallied)\b|上漲|上升|上調|調升|提升|增加|提高|成長|走高|攀升|"
    r"走揚|上揚|漲|升",
    re.IGNORECASE,
)
_DOWNWORD_RE = re.compile(
    r"\b(?:down|lower|fall|falls|fell|fallen|drop|drops|dropped|decrease|"
    r"decreases|decreased|decline|declines|declined|plunge|plunged|sink|sank|"
    r"tumble|tumbled|slump|slumped|cut|cuts|crash|crashed)\b|下跌|下降|下調|調降|"
    r"減少|降低|下滑|衰退|縮減|走低|下修|跌",
    re.IGNORECASE,
)
# Directional motion VERBS only, for standalone claim extraction. Noun-ambiguous
# words (increase/growth/成長/增加/提高/減少) are deliberately excluded to avoid
# asymmetric double-counting; they are still tagged onto an adjacent quantity.
_CLAIM_UP_RE = re.compile(
    r"\b(?:rise|rises|rose|risen|surge|surges|surged|jump|jumps|jumped|climb|"
    r"climbs|climbed|soar|soars|soared|rally|rallies|rallied)\b|"
    r"上漲|上升|攀升|走高|上揚",
    re.IGNORECASE,
)
_CLAIM_DOWN_RE = re.compile(
    r"\b(?:fall|falls|fell|fallen|drop|drops|dropped|decline|declines|declined|"
    r"plunge|plunges|plunged|sink|sinks|sank|tumble|tumbles|tumbled|slump|"
    r"slumps|slumped|crash|crashes|crashed)\b|下跌|下降|下滑|走低|重挫",
    re.IGNORECASE,
)
_NEG_RE = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|won't|wont|don't|dont|doesn't|"
    r"didn't|isn't|aren't|neither|nor|none|deny|denies|denied|refuse|refuses|"
    r"refused)\b|不|未|無|沒有|沒|並非|否認|拒絕|勿|毫無",
    re.IGNORECASE,
)
# Clause delimiters (punctuation + coordinating conjunctions, English + zh-TW).
# Direction/negation are scoped to a clause so a marker never binds across it.
_CLAUSE_DELIM_RE = re.compile(
    r"[，。；;,.:!?、\n]|\b(?:while|and|but|or|whereas|although|though|yet)\b|"
    r"而|但|並且|以及|然而|同時",
    re.IGNORECASE,
)
# Currency / percentage markers used to type a quantity by its adjacent context.
_USD_AFTER_RE = re.compile(r"(?:美元|美金|dollars?|usd)\b", re.IGNORECASE)
_USD_BEFORE_RE = re.compile(r"(?:USD|dollars?)\s*$", re.IGNORECASE)
_PCT_AFTER_RE = re.compile(r"(?:percent|percentage|pct)\b", re.IGNORECASE)
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


def _quantity_type(before: str, after: str) -> str:
    """Classify a number by its adjacent context: percent, USD currency, or bare.

    The unit travels with the value, so a value cannot silently change units
    (25% -> 25 美元) or a currency swap another value's slot.
    """
    tail = after.lstrip()
    head = before.rstrip()
    if tail[:1] in ("%",) or _PCT_AFTER_RE.match(tail) or head.endswith("百分之") or (
        "百分之" in before[-5:]
    ):
        return "percent"
    if (
        head[-1:] == "$"
        or tail[:2] in ("美元", "美金")
        or _USD_AFTER_RE.match(tail)
        or _USD_BEFORE_RE.search(before)
    ):
        return "currency_usd"
    return "number"


def _clause_start(text: str, pos: int) -> int:
    """Index just after the last clause delimiter before ``pos`` (or 0)."""
    last = 0
    for match in _CLAUSE_DELIM_RE.finditer(text[:pos]):
        last = match.end()
    return last


def _clause_end(text: str, pos: int) -> int:
    """Index of the next clause delimiter at/after ``pos`` (or end of text)."""
    match = _CLAUSE_DELIM_RE.search(text, pos)
    return match.start() if match else len(text)


def _quantity_direction(work: str, start: int, floor: int = 0) -> str:
    """Polarity of the value at ``start``: an explicit +/- sign, else an up/down
    word between it and the previous number *within the same clause*, else
    neutral. Bounding by both the clause start and the previous number stops a
    marker that belongs to an earlier value (``rise 25% ... $1,000``) from
    binding here."""
    pre = work[:start]
    sign = re.search(r"(?<![\d.])([+\-−])\s*$", pre)
    if sign:
        return "up" if sign.group(1) == "+" else "down"
    window = work[max(_clause_start(work, start), floor):start]
    down = bool(_DOWNWORD_RE.search(window))
    up = bool(_UPWORD_RE.search(window))
    if down and not up:
        return "down"
    if up and not down:
        return "up"
    return "neutral"


def _extract_value_tokens(text: str) -> tuple[Counter, str]:
    """Typed multiset of URLs, dates and quantities.

    Each quantity is ``(kind, canonical_value, direction)`` where ``kind`` is
    ``percent`` / ``currency_usd`` / ``number`` (unit bound to the value),
    the value is canonicalized (scaled quantities like ``100 million`` / ``1 億``
    collapse to a base value), and ``direction`` is up / down / neutral.
    Cashtags are stripped before quantity typing so ``$NVDA`` is never a USD
    amount. Returns the tokens and the URL/date-stripped working text.
    """
    tokens: Counter = Counter()
    work = text or ""

    def _url_repl(match: re.Match) -> str:
        tokens[("url", match.group(0).rstrip(_URL_TRAILING))] += 1
        return " "

    work = _URL_TOKEN_RE.sub(_url_repl, work)
    work = _normalize_for_match(work)
    work = _CASHTAG_RE.sub(" ", work)  # $NVDA is a ticker, not a USD amount

    def _date_repl(match: re.Match) -> str:
        y, m, d = (int(match.group(i)) for i in (1, 2, 3))
        tokens[("date", (y, m, d))] += 1
        return " "

    work = _ISO_DATE_RE.sub(_date_repl, work)
    work = _CJK_DATE_RE.sub(_date_repl, work)

    prev_end = 0
    for match in _NUMBER_RE.finditer(work):
        after = work[match.end():match.end() + 16]
        stripped_tail = after.lstrip()
        if _ORDINAL_RE.match(stripped_tail):
            prev_end = match.end()
            continue  # "1st" -> "第一" legitimately drops the digit
        multiplier = 1
        after_unit = after
        scale_en = _SCALE_EN_RE.match(after)
        cjk_next = stripped_tail[:1]
        if scale_en:
            multiplier = _SCALE_EN_MULT[scale_en.group(1).lower()]
            after_unit = after[scale_en.end():]
        elif cjk_next in _SCALE_CJK_MULT:
            multiplier = _SCALE_CJK_MULT[cjk_next]
            after_unit = stripped_tail[1:]
        value = _canonical_number(match.group(0), multiplier)
        before = work[max(0, match.start() - 16):match.start()]
        kind = _quantity_type(before, after_unit)
        direction = _quantity_direction(work, match.start(), prev_end)
        tokens[(kind, value, direction)] += 1
        prev_end = match.end()
    return tokens, work


def _direction_claims(text: str) -> Counter:
    """Multiset of *negated* standalone directional claims ``(direction,)``.

    Only negated directional verbs in a number-free clause are counted: numbered
    directions are already bound to their quantity token, and a non-negated bare
    direction ("is up today" vs "上漲") is intentionally not compared to avoid an
    English/zh vocabulary asymmetry. This still catches a negation reversal or
    drop such as ``not rise ... fall`` -> ``上升 ... 不會下降``.
    """
    claims: Counter = Counter()
    body = text or ""

    def _collect(pattern: re.Pattern, direction: str) -> None:
        for match in pattern.finditer(body):
            clause = body[_clause_start(body, match.start()):_clause_end(body, match.end())]
            if any(ch.isdigit() for ch in clause):
                continue  # numbered direction -> handled by the quantity token
            window = body[_clause_start(body, match.start()):match.start()]
            if _NEG_RE.search(window):
                claims[(direction,)] += 1

    _collect(_CLAIM_UP_RE, "up")
    _collect(_CLAIM_DOWN_RE, "down")
    return claims


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
    input, so a clean zh-TW translation is dominated by Han script. After
    removing protected Latin tokens (URLs, tickers) — which a faithful mixed
    translation may keep — Han content must dominate Latin content; otherwise the
    output is an English echo / paraphrase / wrapper. An output equal to or
    containing the normalized source is also an echo.
    """
    stripped = (output or "").strip()
    if not stripped:
        return True
    src_norm = " ".join((source or "").split()).lower()
    out_norm = " ".join(stripped.split()).lower()
    if src_norm and (out_norm == src_norm or src_norm in out_norm):
        return True

    cleaned = _URL_TOKEN_RE.sub(" ", stripped)
    cleaned = _CASHTAG_RE.sub(" ", cleaned)
    known = _known_tickers()
    cleaned = _UPPER_WORD_RE.sub(
        lambda m: " " if m.group(0) in known else m.group(0), cleaned
    )
    han = len(_HAN_RE.findall(cleaned))
    latin = len(re.findall(r"[A-Za-z]", cleaned))
    if han == 0:
        return True
    return latin > han  # Chinese content must dominate a real translation


def fidelity_error(source: str, translation: str) -> str | None:
    """Return an error code when protected source values are corrupted.

    Compares typed multisets symmetrically: quantities carry their unit
    (percent / USD / bare) and per-value direction, so unit swaps, value
    changes, scaled-rescale errors, invented/dropped values and numbered-
    direction reversals are all caught; a separate directional-claim multiset
    catches clause-swapped direction/negation reversals; tickers are compared
    too. Returns ``None`` when fidelity holds or neither side carries anything
    protected.

    Deliberately NOT enforced: a pure entity↔value *permutation* that leaves
    both the value and ticker multisets individually balanced (``NVDA 25%, AMD
    30%`` -> ``NVDA 30%, AMD 25%``). Binding a value to its owning ticker
    reliably needs clause parity between English and zh-TW, which does not hold
    (English runs multiple facts together where zh-TW inserts commas), so a
    clause-scoped binding gate degrades many *faithful* translations to
    English-only. Because the complete English original is always delivered
    alongside the translation, such a permutation stays visible to the reader;
    a fragile gate would trade that visible, rare case for frequent false
    fallbacks. See ``docs/trump_truth_zh_tw_translation_v1.md``.
    """
    source_values, _ = _extract_value_tokens(source)
    translation_values, _ = _extract_value_tokens(translation)
    source_tickers = _ticker_counts(source)
    translation_tickers = _ticker_counts(translation)
    source_claims = _direction_claims(source)
    translation_claims = _direction_claims(translation)
    if not any(
        (
            source_values,
            translation_values,
            source_tickers,
            translation_tickers,
            source_claims,
            translation_claims,
        )
    ):
        return None
    if source_values != translation_values:
        return "fidelity_mismatch"
    if source_tickers != translation_tickers:
        return "fidelity_mismatch"
    if source_claims != translation_claims:
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
    # Defence in depth: settings already coalesces an empty env to a default,
    # but never construct an adapter with a blank model — a blank model name
    # would make every call fail late instead of cleanly disabling translation.
    model = (GEMINI_MODEL or "").strip()
    if not model:
        return None
    return GeminiTranslator(GEMINI_API_KEY, model)
