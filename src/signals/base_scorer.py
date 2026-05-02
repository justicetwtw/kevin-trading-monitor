"""共用評分基底:權重套用、邊界 clip、12 欄 return dict 統一格式。"""

from datetime import datetime, timezone


def normalize_to_100(score: float, max_score: float) -> float:
    """將原始分數縮放至 0-100。"""
    if max_score <= 0:
        return 0.0
    return min(100.0, max(0.0, score / max_score * 100))


def score_with_threshold(value: float, thresholds: list, scores: list) -> float:
    """根據閾值階梯給分。
    e.g. score_with_threshold(rsi, [30, 50, 70], [40, 20, 5]) =
         rsi<=30 → 40, rsi<=50 → 20, rsi<=70 → 5, else 0
    """
    for thr, s in zip(thresholds, scores):
        if value <= thr:
            return float(s)
    return 0.0


def clip(value: float, lo: float, hi: float) -> float:
    """通用 clip。"""
    return max(lo, min(hi, value))


def now_iso() -> str:
    """ISO 8601 with UTC tz。"""
    return datetime.now(timezone.utc).isoformat()


def alert_level_from_score(final_score: float, push_threshold: int | None,
                            green: int = 70, yellow: int = 50) -> str:
    """根據 final_score 與 priority push threshold 決定推播等級。
    green ≥ priority threshold(如沒給用 70);
    yellow ∈ [50, threshold);
    white < 50。
    """
    threshold = push_threshold if push_threshold is not None else green
    if final_score >= threshold:
        return "green"
    if final_score >= yellow:
        return "yellow"
    return "white"


def build_scorer_result(
    symbol: str,
    signal_type: str,
    raw_score: float,
    layer0_modifier: int = 0,
    layer_f_modifier: int = 0,
    components: dict | None = None,
    indicators: dict | None = None,
    veto_triggered: bool = False,
    veto_reasons: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    """統一 12 欄 return dict 格式。

    final_score = max(0, raw_score + layer0_modifier + layer_f_modifier)(若 veto 則為 0)
    alert_level / tags / priority / push_threshold 由 final_scorer 後注入。
    """
    if veto_triggered:
        final_score = 0.0
    else:
        final_score = max(0.0, raw_score + layer0_modifier + layer_f_modifier)

    result = {
        "symbol": symbol,
        "signal_type": signal_type,
        "raw_score": float(raw_score),
        "final_score": float(final_score),
        "layer0_modifier": int(layer0_modifier),
        "layer_f_modifier": int(layer_f_modifier),
        "veto_triggered": bool(veto_triggered),
        "veto_reasons": list(veto_reasons or []),
        "alert_level": "white",  # final_scorer 後覆寫
        "tags": [],               # final_scorer 後注入
        "components": dict(components or {}),
        "indicators": dict(indicators or {}),
        "scan_time": now_iso(),
    }
    if extra:
        result.update(extra)
    return result
