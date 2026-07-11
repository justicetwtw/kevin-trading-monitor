"""Gemini 逐字稿(純文字)→ 結構化摘要(Markdown)。

第二段呼叫:吃文字不吃音檔(便宜、可獨立調 prompt)。
與 transcriber 同紀律:google.genai lazy import、失敗 try/except 回 None。
"""

from __future__ import annotations

from loguru import logger

from src.config import gooaye_config
from src.config.settings import GEMINI_API_KEY, GEMINI_MODEL


def summarize(transcript: str) -> str | None:
    """逐字稿 → Markdown 摘要;失敗回 None。"""
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY 未設定,跳過摘要")
        return None
    if not transcript or not transcript.strip():
        logger.error("逐字稿為空,跳過摘要")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = gooaye_config.build_summarize_prompt(transcript)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                max_output_tokens=gooaye_config.SUMMARIZE_MAX_OUTPUT_TOKENS,
            ),
        )

        summary = (resp.text or "").strip()
        if not summary:
            logger.error("Gemini 摘要回傳空字串")
            return None

        logger.info(f"Gooaye summarize OK: {len(summary)} chars")
        return summary
    except Exception as e:
        logger.error(f"Gooaye summarize failed: {e}")
        return None
