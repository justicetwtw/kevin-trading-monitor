# CLAUDE.md

> 本檔給 Claude Code / Claude 介面使用，但**內容刻意保持薄**：本專案的 agent 規範是 **LLM 中立**的，正式規則寫在 [`AGENTS.md`](AGENTS.md)。

## 先讀這個

請先完整讀 **[`AGENTS.md`](AGENTS.md)**，再讀 [`_onboarding/AI-ONBOARDING.md`](_onboarding/AI-ONBOARDING.md)。
`AGENTS.md` 是所有 AI（Claude / ChatGPT / Codex）共用的進場總則，包含：

- 唯一真實來源 = GitHub repo 最新 main
- 新 session 開場 SOP
- 紅線（不改 trading logic / 不改 workflow / 不改 secrets / 不補寫策略 / 訊號不得寫成投資建議 / 永不 force push）

本檔不重複那些內容，避免兩份規則漂移。**若本檔與 `AGENTS.md` 有出入，以 `AGENTS.md` 為準。**

## Claude Code 專屬小提醒

- 這是 Python 專案（純後端，無前端）。測試用 `pytest`，套件見 `requirements.txt` / `pyproject.toml`。
- 改檔前先用搜尋工具定位既有命名，沿用既有風格（見 `AGENTS.md` §3）。
- `data_store/*.json` 由 GitHub Actions 的 `commit-state` 自動 commit（訊息帶 `[skip ci]`）。手動改動專注在 `.py` / `.yml` / `.md`，避免與自動 state commit 衝突；若 push 撞到，`git pull --rebase origin main` 後重 push。
- 歷史背景：早期 onboarding 文件 `_onboarding/CLAUDE-ONBOARDING.md` 為 Claude 單一視角版本，已由 LLM 中立的 `_onboarding/AI-ONBOARDING.md` 取代，新內容以後者為準。

## 過往對話

接續開發時，先讀 `handoffs/` 內**日期最新**的一份（見 `handoffs/README.md`），不要請使用者重講進度。
