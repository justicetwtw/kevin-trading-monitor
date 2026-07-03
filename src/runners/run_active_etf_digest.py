"""主動式 ETF 經理人共識 digest 進入點(workflow 呼叫)。

比照既有 runner 風格:呼叫 pipeline run(),sys.exit 回傳碼。
"""

import sys

from src.twstock.active_etf_digest import run

if __name__ == "__main__":
    sys.exit(run())
