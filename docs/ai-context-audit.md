# 전체 명령어와 AI 맥락 점검

2026-11-18에 `bot.py`와 `cogs/` 전체의 명령 선언, AI 호출, 메시지 수집과 프롬프트 입력 경로를 확인했다. 아래 명령 목록은 소스의 정적 선언 기준이며 실제 서버에 등록된 명령을 조회한 결과는 아니다. 그룹 명령의 하위 이름과 접두사 명령의 별칭도 함께 기록한다.

## 확인된 문제와 수정

봇 자신의 일반 발화는 이미 `assistant`로 저장되어 질문과 대화 요약에 포함됐다. 해석과 설명의 선택 메시지 주변 문맥에도 봇 발화가 이미 들어갔다. 하지만 메시지 수정 이벤트가 캐시를 삭제만 해 편집으로 완성되는 답변을 놓쳤고, 봇의 임베드 본문도 읽지 못했다. 직접 입력한 해석과 설명, 검색, 번역과 음식 추천에는 대화 맥락 전달이 없었다.

수정된 공개 메시지는 최신 내용을 재조회해 캐시에 반영한다. 빈 대기 응답에서 나중에 완성되는 답변도 수집한다. 재조회에 실패하면 오래된 내용은 남기지 않는다. 일반 수신과 재로드는 같은 수집 함수를 사용하고 메시지 ID로 중복을 제거한다. 봇 임베드의 제목, 본문과 필드를 포함하며 같은 초의 메시지는 ID로 순서를 구분한다.

## 기능별 맥락 범위

| 기능 | 변경 후 입력과 봇 발화 처리 |
|---|---|
| `/질문`, `/신이시여` | 기존 현재 채널 최근 20건 유지. 사람과 봇의 역할을 함께 전달 |
| `/검색` | 현재 채널 최근 20건 추가. 앞선 봇 답변의 지시 대상을 검색 근거로 다시 확인 |
| `/해석`, `/설명` 직접 입력 | 현재 채널 최근 20건을 이전 맥락으로 추가 |
| `/해석`, `/설명` 선택 및 메시지 메뉴 | 대상 앞뒤 각 10건에서 각 20건으로 확대. 인접 이미지 최대 4장 유지 |
| `/번역` 직접 입력 | 현재 채널 최근 20건 추가. 번역 대상 외 대화는 번역하지 않음 |
| `/번역` 선택 및 메시지 메뉴 | 대상 앞뒤 각 최대 20건 추가. 지시어와 용어 해소에만 사용 |
| `/뭐먹지` | 현재 채널 최근 20건 추가. 최근 추천 메뉴 20개 제외와 허용 목록 유지 |
| `/대화요약` | 기존 요약 원문 최대 150건과 최근 이미지 최대 4장 유지. 20건 보조 맥락과 다른 용도의 입력 |
| `/요약`, 유튜브 메시지 메뉴, 자동 링크 요약 | 선택한 영상 전사, 댓글 또는 게시물 원문만 처리 |
| 메이플스토리 및 로스트아크 공지 | 지정 공지 원문만 처리. 채널의 잡담과 섞지 않음 |
| Codex 리셋 및 Tibo 알림 | 지정 JSON 원문만 번역 또는 요약 |
| 자동 1557 감지 | 대상 텍스트 또는 이미지의 실제 숫자만 판별 |
| 그 밖의 운영, 음악, 게임과 정보 명령 | 대화형 생성 모델 호출 없음. 채널 대화를 전달할 AI 요청도 없음 |
| 음성 관련 명령 | 음성 인식과 음성 채널 처리. 텍스트 생성용 대화 프롬프트 없음 |

채널 ID와 요청자의 채널 보기 및 이력 읽기 권한을 기준으로 맥락을 제한한다. 다른 채널의 기록과 이미지는 섞지 않는다. 번역, 해석과 설명의 최근 메시지 선택 목록에서도 봇 메시지를 고를 수 있다. 주변 맥락에서 실제 봇 화자는 `(봇)`으로 구분한다.

## 저장형 프롬프트

사용 중인 프롬프트 15개는 모두 한국어 지시문이다. 신이시여 v11은 앞서 개편된 내용을 유지하고 나머지 14개의 역할, 입력, 판단, 자료 경계, 예외와 출력 계약을 정리해 게시했다. 정확한 버전과 전문은 [AI 말투와 저장형 프롬프트](ai-prompt-voice.md)에 있다. 모델과 추론 강도, 검색 설정 및 JSON 필드 이름은 유지했다.

## 수집 범위와 확인 한계

메시지 캐시는 메모리 기반이며 작성자별 최근 100건으로 제한된다. 시작 및 일일 재로드는 기존처럼 채널 최근 100건 중 당일 메시지를 읽는다. 공개 채널의 본문과 봇 임베드 및 이미지 첨부를 수집하며 비공개 응답이나 첨부 텍스트 파일의 내부 내용은 채널 대화로 읽지 않는다. 실제 Discord 이벤트 전달과 Jenkins 배포는 별도 실행 검증 대상이다.

## 전체 명령 선언 목록

| 소스 | 명령 및 메뉴 |
|---|---|
| [bot.py](../bot.py) | `echo / 채팅`, `ping / 핑` |
| [cogs/celebration_update/__init__.py](../cogs/celebration_update/__init__.py) | `기념일업데이트` |
| [cogs/channel_settings/__init__.py](../cogs/channel_settings/__init__.py) | `채널설정`, `채널설정확인` |
| [cogs/clean/__init__.py](../cogs/clean/__init__.py) | `clean` |
| [cogs/codex_resets/__init__.py](../cogs/codex_resets/__init__.py) | `코덱스리셋알림` |
| [cogs/custom_help/__init__.py](../cogs/custom_help/__init__.py) | `도움`, `기가채드` |
| [cogs/dday/__init__.py](../cogs/dday/__init__.py) | `dday추가`, `dday삭제`, `dday목록` |
| [cogs/earthquake_alert/__init__.py](../cogs/earthquake_alert/__init__.py) | `지진알림` |
| [cogs/exchange_rate/__init__.py](../cogs/exchange_rate/__init__.py) | `환율` |
| [cogs/explanation/__init__.py](../cogs/explanation/__init__.py) | `메시지 설명 (메시지 메뉴)`, `설명` |
| [cogs/foreign_reserves/__init__.py](../cogs/foreign_reserves/__init__.py) | `외환보유액` |
| [cogs/gambling/__init__.py](../cogs/gambling/__init__.py) | `뿌리기`, `돈줘`, `잔액`, `순위`, `송금`, `가위바위보`, `도박`, `즉석복권`, `사다리`, `슬롯`, `블랙잭` |
| [cogs/interpret/__init__.py](../cogs/interpret/__init__.py) | `메시지 해석 (메시지 메뉴)`, `해석` |
| [cogs/lol_scrim/__init__.py](../cogs/lol_scrim/__init__.py) | `내전` |
| [cogs/lostark/__init__.py](../cogs/lostark/__init__.py) | `로아공지구독` |
| [cogs/maplestory/__init__.py](../cogs/maplestory/__init__.py) | `썬데이메이플`, `메이플공지구독` |
| [cogs/meal_recommendation/__init__.py](../cogs/meal_recommendation/__init__.py) | `뭐먹지` |
| [cogs/minecraft/__init__.py](../cogs/minecraft/__init__.py) | `마크서버` |
| [cogs/music/__init__.py](../cogs/music/__init__.py) | `음악`, `재생`, `일시정지`, `다시재생`, `정지`, `스킵`, `대기열`, `구간이동`, `반복`, `대기열삭제`, `대기열비우기`, `대기열이동`, `셔플` |
| [cogs/party/__init__.py](../cogs/party/__init__.py) | `파티`, `파티생성`, `파티초대`, `파티해제`, `파티참가`, `파티원`, `파티탈퇴` |
| [cogs/ping/__init__.py](../cogs/ping/__init__.py) | `핑` |
| [cogs/questions/__init__.py](../cogs/questions/__init__.py) | `질문`, `신이시여` |
| [cogs/rank/__init__.py](../cogs/rank/__init__.py) | `솔랭`, `자랭`, `일일랭크`, `일일랭크변경`, `일일랭크루프` |
| [cogs/scheduler/__init__.py](../cogs/scheduler/__init__.py) | `일반`, `반복`, `리스트` |
| [cogs/search/__init__.py](../cogs/search/__init__.py) | `검색` |
| [cogs/summarize/__init__.py](../cogs/summarize/__init__.py) | `유튜브 요약 (메시지 메뉴)`, `대화요약`, `요약` |
| [cogs/translation/__init__.py](../cogs/translation/__init__.py) | `메시지 번역 (메시지 메뉴)`, `번역` |
| [cogs/voice_chat/__init__.py](../cogs/voice_chat/__init__.py) | `대화`, `대화종료` |
| [cogs/vote/__init__.py](../cogs/vote/__init__.py) | `투표` |
| [cogs/youtube_subscriptions/__init__.py](../cogs/youtube_subscriptions/__init__.py) | `추가`, `알림설정`, `삭제`, `목록` |
