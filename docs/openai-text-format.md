# OpenAI Text format 적용 기준

2026-10-11 기준으로 OpenAI 호출부와 응답을 사용하는 코드를 확인했다. 출력이 JSON이라는 지시만 쓰는 것보다 `json_schema`와 `strict: true`로 필드와 타입을 고정하는 방식이 구조화된 데이터 처리에 적합하다. `json_object`는 유효한 JSON만 보장하므로 이 기능들에서는 사용하지 않는다.

| 기능 | 형식 | 결정과 이유 |
| --- | --- | --- |
| Codex 리셋 게시물 번역 | JSON Schema | `codex_reset_translation` v2에서 `translation` 문자열 또는 null을 반환한다. null은 번역 실패로 처리하며 Discord에 전송하지 않는다. |
| Tibo Daily log 요약 | JSON Schema | `tibo_daily_log_summary` v1에서 `announcements` 배열과 각 항목의 `title`, `summary` 문자열을 반환한다. |
| 1557 이미지 분석 | JSON Schema | 기존 `find1557_from_image` v9의 strict 스키마를 유지한다. `exist`, `imageToText`, `reason`이 이미 정의되어 있다. |
| 일반 번역, 해석, 설명 | text | 결과 문장을 그대로 사용자에게 표시하므로 JSON 변환이 필요하지 않다. |
| 질문, 검색, 대화 및 YouTube 요약, 공지 요약 | text | 자연어 또는 Markdown을 바로 표시한다. |
| 음식 추천 | text | 단일 메뉴를 표시하고 기존 텍스트 정규화로 처리한다. JSON 도입으로 얻는 이점이 작다. |

스키마와 번역 지침은 프롬프트 에디터에서 관리한다. 코드는 게시된 프롬프트 ID와 버전을 고정해 호출한다. 응답 형식이 달라지는 새 버전을 게시할 때는 파서와 회귀 테스트도 함께 수정해야 한다. 원문은 저장 프롬프트 변수에만 의존하지 않고 별도의 사용자 입력으로 전달한다.

JSON Schema는 한국어 번역의 정확성, 사실 보존, 발표의 개수와 순서까지 보장하지 않는다. 한국어 여부, 비어 있는 문자열, 발표 개수는 애플리케이션에서 계속 검사한다. 거부 응답, 출력 중단, JSON 파싱 실패도 정상 번역으로 취급하지 않으며 전송 상태를 저장하지 않아 다음 확인 때 재시도한다.

기존 Discord 메시지의 표시 형식은 바뀌지 않는다. JSON은 코드 내부에서만 읽고 번역문과 요약을 임베드에 넣는다.

근거: [OpenAI Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## 실제 페이지 확인 중 발견한 파서 오류

Daily log 페이지를 직접 읽는 과정에서 `Unknown Tibo log entry type` 오류가 발생했다. 기존 파서는 모든 발표에 `challenge-entry--reset` 같은 유형 클래스가 있다고 가정했지만, 실제 일반 리셋과 적립형 리셋 발표는 `challenge-entry` 클래스만 사용했다. 이 경우 유형은 발표 앞의 `challenge-badge`에 각각 `Reset`, `Banked reset`으로 표시되어 있었다.

유형 클래스가 없으면 직전 배지의 알려진 유형을 사용하도록 수정했다. 명시적인 알 수 없는 유형이나 배지까지 없는 발표는 계속 오류로 처리한다. 일반 리셋과 적립형 리셋의 배지 기반 분류를 회귀 테스트에 추가했다. 기존 테스트 fixture에는 유형 클래스가 있어 이 차이가 드러나지 않았으며, 단위 테스트 통과만으로 실제 페이지 호환성을 판단할 수 없었다.

## 2026-10-11 검증 결과

- 최종 전체 unittest 774개 통과, Python 컴파일 검사와 변경 파일 형식 검사 통과.
- 실제 Daily log 페이지의 발표 14개를 파싱했고, 일반 리셋 2개와 적립형 리셋 1개를 구분했다.
- 실제 OpenAI API에서 리셋 번역 v2와 Daily log 요약 v1이 모두 `completed`, `json_schema`, `strict: true`로 응답했다.
- 리셋 번역은 “리셋 적용이 완료됐습니다. 전체에 반영됐습니다.”였으며 원문 URL이 유지됐다.
- 실제 Day 05 발표 3개가 모두 한국어 제목과 요약으로 반환됐고, 하나의 임베드를 생성했다.
- 실제 API 확인 과정에서는 Discord 메시지를 전송하지 않았다. Jenkins 실행과 서버 배포 성공은 이 로컬 검증의 확인 범위에 포함되지 않는다.
