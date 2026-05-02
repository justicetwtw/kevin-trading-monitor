"""評分門檻、Modifier 區間 - 集中管理所有可調參數"""

# ============================================
# 推播分數門檻
# ============================================

PUSH_THRESHOLD_GREEN = 70   # 強推播
PUSH_THRESHOLD_YELLOW = 50  # 日報摘要
# < 50 不通知

# 標的優先級對應的推播門檻調整
PRIORITY_PUSH_THRESHOLD = {
    "P0": 70,  # Tier A + 持倉
    "P1": 75,  # Tier B
    "P2": 80,  # 觀察清單
    "P3": None,  # 不推
}

# ============================================
# 推播頻率上限(每日)
# ============================================

DAILY_PUSH_LIMITS = {
    "P0": 5,
    "P1": 10,
    "P2": None,  # 進日報
}

# ============================================
# Layer 0 Modifier 上下限
# ============================================

LAYER0_MODIFIER_MIN = -30
LAYER0_MODIFIER_MAX = 20

# ============================================
# 各子模組 Modifier 範圍
# ============================================

LAYER0_SUBMODIFIER_RANGES = {
    "macro_regime": (-15, 10),
    "breadth": (-10, 10),
    "distribution_days": (-20, 0),
    "bubble": (-15, 0),
    "put_call_ratio": (-10, 10),
    "vix_structure": (-15, 15),
    "aaii_sentiment": (-5, 5),
}

# ============================================
# 賣 CALL 評分權重
# ============================================

SELL_CALL_WEIGHTS = {
    "premium": 40,        # 權利金面
    "price": 40,          # 價格面
    "pattern": 20,        # 形態確認
    "max_layer0": 30,     # Layer 0 加成上限
}

# 賣 CALL 否決條件
SELL_CALL_VETO = {
    "earnings_within_days": 7,            # 7 天內財報否決
    "near_52w_high_pct": 0.99,            # ≥ 52W 高 × 0.99
    "volume_surge_multiplier": 1.5,       # 量 > 平均 1.5x
    "adx_strong_trend": 25,               # ADX > 25 = 強趨勢
    "analyst_upgrade_count": 2,           # 7 天內 ≥ 2 家上調 → 否決
}

# ============================================
# 賣 PUT 評分權重
# ============================================

SELL_PUT_WEIGHTS = {
    "premium": 35,
    "entry_quality": 45,
    "pattern": 20,
    "max_layer0": 30,
    "max_layerf": 35,     # 含 insider cluster + 庫藏股
}

# 賣 PUT 否決條件
SELL_PUT_VETO = {
    "must_be_in_whitelist": True,         # 不在白名單 → 否決
    "earnings_within_days": 7,
    "negative_catalyst_within_days": 7,
    "vix_extreme": 35,                    # VIX > 35 → 否決
    "max_assignments_per_month": 1,       # 單月已被指派 ≥1 次 → 否決
    "max_single_stock_exposure": 0.25,    # 個股總曝險 > 25% → 否決
}

# ============================================
# LEAPS 進場評分權重
# ============================================

LEAPS_ENTRY_WEIGHTS = {
    "entry_quality": 60,
    "valuation": 20,
    "volatility": 20,
    "max_layerf": 65,     # insider cluster (20) + 庫藏股 (20) + TSMC 月營收 (10) + VIX 結構 (15)
}

# LEAPS 進場否決
LEAPS_ENTRY_VETO = {
    "earnings_within_days": 7,
    "vix_extreme_consecutive_days": 3,    # 連 3 天 VIX > 30
    "fundamental_breakdown": True,        # 連 2 季 EPS miss
    "max_single_stock_exposure": 0.25,
    "value_thesis_review_or_exit": True,  # value_thesis = "review" 或 "exit" → 否決
}

# ============================================
# IV Rank 門檻
# ============================================

IVR_THRESHOLDS = {
    "high": 70,
    "medium": 50,
    "low": 30,
    "min_for_short_premium": 30,  # 學習鎖第 2 條
}

# 2x ETF 專用 IVR 門檻(更嚴)
IVR_2X_ETF_THRESHOLD = 60

# ============================================
# Distribution Days(IBD)
# ============================================

DISTRIBUTION_DAYS_RULE = {
    "lookback_days": 25,
    "min_drop_pct": 0.002,                # ≥ 0.2% drop
    "thresholds": {
        "healthy": 3,      # 0-3 healthy
        "pressure": 5,     # 4-5 承壓
        # 6+ 派發
    },
}

# ============================================
# Bubble Detector 門檻
# ============================================

BUBBLE_INDICATORS_THRESHOLDS = {
    "buffett_indicator": {
        "normal": 1.30,    # < 130%
        "warning": 1.80,   # 130-180%
        "bubble": 2.00,    # > 200%
    },
    "shiller_cape": {
        "normal": 20,
        "warning": 30,
        "bubble": 35,
    },
    "sp500_top10_concentration": {
        "normal": 0.25,
        "warning": 0.32,
        "bubble": 0.35,
    },
    "margin_debt_yoy": {
        "normal": 0.20,
        "warning": 0.50,
        "bubble": 0.50,    # > 50%
    },
    "aaii_bull_bear_spread": {
        "normal_range": (-20, 20),
        "warning": 40,
        "bubble": 40,      # > 40 連續
    },
}

# ============================================
# VIX 期貨結構
# ============================================

VIX_STRUCTURE_RULES = {
    "vix9d_inversion_modifier": 15,       # VIX9D > VIX → 賣 PUT/LEAPS +15
    "vix_vs_vix3m_inversion_pause": True, # VIX > VIX3M → 暫停新建 long premium
}

# ============================================
# Put/Call Ratio
# ============================================

PUT_CALL_RATIO_THRESHOLDS = {
    "extreme_fear": 1.20,        # > 1.2 → 賣 PUT/LEAPS +10
    "extreme_greed": 0.70,       # < 0.7 → 賣 CALL +10
}

# ============================================
# Insider Cluster Buying
# ============================================

INSIDER_BUYING_RULES = {
    "tier1_min_purchase_usd": 50_000,
    "tier2_ceo_cfo_min_usd": 250_000,
    "tier3_cluster": {
        "lookback_days": 30,
        "min_insiders": 3,
        "min_total_usd": 500_000,
    },
    "tier3_signal_boost": {
        "leaps_entry": 20,
        "sell_put": 15,
    },
    "tier2_signal_boost": {
        "leaps_entry": 10,
    },
    "ignore_codes": ["M", "10b5-1"],     # 忽略行使選擇權套現、計劃性賣出
}

# ============================================
# 庫藏股回購
# ============================================

BUYBACK_RULES = {
    "min_pct_of_market_cap": 0.05,        # ≥ 5% 市值 → LEAPS +20
    "asr_extra_boost": 5,                 # 加速回購額外 +5
}

# ============================================
# TSMC 月營收
# ============================================

TSMC_REVENUE_RULES = {
    "strong_yoy": 0.15,                   # > +15% → 半導體 +5
    "weak_yoy": -0.10,                    # < -10% → 警訊
}

# ============================================
# ETF 資金流
# ============================================

ETF_FLOW_RULES = {
    "smh_outflow_consecutive_days": 5,
    "smh_outflow_min_usd": 500_000_000,   # ≥ $500M
    "qqq_inflow_consecutive_days": 5,
    "qqq_inflow_min_usd": 1_000_000_000,  # ≥ $1B
}

# ============================================
# LEAPS 管理觸發點
# ============================================

LEAPS_MANAGEMENT_TRIGGERS = {
    "profit_protect_pct": 0.50,           # +50% 變 diagonal
    "profit_take_partial_pct": 1.00,      # +100% 賣 1/3
    "loss_warning_pct": -0.30,
    "loss_force_decision_pct": -0.40,
    "dte_roll_threshold_days": 270,       # < 9 個月評估 roll out
}

# LEAPS 規格
LEAPS_SPEC = {
    "min_dte_days": 365,                  # ≥ 12 個月
    "ideal_dte_days": (540, 720),         # 18-24 個月
    "delta_range": (0.55, 0.75),
    "max_premium_per_position_usd": 20_000,
    "max_position_pct_of_account": 0.12,
    "forbidden_otm_delta": 0.40,          # Delta < 0.40 的 OTM LEAPS 禁區
}

# ============================================
# Short Option 防守
# ============================================

SHORT_OPTION_DEFENSE = {
    "delta_warning_threshold": 0.35,      # |Delta| > 0.35 → 警報
    "profit_take_min_pct": 0.50,          # 50% 衰退即平倉
    "profit_take_max_pct": 0.70,          # 70% 為上限
}

# ============================================
# 對沖部位管理
# ============================================

HEDGE_DTE_THRESHOLD_DAYS = 45             # < 45 天 → 換倉提醒
HEDGE_PROFIT_TAKE_PCT = 1.00              # +100% 且 VIX > 30 → 賣 1/2

# ============================================
# 帳戶回撤防線
# ============================================

ACCOUNT_DRAWDOWN_LEVELS = {
    "level_1": -0.10,    # 全面檢視
    "level_2": -0.20,    # 強制檢視 LEAPS
    "level_3": -0.30,    # 防守模式,平所有 short premium
}

# ============================================
# Wheel Strategy (賣 PUT) 規格
# ============================================

SELL_PUT_SPEC = {
    "dte_range": (30, 45),
    "delta_range": (0.20, 0.30),
    "profit_take_pct": 0.50,
}

# ============================================
# Sell Call 規格
# ============================================

SELL_CALL_SPEC_LEAPS_OR_STOCK = {
    "dte_range": (30, 45),
    "delta_range": (0.20, 0.25),
}

SELL_CALL_SPEC_2X_ETF = {
    "dte_range": (14, 30),
    "delta_range": (0.10, 0.15),
    "max_position_pct_of_account": 0.05,
}

# ============================================
# 台股策略
# ============================================

TWSTOCK_TIER_RULES = {
    "A": {"drawdown_pct": -0.10, "weekly_rsi_max": 40, "deploy_pct": 0.25},
    "B": {"drawdown_pct": -0.20, "weekly_rsi_max": 35, "deploy_pct": 0.35},
    "C": {"drawdown_pct": -0.30, "weekly_rsi_max": 30, "deploy_pct": 0.40, "vix_min": 35},
}

TWSTOCK_CORE_ALLOCATION = {
    "00631L.TW": 0.60,
    "2330.TW": 0.40,
}

TWSTOCK_MIN_DAYS_BETWEEN_DEPLOYMENTS = 14  # 加碼後等 ≥2 週

# ============================================
# 台股主動 ETF 跟單訊號
# ============================================

TWSTOCK_ACTIVE_ETF_RULES = {
    "tier1_single_etf_min_nav_pct": 0.01,          # 單一 ETF 加碼 ≥ 1% NAV
    "tier2_multi_etf_count": 3,                    # 7 天內 ≥3 檔加碼同一股
    "tier2_lookback_days": 7,
    "tier3_consensus_etf_count": 5,                # ≥5 檔共同持有
    "tier3_lookback_days": 30,
}

# ============================================
# 季節性出場規則(LEAPS)
# ============================================

SEASONAL_EXIT_RULES = {
    "leaps_year_end_peak": {
        "dte_range_days": (60, 120),
        "near_high_pct": 0.05,                      # 距 52W 高 < 5%
        "trigger_months": [11, 12],                 # 11-12 月
    },
    "september_slump_defense": {
        "trigger_months": [7, 8],                   # 7 月底-8 月中
        "weekly_rsi_min": 70,
        "near_high_pct": 0.03,
        "reduce_position_pct": 1/3,
    },
}

# ============================================
# 學習鎖(寫死的禁區)
# ============================================

HARD_RULES = {
    "min_long_call_dte_days": 365,                  # 第 1 條
    "min_ivr_for_short_premium": 30,                # 第 2 條
    "no_short_premium_within_earnings_days": 7,     # 第 3 條
    "no_long_premium_after_vix_high_days": 3,       # 第 4 條
    "tier_c_no_sell_put": ["PLTR", "TSLA"],         # 第 5 條
    "no_long_position_for_2x_single_etf": True,     # 第 6 條
}
