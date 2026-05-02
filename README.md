# Kevin Trading Monitor

> 個人化選擇權策略決策輔助系統 — 全雲端、零月費、佛系操作

## 是什麼

一套基於完整投資策略架構 v4 的自動化監測系統,GitHub Actions 24/7 雲端運作,Telegram 推播訊號:

- 🔥 **三大核心訊號**:賣 CALL / 賣 PUT(Wheel)/ LEAPS 進場
- 📊 **Layer 0 宏觀層**:7 子模組(Macro/Breadth/Distribution/Bubble/P-C/VIX 結構/AAII)
- 🚨 **Layer 0+ 事件層**:Trump Truth Social / RSS / Fed / SEC 8-K
- 💼 **Layer F 基本面**:7 子模組(基本面/分析師/13F/Form 4/庫藏股/TSMC 月營收/ETF 流)
- 📋 **部位管理**:LEAPS 損益 / Short Delta / 對沖 DTE / 帳戶回撤
- 🇹🇼 **台股模組**:00631L + 2330 三級加碼 + 6 檔主動 ETF 跟單
- 📈 **EV 追蹤 + 20 年回測**

## 設計哲學

1. **完全免費**:GitHub Public Repo + Actions(unlimited)+ yfinance + RSS = $0/月
2. **零維護**:設置完成後幾乎不需動手
3. **佛系操作**:5-15 分鐘延遲符合長線策略
4. **最終決策權在你**:系統提供訊號,你下單

## 快速開始

詳細設置教學見 [docs/setup_guide.md](docs/setup_guide.md)。

3 步驟:

1. **Fork 此 Repo**
2. **建立 Telegram Bot**,取得 token 與 chat_id ([docs/telegram_bot_setup.md](docs/telegram_bot_setup.md))
3. **設定 GitHub Secrets** ([docs/github_secrets_setup.md](docs/github_secrets_setup.md))

完成後 push,GitHub Actions 自動運作,你會在 Telegram 收到第一則 "System Online" 訊息。

## 文件

- [策略架構 v4](docs/strategy_v4.md) - 完整策略邏輯
- [系統架構](docs/architecture.md) - 技術架構
- [設置教學](docs/setup_guide.md) - 一次性設置
- [Telegram Bot 設置](docs/telegram_bot_setup.md)
- [GitHub Secrets 設置](docs/github_secrets_setup.md)

## 架構

```
src/
├── config/      # 設定檔(集中管理)
├── data/        # 資料抓取(階段 2)
├── indicators/  # 技術指標(階段 2)
├── layers/      # Layer 0/0+/F(階段 2)
├── signals/     # 三大核心訊號(階段 2)
├── management/  # 部位管理(階段 2)
├── twstock/     # 台股模組(階段 2)
├── alerts/      # Telegram 推播
├── storage/     # 狀態持久化
├── evaluation/  # EV/回測(階段 3)
└── runners/     # GitHub Actions 進入點
```

## License

MIT
