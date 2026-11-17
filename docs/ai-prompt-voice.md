# AI 응답 말투와 저장형 프롬프트

2026-11-18 기준으로 사용 중인 저장형 프롬프트 15개의 자연어 지시문은 모두 한국어다. 14개는 역할, 입력, 판단 기준, 자료 경계, 예외와 출력 계약을 구분해 게시했다. `god_question`은 v12에서 본섭 이벤트와 테스트월드 패치노트를 함께 확인하고 현재 이벤트에서 다음 이벤트로 이어지는 상황을 설명하도록 보강했다. API 변수 이름과 JSON 키는 호출 코드의 계약이므로 유지한다.

## 게시 버전과 전문

| 기능 | 버전 | 전문 |
|---|---|---|
| 일반 질문 | 13 | [general_prompt](prompts/general_prompt.md) |
| 신이시여 | 12 | [god_question](prompts/god-question.md) |
| 해석 | 23 | [interpret](prompts/interpret.md) |
| 설명 | 12 | [explanation](prompts/explanation.md) |
| 번역 | 12 | [translation](prompts/translation.md) |
| 웹 검색 | 15 | [web_search](prompts/web_search.md) |
| 음식 추천 | 4 | [meal](prompts/meal.md) |
| 대화 요약 | 12 | [discord_summary](prompts/discord_summary.md) |
| 영상 요약 | 12 | [youtube_summary](prompts/youtube_summary.md) |
| 댓글 요약 | 14 | [comments_summary](prompts/comments_summary.md) |
| 유튜브 게시물 요약 | 2 | [youtube_post_summary](prompts/youtube_post_summary.md) |
| 게임 공지 요약 | 3 | [game_notice_summary](prompts/game_notice_summary.md) |
| 1557 이미지 판별 | 11 | [find1557](prompts/find1557.md) |
| Codex 리셋 번역 | 3 | [codex_reset_translation](prompts/codex_reset_translation.md) |
| Tibo 일일 소식 요약 | 2 | [tibo_summary](prompts/tibo_summary.md) |

기존 모델, 추론 강도, 도구와 JSON 스키마는 유지했다. 일반 질문과 검색은 GPT-6.1 Sol의 medium, 해석은 GPT-6.1 Sol의 high, 신이시여는 GPT-6.1 Terra의 medium이다. 나머지 기능은 기존 GPT-6 Luna 설정을 유지한다. 신이시여만 앞선 개편의 존댓말 패러디를 유지한다.

## 말투와 정확성

일반 대화와 요약은 짧고 직설적인 한국어 반말을 쓴다. 건조한 비유나 날카로운 관찰은 실제 상황에서 나온 근거가 있을 때만 넣는다. 웃음 문자, 반응 이모지와 고정 유행어를 강요하지 않는다. 사람의 인격을 공격하거나 재미를 위해 감정, 동기, 화자 관계와 사실을 만들지 않는다. 개인의 고통이나 실제 안전 문제에는 농담을 생략한다.

번역은 원문의 격식과 감정의 강도를 보존한다. 음식 추천은 허용된 메뉴 이름 하나만, 숫자 판별과 알림 번역은 구성된 JSON 스키마만 반환한다. 요약의 줄 수와 길이, 실제 일정과 조건 보존이 말투보다 우선한다. 게임 공지는 실제 제한, 점검과 수령 부담을 날카롭게 짚을 수 있지만 원문에 없는 보상, 과실이나 감정을 추가하지 않는다.

## 맥락과 원문

대화형 명령은 현재 채널의 사람과 봇 발화를 함께 참고한다. 봇 답변은 대화의 자료일 뿐 검증된 사실이나 사용자의 동의가 아니다. 다른 사람의 문제와 감정을 대상 화자에게 옮기지 않는다. 검색, 번역, 음식 추천에는 `recent_messages` 변수를 명시적으로 등록했으며 코드에서도 같은 변수로 전달한다.

대화형 명령의 맥락 건수와 원문 요약의 입력 범위는 [전체 명령어와 맥락 점검](ai-context-audit.md)에 기록했다. 영상, 댓글, 공지와 JSON 원문을 처리하는 기능은 채널 대화를 섞지 않는다.

## 변경 시 검증

저장형 프롬프트를 게시한 후 실제 게시 버전으로 코드와 문서를 함께 갱신한다. 화면에서 변수를 문장에 입력하는 것만으로는 API 변수가 등록되지 않으므로 Variables 목록에도 추가한다. 봇의 문맥 전달 경로와 출력 계약은 단위 테스트로 확인하고 원격 변수 등록과 모델 설정은 실제 API 요청으로 확인한다.

이번에 게시한 14개 프롬프트는 실제 API 요청을 모두 통과했다. 검사에는 봇 발화 참조, 검색 실행, 번역 및 허용 메뉴 선택, 요약 형식과 JSON 키 검증을 포함했다. 이는 각 샘플의 확인 결과이며 모든 입력에서 문체와 사실성을 보장하는 것은 아니다.
