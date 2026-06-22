# 股癌 Podcast Digest 設定教學(gooaye-digest）

這個功能會自動偵測「股癌」podcast 新集 → Gemini 轉逐字稿 + 摘要 → Email 寄給 Kevin。
全自動跑在 GitHub Actions,不依賴本機 PC。

跑起來只需要設 **4 個 GitHub Secrets**(`GEMINI_MODEL` 選填)。以下逐步。

---

## 1. 取得 Gemini API Key(免費層)

1. 到 <https://aistudio.google.com/apikey>(Google AI Studio),用 Google 帳號登入。
2. 點 **Create API key** → 複製金鑰(`AIza...` 開頭)。
3. 免費層額度足夠:股癌一週兩集,遠低於免費層每日上限。

> **模型 ID**:預設 `gemini-2.5-flash`(已查證免費層、支援音訊輸入)。
> 若 AI Studio 顯示有更新的免費層音訊模型(例如 `gemini-3-flash`),只要設
> `GEMINI_MODEL` secret 換掉即可,程式不用動。**免費層不含 Pro**,別填 Pro 系列。

---

## 2. 取得 Gmail App Password(寄件用）

App password 需要帳號先開啟 **2 階段驗證**。

1. 到 <https://myaccount.google.com/security>,開啟「兩步驟驗證」。
2. 到 <https://myaccount.google.com/apppasswords>。
3. 取一個名字(例如 `gooaye-digest`)→ 產生 → 得到 **16 碼密碼**(會顯示成 `abcd efgh ijkl mnop`)。
4. 這 16 碼就是 `GMAIL_APP_PASSWORD`。**程式會自動去掉空格**,你貼上有沒有空格都行。

> **建議**:用一個「機器專用」Gmail 帳號當寄件者(`GMAIL_SENDER`),
> 跟私人信箱分流,萬一 app password 外洩影響範圍也小。用既有帳號也可以,
> 只是 `GMAIL_SENDER` / `GMAIL_APP_PASSWORD` 兩個值的差別,不影響程式。

---

## 3. 設定 GitHub Secrets

到 repo → **Settings → Secrets and variables → Actions → New repository secret**,
新增以下幾個:

| Secret 名稱 | 必填 | 說明 | 範例 |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ | 第 1 步的 Gemini 金鑰 | `AIza...` |
| `GMAIL_SENDER` | ✅ | 寄件 Gmail 完整地址 | `gooaye.bot@gmail.com` |
| `GMAIL_APP_PASSWORD` | ✅ | 第 2 步的 16 碼 app password | `abcd efgh ijkl mnop` |
| `EMAIL_RECIPIENT` | ✅ | 收件信箱(可逗號分隔多人) | `kevin@gmail.com` |
| `GEMINI_MODEL` | ⬜ 選填 | 不填則用預設 `gemini-2.5-flash` | `gemini-2.5-flash` |

> 多收件人:`EMAIL_RECIPIENT` 填 `kevin@gmail.com,lisa@gmail.com`(逗號分隔)。
> v1 預設只寄 Kevin。

---

## 4. 第一次執行(手動觸發測試)

1. repo → **Actions → Gooaye Digest → Run workflow**(`workflow_dispatch`)。
2. 預期:
   - **首次執行**會把目前 feed 全部約 600+ 集標記為「已看過」,但**只處理最新 1 集**
     (bootstrap 保護,避免一次轉錄整個歷史節目把額度燒光、信箱塞爆)。
   - 約幾分鐘後,Kevin 收到**一封 email**:內文是結構化摘要(產業 / 持股 / 核心觀點),
     附件是 `{集名}.md` 逐字稿。
3. **再次手動觸發** → 不會重複寄(dedup 生效,該集已標 seen)。
4. 之後系統每 30 分鐘輪詢一次,有新集才會處理(每次最多 2 集),99% 的 run 是 no-op。

---

## 5. 運作機制與容錯(備忘)

- **狀態檔**:`data_store/gooaye_seen.json` 記已處理集數的 GUID,workflow 跑完自動 commit 回 repo
  (比照 Trump monitor 的 state commit:`pull --rebase` 防 push race)。
- **容錯**:任何一集的下載 / 轉錄 / 摘要 / 寄信失敗,只會跳過那一集並記 log,
  不影響其他集;未成功的集不標 seen,下次 run 自動重試。
- **額度安全**:dedup 先擋,只有真有新集才會打 Gemini,每 30 分輪詢不燒額度。
- **排程延遲**:GitHub Actions 對低活動 repo 的 schedule 可能延後幾十分鐘觸發,
  podcast digest 非急件可接受。

---

## 6. 已知限制 / 待觀察

- **長音檔逐字稿**:50 分鐘單次轉錄,極端情況可能被輸出長度截斷或漂移成摘要;
  v1 用強逐字 prompt + 大 `max_output_tokens` 緩解,若實測不夠之後切「分段轉錄」。
- **台味國語 + 代號辨識**:已餵 ticker 詞庫提升辨識,但無法保證 100% 正確,
  逐字稿存疑代號摘要會標「(待確認)」。需要更高品質時,後路是地端 faster-whisper。
- **版權**:逐字稿僅供 Kevin 本人閱讀,請勿公開散布。
