from datetime import timedelta, timezone

from util.runtime_paths import data_file_path

SEOUL_TZ = timezone(timedelta(hours=9))
BALANCE_FILE = data_file_path("gambling_balance.json")
FINAL_BALANCE_LABEL = "최종 잔액"
BET_AMOUNT_REQUIRED = "❌ 배팅 금액은 0보다 커야 합니다."
