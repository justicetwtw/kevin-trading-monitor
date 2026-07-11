"""股癌 Podcast Digest 進入點(GitHub Actions workflow 呼叫)。

比照既有 runner 風格(run_health_check.py):呼叫 pipeline.run(),sys.exit 回傳碼。
exit 0 = 成功 / no-op;exit 1 = 有集處理失敗(下次 run 會重試未標 seen 的集)。
"""

import sys

from src.gooaye.pipeline import run

if __name__ == "__main__":
    sys.exit(run())
