"""Gemini 音檔 → 逐字稿(繁中 + ticker 詞庫)。

用新版 google-genai 統一 SDK(from google import genai)。
音檔走 Files API 上傳(~50MB MP3 OK;檔案雲端暫存 48h,即用即可)。

紅線:
- google.genai 走 lazy import(函式內才 import)——讓本模組在沒裝 SDK / SDK
  import 失敗的環境仍可被 import(測試與 pipeline 載入不受影響)。
- 失敗一律 try/except 回 None,單集失敗不阻塞其他集。

§14 已知風險:長音檔單次轉錄可能被輸出 token 上限截斷或漂移成摘要。
v1 先單次 + 強逐字 prompt + 大 max_output_tokens。
"""

from __future__ import annotations

from loguru import logger

from src.config import gooaye_config
from src.config.settings import GEMINI_API_KEY, GEMINI_MODEL


def transcribe(mp3_path: str) -> str | None:
    """MP3 → 逐字稿字串;失敗回 None。

    TODO(§7.2 fallback):若實測長音檔被截斷/漂移成摘要,改成把音檔切 2 段
    分別轉錄再串接(chunking)。v1 先單次呼叫。
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY 未設定,跳過轉錄")
        return None

    try:
        # lazy import:SDK 介面會演進,且部分環境 import 即 crash;放函式內最安全
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        uploaded = client.files.upload(
            file=mp3_path,
            config=types.UploadFileConfig(mime_type="audio/mpeg"),
        )

        prompt = gooaye_config.build_transcribe_prompt()
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[uploaded, prompt],
            config=types.GenerateContentConfig(
                max_output_tokens=gooaye_config.TRANSCRIBE_MAX_OUTPUT_TOKENS,
            ),
        )

        transcript = (resp.text or "").strip()
        if not transcript:
            logger.error("Gemini 轉錄回傳空逐字稿")
            return None

        logger.info(f"Gooaye transcribe OK: {len(transcript)} chars")

        # 即用即清:刪掉雲端暫存檔(失敗不影響結果,48h 後自動過期)
        try:
            client.files.delete(name=uploaded.name)
        except Exception as e:
            logger.warning(f"Gemini 暫存檔刪除失敗(可忽略,48h 自動過期): {e}")

        return transcript
    except Exception as e:
        logger.error(f"Gooaye transcribe failed: {e}")
        return None
