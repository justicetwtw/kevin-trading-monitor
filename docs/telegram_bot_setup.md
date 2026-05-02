# Telegram Bot 設置教學

## 1. 建立 Bot

1. 開 Telegram,搜尋 `@BotFather`
2. 開始對話,送 `/newbot`
3. 設定 Bot 名稱(任意):例如 `Kevin Trading Monitor`
4. 設定 Bot 用戶名(必須以 `bot` 結尾):例如 `kevin_trading_monitor_bot`
5. BotFather 會回覆 token,類似:`1234567890:AAEhBPxxxxxxxxxxxxxxxx`
6. **記下這個 token**,這是你的 `TELEGRAM_BOT_TOKEN`

## 2. 取得 Chat ID

1. 在 Telegram 主動傳訊息給你新建的 bot(隨便傳一句)
2. 開瀏覽器,訪問:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. 找到 `"chat":{"id":123456789,...}`
4. **記下這個 id 數字**,這是你的 `TELEGRAM_CHAT_ID`

## 3. 設置完成

把 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 設為 GitHub Secrets,見 [github_secrets_setup.md](github_secrets_setup.md)

## 故障排除

- **getUpdates 沒結果?** → 確認你**主動傳訊息給 bot 至少一次**
- **token 找不到?** → 對 BotFather 送 `/mybots`,選你的 bot,選 "API Token"
