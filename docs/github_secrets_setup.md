# GitHub Secrets 設置教學

## 1. 進入 Repo Settings

1. 開你的 GitHub repo 頁面
2. 點 Settings(右上角)
3. 左側選 Secrets and variables → Actions

## 2. 新增 Secrets

點 "New repository secret" 兩次,各加入:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 你的 Bot token(類似 `1234567890:AAEhBP...`) |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID(類似 `123456789`) |

## 3. 驗證

到 Actions 頁面 → Health Check → Run workflow,手動觸發。
30-60 秒後,Telegram 應收到 System Online 訊息。

## 安全注意

- ❌ 不要把 token 直接寫進程式碼
- ❌ 不要 commit `.env` 檔
- ✅ 一律走 GitHub Secrets

## 後續(可選)

之後階段如果加入其他 API key(例如 FRED API key 等),都用同一方式新增 Secret。
