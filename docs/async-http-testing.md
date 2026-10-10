# 비동기 HTTP 테스트 모킹과 배포 실패 재발 방지

## 2026-10-11 Tibo Daily log 테스트 실패

Tibo Daily log 알림을 추가한 커밋 `71770fb`의 Jenkins `Verify` 단계에서 전체 테스트 764개 중 1개가 오류로 종료됐다. 실패한 테스트는 `TiboFetcherTests.test_fetch_uses_page_and_checks_http_status`였다. `compileall`은 통과했지만 unittest가 실패해 DB 마이그레이션과 배포 단계는 실행되지 않았다.

핵심 오류는 다음과 같다.

```text
TypeError: 'coroutine' object does not support the asynchronous context manager protocol
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```

이 로그는 HTTP 요청에 대한 테스트 대역에서 발생했다. 실제 사이트 응답이나 Discord 전송 장애를 입증하는 로그가 아니다. 기존 컨테이너는 제공된 실패 로그에서 healthy로 표시됐지만, 이는 새 커밋이 배포됐다는 의미가 아니다.

### 직접 원인

실제 코드의 호출은 다음과 같다.

```python
async with session.get(url) as response:
    response.raise_for_status()
    html = await response.text()
```

`session.get()`은 호출 즉시 비동기 컨텍스트 매니저로 사용할 수 있는 요청 객체를 반환한다. HTTP 처리가 비동기라는 이유만으로 `get` 자체를 `AsyncMock`으로 만들면 안 된다.

실패한 테스트는 다음처럼 세션을 모킹했다.

```python
with patch("util.codex_resets.tibo.aiohttp.ClientSession") as client:
    session = client.return_value.__aenter__.return_value
    session.get.return_value.__aenter__.return_value = response
```

위 테스트는 세션을 명시적으로 구성하지 않았다. 자동 생성된 `__aenter__`의 반환 대역은 `AsyncMock`이었고, 그 자식인 `session.get`도 비동기 호출 대역이 됐다. 따라서 `session.get()`의 결과는 요청 컨텍스트 매니저가 아니라 코루틴이었다. `async with`가 이 코루틴에 진입하려 하면서 타입 오류가 났고, 사용되지 않은 코루틴 경고도 함께 발생했다.

### 작성 과정에서 놓친 점과 발견이 늦어진 이유

- 저장소의 `test/test_codex_resets_fetcher.py`에는 세션과 요청 객체를 `MagicMock`으로 명시하고 컨텍스트 진입만 `AsyncMock`으로 구성한 선례가 이미 있었다. 새 테스트를 작성할 때 이 호출 구조를 재사용하지 않았다.
- 응답의 `text()`를 비동기로 설정하는 데 집중하면서 세션, 요청 객체, 응답 각각의 호출 방식을 구분하지 않았다. 테스트 코드를 작성했다는 사실만으로 실행 가능성을 확인한 것으로 볼 수 없다.
- 최초 구현과 커밋에서는 기존 사용자 지시에 따라 사후 테스트를 실행하지 않았다. 이는 검증을 생략한 배경이며, 잘못된 모킹을 만든 기술적 원인과는 구분한다. 실행되지 않은 테스트의 결과는 미확인 상태였고, Jenkins가 첫 실행 검증 지점이 됐다.
- 컴파일 검사는 Python 문법 오류를 찾지만, 실행 시 반환되는 객체가 비동기 컨텍스트 매니저인지까지 확인하지 않는다. 따라서 이번 오류는 컴파일 검사만으로 발견할 수 없었다.

문서화 과정에서는 `.github/copilot-instructions.md`에 정식 단위 테스트가 없고 수동 검증에 의존한다는 오래된 설명도 발견했다. 실제 unittest 구성과 Jenkins 검증 절차에 맞게 수정했다. 이 문구가 이번 모킹 오류를 직접 유발했다는 증거는 없으며, 향후 작업자가 잘못된 검증 절차를 따르지 않도록 정리한 사항이다.

### 수정과 확인된 결과

수정 커밋 `d623f4e`에서는 세션을 명시적인 `MagicMock`으로 교체했다. HTTP 429 오류가 전달되고 오류 응답의 본문은 읽지 않는지도 같은 테스트에서 확인하도록 보강했다. 애플리케이션 HTTP 호출 코드는 변경하지 않았다.

수정 후 로컬 Python 3.11.9에서 확인한 결과는 다음과 같다.

- Tibo 관련 테스트 24개 통과
- 전체 unittest 764개 통과
- `compileall` 통과
- `git diff --check` 통과

수정 커밋은 `origin/main`에 푸시됐으며 로컬과 원격 SHA가 일치했다. 이후 사용자가 제공한 `d623f4e`의 Jenkins 로그에서 전체 764개 테스트 통과, DB 마이그레이션 완료, 컨테이너 healthy 및 최종 SUCCESS를 확인했다. 실서비스 Daily log 알림 전송은 해당 로그로 확인하지 않았다. 성공 로그에 남은 경고의 원인과 후속 개선은 [Jenkins 로그 분석](jenkins-log-analysis-2026-10-11.md)에 기록했다.

## 앞으로 사용할 모킹 기준

비동기 기능을 테스트할 때는 기능 이름보다 실제 호출 표현식을 기준으로 대역을 선택한다.

| 호출 표현식 | 대역 |
| --- | --- |
| `async with aiohttp.ClientSession()` | 세션 생성자는 `MagicMock`, `__aenter__`와 `__aexit__`는 비동기 대역 |
| `async with session.get(url)` | `session.get`은 `MagicMock`, 반환값은 비동기 컨텍스트 매니저 |
| `response.raise_for_status()` | `Mock` 또는 `MagicMock` |
| `await response.text()` 또는 `await response.json()` | `AsyncMock` |
| `await channel.send(...)` | `AsyncMock` |

요청 컨텍스트와 응답을 모두 명시적으로 설정한다. 세션의 기본 `__aenter__.return_value`를 그대로 가져와 세션으로 사용하지 않는다.

```python
from unittest.mock import AsyncMock, MagicMock, patch

response = MagicMock()
response.text = AsyncMock(return_value="<html>fixture</html>")

request = MagicMock()
request.__aenter__ = AsyncMock(return_value=response)
request.__aexit__ = AsyncMock(return_value=False)

session = MagicMock()
session.get.return_value = request

with patch("module_under_test.aiohttp.ClientSession") as client:
    client.return_value.__aenter__.return_value = session
    result = await function_under_test()
```

위 예시의 `module_under_test`와 `function_under_test`는 대상 모듈과 함수로 바꾼다. 구현에서 이름을 참조하는 모듈을 patch하고, 실제 HTTP 요청이나 운영 서비스 실행으로 단위 테스트를 대신하지 않는다.

## 작성과 검증 절차

1. 변경할 함수와 호출부의 `await`, `async with`, 일반 호출을 먼저 구분한다.
2. 같은 라이브러리를 쓰는 기존 테스트를 읽고 세션, 요청, 응답 구성을 재사용한다. aiohttp 조회 테스트의 참고 파일은 `test/test_codex_resets_fetcher.py`와 `test/test_tibo_daily_log.py`다.
3. 성공 응답뿐 아니라 HTTP 오류 전달과 오류 후 본문 미조회도 테스트한다. `RuntimeWarning`에 미대기 코루틴이 나오면 호출 방식과 대역을 먼저 대조한다.
4. 테스트 실행을 요청받았으면 Python 3.11에서 focused discovery로 실패를 재현하고 수정 후 같은 테스트를 실행한다. 이번처럼 Jenkins 전체 테스트가 실패한 경우에는 전체 discovery와 컴파일 검사도 실행한다.
5. 테스트 실행이 허용되지 않은 작업에서는 자동 실행하지 않는다. 대역의 호출 구조를 소스로 확인하고, 결과에는 테스트 작성과 실행 여부를 별도로 적는다. 테스트를 추가했다는 이유로 통과를 주장하지 않는다.
6. 커밋과 푸시 완료, Jenkins 검증 성공, 배포 성공을 서로 다른 상태로 보고한다. `Verify` 실패 시 원인을 수정하고, 배포 검증 단계를 우회하지 않는다.

검증이 요청된 경우의 실행 명령은 다음과 같다.

```bash
python -m unittest discover -s test -p "test_tibo_daily_log.py"
python -m compileall -q bot.py api cogs common func util test
python -m unittest discover -s test
```

문서화와 모킹 기준은 같은 작성 실수를 줄이기 위한 조치다. 실행을 생략한 변경의 정확성을 보장하지는 않으며, Jenkins 검증은 계속 배포 전 차단 장치로 유지한다.
