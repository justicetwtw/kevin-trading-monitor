# 一次性設置教學

## 0. 前置需求

- GitHub 帳號
- Telegram 帳號

## 1. Fork / Clone Repo

```bash
git clone <your-repo-url>
cd kevin-trading-monitor
```

或在 GitHub 網頁 Fork。

## 2. 建立 Telegram Bot

詳見 [telegram_bot_setup.md](telegram_bot_setup.md)

完成後你會有:
- `TELEGRAM_BOT_TOKEN`(類似 `1234567890:AAEhBP...`)
- `TELEGRAM_CHAT_ID`(類似 `123456789`)

## 3. 設定 GitHub Secrets

詳見 [github_secrets_setup.md](github_secrets_setup.md)

加入:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## 4. 第一次 Push

```bash
git add .
git commit -m "Initial setup"
git push origin main
```

## 5. 驗證 Health Check

到 GitHub Actions 頁面,**手動觸發** `Health Check` workflow:

1. Actions 標籤 → Health Check → Run workflow
2. 等 30-60 秒
3. 你的 Telegram 應收到 "🟢 System Online — kevin-trading-monitor v0.1.0" 訊息

## ✅ 設置完成

下一步:在新對話交付 PHASE 2 文件給 Claude Code,實作核心模組(三大訊號系統 + Layer 0/0+/F 等)。
