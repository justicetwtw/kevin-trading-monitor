"""主動式 ETF 經理人共識 digest — 設定集中地(獨立功能,純加法)。

目標:抓台灣大型主動式 ETF 每日持股 → 跨經理人共識(誰同向加/減碼)→ 每日盤後 email 趨勢摘要。
含台股檔 + 投資海外(美股)的檔(對 Kevin 美股部位最有參考價值)。

⚠ 資料源狀態(measure-first,見 scripts/probe_active_etf_sources.py):
  - 台股持股:沿用既有 src/data/twstock_active_etf.py 的 TWSE OpenAPI(t187ap47_L),待 runner 實證。
  - 海外持股:資料源尚未實證(TWSE OpenAPI 可能僅含台股成分);跑完探針確認真實格式後再接 parser。
  - 下方清單規模/名稱以 2026Q2 公開資料填,標 (待確認) 者請對照探針輸出的官方基金清單校正。
"""

# ============================================
# 共識 / 摘要參數
# ============================================

# 權重變動 ≥ 此百分點(pp)才算一次「加/減碼」動作
MIN_WEIGHT_DELTA_PP = 0.3

# 共識窗格(天)
SHORT_WINDOW_DAYS = 7
LONG_WINDOW_DAYS = 30

# 每日持股快照保留天數:每日抓不需囤太多,但必須 ≥ 長窗才算得出 30 日共識,
# 多 15 天緩衝吸收週末/假日/漏跑(基準日挑「≤ today-N」最近的快照)。
HOLDINGS_HISTORY_DAYS = LONG_WINDOW_DAYS + 15  # = 45

# 摘要榜:各方向(加碼/減碼)各取前 N 名
DIGEST_TOP_N = 15

# 「共識」門檻:同一標的被 ≥ 此數量的經理人同向操作才上摘要重點區
CONSENSUS_MIN_FUNDS = 3

# 持股快照狀態檔(獨立於既有 active_etf_holdings.json,避免動到既有台股 TG 流程)
DIGEST_HOLDINGS_FILE = "active_etf_digest_holdings.json"

# email 主旨前綴
EMAIL_SUBJECT_PREFIX = "[主動ETF共識]"


# ============================================
# 標的清單(台股 + 海外)
# ============================================
# market:
#   "tw"       純台股成分
#   "overseas" 主要投資海外(美股/全球)
#   "mixed"    台股 + 海外都有(成分 market 以「逐持股」判定,fund 層只當分組提示)
# scope 僅用於 digest 分區顯示;真正 market 判定看每一檔持股代號(台股=數字、美股=英文字母)。

ACTIVE_ETF_FUNDS = [
    # ---- 台股(沿用既有 universe.TWSTOCK_ACTIVE_ETFS 命名)----
    {"symbol": "00981A.TW", "name": "主動統一台股增長", "manager": "統一投信",
     "market": "tw", "size_billion_ntd": 1833, "focus": "AI 供應鏈,大型成長(龍頭)"},
    {"symbol": "00982A.TW", "name": "主動群益台灣強棒", "manager": "群益投信",
     "market": "tw", "size_billion_ntd": 156, "focus": "量化選股 + 中小型成長"},
    {"symbol": "00992A.TW", "name": "主動群益科技創新", "manager": "群益投信",
     "market": "tw", "size_billion_ntd": 100, "focus": "純科技主題"},
    {"symbol": "00980A.TW", "name": "主動野村台灣優選", "manager": "野村投信",
     "market": "tw", "size_billion_ntd": 100, "focus": "AI + 大型權值"},
    {"symbol": "00985A.TW", "name": "主動野村台灣 50", "manager": "野村投信",
     "market": "tw", "size_billion_ntd": 80, "focus": "對標 0050 的主動版"},
    {"symbol": "00987A.TW", "name": "主動野村臺灣科技 50", "manager": "野村投信",
     "market": "tw", "size_billion_ntd": 80, "focus": "純科技 50 檔"},
    {"symbol": "00984A.TW", "name": "主動安聯台灣高息", "manager": "安聯投信",
     "market": "tw", "size_billion_ntd": None, "focus": "高息收益(待確認)"},

    # ---- 海外 / 全球(對美股部位最有參考價值;名稱規模待探針校正)----
    {"symbol": "00983A.TW", "name": "主動中信 ARK 創新", "manager": "中信投信",
     "market": "overseas", "size_billion_ntd": None,
     "focus": "美股創新(ARK 系,TSLA/COIN 等,待確認)"},
    {"symbol": "00988A.TW", "name": "主動統一全球創新", "manager": "統一投信",
     "market": "mixed", "size_billion_ntd": None,
     "focus": "全球創新,跨美/德/台(待確認)"},
    {"symbol": "00990A.TW", "name": "主動元大 AI 新經濟", "manager": "元大投信",
     "market": "overseas", "size_billion_ntd": None,
     "focus": "美股 / 全球 AI 科技(待確認)"},
]


def tw_funds() -> list[dict]:
    """純台股 + 含台股成分(mixed)的檔。"""
    return [f for f in ACTIVE_ETF_FUNDS if f["market"] in ("tw", "mixed")]


def overseas_funds() -> list[dict]:
    """投資海外(overseas / mixed)的檔。"""
    return [f for f in ACTIVE_ETF_FUNDS if f["market"] in ("overseas", "mixed")]


def fund_symbols() -> list[str]:
    return [f["symbol"] for f in ACTIVE_ETF_FUNDS]


def classify_holding_market(holding_code: str) -> str:
    """逐持股判定市場(provisional,待探針確認海外代號真實格式再校正)。

    台股代號一律以數字開頭(2330 / 0050 / 00981A);美股 ticker 以英文字母開頭(NVDA)。
    用「首字元是數字 vs 字母」判定,比「整串是否純數字」穩(後者會把 00981A 誤判海外)。
    """
    code = str(holding_code or "").strip()
    if not code:
        return "unknown"
    return "tw" if code[0].isdigit() else "overseas"
