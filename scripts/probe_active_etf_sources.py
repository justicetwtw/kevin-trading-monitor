"""主動式 ETF 持股資料源「探針」(measure-first,讀取用,不寫狀態、不寄信)。

目的:在「對外網路開放」的環境(Kevin 本機 / GitHub Actions runner)實打候選資料源,
印出真實結構,讓我們**照真實格式**寫 parser,而不是猜格式硬寫(踩雷筆記 §1/§2)。

用法:
    python scripts/probe_active_etf_sources.py
把整段輸出貼回給 Claude,即可據此完成台股 + 海外 持股 parser。

這支腳本是可丟棄的診斷工具,不進 production 路徑。
"""

from __future__ import annotations

import json

import httpx

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 30.0

# 要驗證的代表性主動 ETF:台股龍頭 + 投資海外的幾檔(成分應出現美股代號)
TW_SAMPLE = "00981A"          # 主動統一台股增長(純台股,龍頭 ~1,800 億)
OVERSEAS_SAMPLES = ["00988A", "00983A", "00990A"]  # 全球創新 / 中信ARK創新 / 元大AI新經濟

TWSE_OPENAPI = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
TWSE_SWAGGER = "https://openapi.twse.com.tw/v1/swagger.json"


def _get(url: str):
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r


def _looks_foreign(code: str) -> bool:
    """粗略判定:台股代號多為 4–6 位數字;含英文字母的多半是美股/海外。"""
    code = str(code or "").strip()
    return bool(code) and not code.replace(".", "").isdigit()


def probe_swagger() -> None:
    print("\n" + "=" * 70)
    print("A) TWSE OpenAPI swagger:找出所有跟 ETF 成分/持股有關的資料集")
    print("=" * 70)
    try:
        spec = _get(TWSE_SWAGGER).json()
        paths = spec.get("paths", {})
        hits = []
        for path, meta in paths.items():
            blob = json.dumps(meta, ensure_ascii=False)
            if any(k in blob for k in ["ETF", "成分", "持股", "基金", "投資組合"]):
                # 取 summary 方便辨識
                summary = ""
                for method in meta.values():
                    if isinstance(method, dict) and method.get("summary"):
                        summary = method["summary"]
                        break
                hits.append((path, summary))
        if not hits:
            print("  (沒在 swagger 找到明顯 ETF 持股資料集,需人工翻 swagger UI)")
        for path, summary in hits:
            print(f"  {path}  —  {summary}")
    except Exception as e:
        print(f"  swagger 取得失敗: {type(e).__name__}: {e}")


def probe_twse_openapi() -> None:
    print("\n" + "=" * 70)
    print("B) t187ap47_L:現有 code 假設的台股持股資料集")
    print("=" * 70)
    try:
        data = _get(TWSE_OPENAPI).json()
        print(f"  總筆數: {len(data)}")
        if data:
            print(f"  第一筆欄位(keys): {list(data[0].keys())}")
            print(f"  第一筆內容: {json.dumps(data[0], ensure_ascii=False)[:300]}")

        # 找出資料集裡有哪些「基金代號」
        def _fund_code(rec: dict) -> str:
            return str(rec.get("基金統一編號") or rec.get("基金代號")
                       or rec.get("證券代號") or rec.get("基金中文簡稱") or "")

        funds = {}
        for rec in data:
            fc = _fund_code(rec)
            funds[fc] = funds.get(fc, 0) + 1
        print(f"  資料集涵蓋的基金代號數: {len(funds)}")

        for sym in [TW_SAMPLE, *OVERSEAS_SAMPLES]:
            present = any(sym in k for k in funds.keys())
            print(f"  - {sym} 是否出現在資料集: {'✅ 有' if present else '❌ 沒有'}")
            if present:
                recs = [r for r in data if sym in _fund_code(r)][:5]
                for r in recs:
                    code = r.get("持股代號") or r.get("成分股代號") or ""
                    name = r.get("持股名稱") or r.get("成分股名稱") or ""
                    flag = "🌎海外?" if _looks_foreign(code) else "台股"
                    print(f"      {code} {name}  [{flag}]")
    except Exception as e:
        print(f"  t187ap47_L 取得失敗: {type(e).__name__}: {e}")


def probe_moneydj() -> None:
    print("\n" + "=" * 70)
    print("C) MoneyDJ 海外持股備援樣本(只看 00988A 全球創新,確認有沒有美股成分)")
    print("=" * 70)
    url = "https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid=00988a.tw"
    try:
        r = _get(url)
        text = r.text
        print(f"  狀態 OK,HTML 長度 {len(text)};以下節錄含 '持股' 的片段:")
        idx = text.find("持股")
        print("  " + text[max(0, idx - 100): idx + 400].replace("\n", " ")[:500])
    except Exception as e:
        print(f"  MoneyDJ 取得失敗(可能擋爬/需 JS): {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("主動式 ETF 持股資料源探針 — 把整段輸出貼回給 Claude")
    probe_swagger()
    probe_twse_openapi()
    probe_moneydj()
    print("\n完成。重點看:B 段 t187ap47_L 是否涵蓋海外 ETF 且成分是否含美股代號。")
