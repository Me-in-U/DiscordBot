from datetime import datetime

import holidays

today = datetime.now().date()

# 한국 및 미국 공휴일 데이터 가져오기
holiday_kr = holidays.Korea()
holiday_list = []
if today in holiday_kr:
    holiday_list.append(f"🇰🇷 한국 공휴일: {holiday_kr[today]}")
today_str = today.strftime("%m-%d")
# 특이한 기념일 추가 (수동 리스트 활용)
special_days = {
    "01-01": "🎉 새해 첫날",
    "02-14": "💖 발렌타인데이",
    "03-14": "🍫 화이트데이",
    "04-01": "😂 만우절",
    "05-04": "🌌 스타워즈 데이 (May the 4th Be With You)",
    "06-01": "🌍 세계 우유의 날",
    "07-07": "🍜 라면의 날",
    "08-08": "🐱 세계 고양이의 날",
    "09-19": "🏴‍☠️ 해적 말하기의 날",
    "10-31": "🎃 할로윈",
    "11-11": "🥨 빼빼로데이 / 🇺🇸 미국 재향군인의 날",
    "12-25": "🎄 크리스마스",
    "01-30": ["asd", "sdfgsdf"],
}
message = "📢 새로운 하루가 시작됩니다."
if today_str in special_days:
    # 리스트인지 확인하고, 리스트면 각 항목을 추가, 문자열이면 그대로 추가
    if isinstance(special_days[today_str], list):
        holiday_list.extend(special_days[today_str])
    else:
        holiday_list.append(special_days[today_str])

if holiday_list:
    message += "\n### 기념일\n- " + "\n- ".join(holiday_list)
print(message)
