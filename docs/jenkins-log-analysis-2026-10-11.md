# 2026-10-11 Jenkins 성공 로그의 오류와 경고 분석

## 확인한 결과와 범위

사용자가 제공한 커밋 `d623f4e`의 Jenkins 로그는 최종 `Finished: SUCCESS`로 끝났다. `Verify`에서 unittest 764개가 통과했고 DB 마이그레이션은 version 1로 완료됐다. 배포 후 네 번째 health 확인에서 성공했으며 컨테이너도 healthy로 표시됐다. 이는 해당 실행의 결과이며 현재 서버를 다시 조회한 기록은 아니다.

성공 로그 안의 예외를 모두 운영 장애로 처리하면 테스트의 의도적인 실패 경로와 실제 개선할 문제를 혼동하게 된다. 로그에 나온 항목을 테스트 코드, 마이그레이션 쿼리, 배포 스크립트와 대조해 다음과 같이 분류했다.

| 로그 항목 | 확인한 원인 | 개선 또는 처리 |
| --- | --- | --- |
| 공지 요약 `RuntimeError: offline` | `test_summary_uses_lostark_prompt_and_completed_fallback`의 `unavailable()`이 의도적으로 예외를 발생시켰다. 폴백 결과는 assertion을 통과했다. | 해당 테스트에서 `assertLogs`로 예외 기록을 캡처하고 확인한다. 공유 요약 함수의 경고도 실제 `source_name`을 사용해 로아 실패가 메이플 실패로 표시되지 않게 했다. |
| `FakeOpusError`, `Voice packet dropped` | 손상된 음성 패킷을 버리는 테스트가 가짜 디코딩 예외를 발생시켰다. | 경고를 `assertLogs`로 확인하고 기존 패킷 폐기와 오류 카운터 assertion을 유지한다. |
| `receiver failed` | 음성 수신이 예기치 않게 종료됐을 때 연결을 해제하는 테스트의 주입된 예외다. | ERROR 로그를 캡처하고 원인 예외 및 연결 해제를 확인한다. |
| `voice connection failed` | 음성 연결 실패 시 사용자 안내와 상태 정리를 확인하는 테스트의 주입된 예외다. | ERROR 로그를 캡처하고 원인 예외 및 기존 상태 정리 assertion을 유지한다. |
| `Table '...' already exists` | 재실행 가능한 `CREATE TABLE IF NOT EXISTS`가 기존 테이블에 대해 내보낸 서버 경고다. 이후 마이그레이션은 완료됐다. | 테이블 생성 구간에서만 `aiomysql.Warning`의 해당 메시지를 제한적으로 필터링한다. 다른 SQL 경고와 예외는 유지한다. |
| `VALUES function is deprecated` | schema version UPSERT의 `version = VALUES(version)`에서 발생했다. | 동일한 version 값을 UPDATE에도 `%s`로 바인딩해 폐기 예정 함수를 제거한다. 원자적인 UPSERT는 유지한다. |
| 부팅 중 `curl: (52) Empty reply from server` 3회 | 컨테이너 교체 직후 health 요청이 응답을 받지 못했고 다음 재시도에서 성공했다. 정확한 서버 내부 상태는 이 로그만으로 확정할 수 없다. | 대기 중에는 INFO 진행 메시지를 남기고, 재시도가 모두 실패하면 마지막 curl 오류를 ERROR로 출력한다. 연결 제한 5초와 요청 제한 10초도 지정한다. |
| 검증과 배포의 의존성 이미지 태그 불일치 | Jenkins Verify와 Migrate는 `requirements.txt`와 `Dockerfile.deps`를 함께 해시했지만 배포 스크립트는 requirements만 해시했다. | 배포 스크립트의 기본 캐시 키를 Jenkins와 같은 두 파일의 해시로 통일한다. |
| Docker blkio throttle 미지원 경고 | `docker info`가 호스트의 해당 기능 미지원을 보고한 것이다. 이 로그에서 배포 실패나 봇 기능 장애는 확인되지 않았다. | 봇 코드 변경으로 해결할 항목이 아니다. 자원 제한을 운영 요구로 사용할 때 호스트와 Docker 환경에서 확인한다. |
| cgroup v1 폐기 예정 경고 | Docker가 호스트 실행 환경에 대한 호환성 경고를 출력한 것이다. | 공유 Docker 호스트 관리 범위에서 cgroup v2 전환을 검토한다. 이 저장소에서 호스트 설정을 변경하거나 경고를 전역으로 숨기지 않는다. |

MySQL의 `VALUES()` 사용 폐기 예정은 [MySQL 8.4 공식 UPSERT 문서](https://dev.mysql.com/doc/refman/8.4/en/insert-on-duplicate.html)에서도 설명한다. 이번 수정은 서버 버전에 따라 지원 여부가 달라질 수 있는 새 행 별칭 문법 대신 기존 파라미터 바인딩을 사용한다.

## 실제로 드러난 구조적 문제

테스트 예외들은 오류 처리 동작을 확인하는 과정이었다. 문제가 된 점은 테스트에서 예상 로그를 캡처하지 않아 빌드 로그에 운영 장애처럼 출력된 것이다. `assertLogs`는 로그를 무조건 없애는 방식이 아니라 기대한 로그가 발생했는지도 검증한다. 애플리케이션의 운영 로깅 수준과 traceback은 유지한다.

의존성 이미지 캐시 키 불일치는 별개의 실제 문제다. 같은 커밋에서도 검증에 사용한 환경과 배포에 사용한 환경이 달라질 수 있었고, `Dockerfile.deps`만 바뀌면 배포 단계가 예전 캐시를 재사용할 수 있었다. 이번 로그에는 서로 다른 태그가 선택됐다는 증거가 있지만, 실제 설치 패키지가 달랐거나 이로 인해 장애가 발생했다는 증거까지 있는 것은 아니다.

DB 테이블 존재 경고와 부팅 중 health 실패는 재실행 및 준비 대기 과정에서 예상할 수 있는 신호다. 경고를 전역으로 숨기거나 health 실패를 성공으로 취급하지 않고, 예상된 범위만 조용하게 처리한다. 마이그레이션 실패와 최종 health 실패는 계속 배포를 중단한다.

## 재발 방지 기준과 추가한 테스트

- 의도적으로 오류를 만드는 테스트는 해당 logger의 `assertLogs` 안에서 호출하고, 원인 예외 또는 이벤트 문구와 실제 폴백, 연결 해제, 상태 정리 결과를 함께 확인한다. 운영 logger를 전역 비활성화하지 않는다.
- 공유 공지 처리 함수는 고정된 게임 이름 대신 공지의 `source_name`을 로깅한다.
- 검증, 마이그레이션, 배포의 기본 의존성 이미지 캐시 키에는 `requirements.txt`와 `Dockerfile.deps`가 모두 들어가야 한다. `DEPS_IMAGE`를 수동 지정할 경우에도 검증 환경과의 일치를 운영자가 확인해야 한다.
- SQL 경고 필터는 정확한 경고 종류, 메시지, 발생 모듈과 실행 구간을 제한한다. 다른 경고가 보존되고 필터가 실행 구간 밖으로 남지 않는지도 테스트한다.
- schema version UPSERT는 deprecated `VALUES(version)` 없이 삽입과 갱신 양쪽에 같은 version을 바인딩한다.
- health 준비 대기는 INFO로 표시하고, 최대 시도 횟수를 소진하면 마지막 실패 이유와 함께 비정상 종료한다. 성공하기 전에는 배포 성공 메시지를 출력하지 않는다.

`test/test_project_analysis_followups.py`에 DB 경고 필터 범위, 필터 복원, schema version 바인딩 테스트를 추가했다. `test/test_jenkins_deploy_script.py`에는 Docker와 curl을 대역으로 구성해 Dockerfile 변경 시 이미지 태그가 달라지는지, 최종 health 실패 시 오류 출력과 비정상 종료가 유지되는지 확인하는 테스트를 추가했다. Bash 실행 테스트는 POSIX Bash와 Windows Git Bash를 지원하며 둘 다 없으면 건너뛴다. Windows의 기본 인코딩과 줄바꿈에 의존하지 않도록 스크립트 fixture는 UTF-8과 LF로 생성하고, Bash 실행 중 테스트 대역의 PATH를 가장 먼저 지정한다.

후속 검증 요청에 따라 로컬 Python 3.11.9에서 관련 테스트 68개와 전체 unittest 767개가 통과했다. 전체 실행에서는 Bash 테스트도 건너뛰지 않고 실행됐다. `compileall`과 `git diff --check`도 통과했다. Docker와 curl은 테스트 대역으로 실행했고 운영 DB 마이그레이션과 실서버 배포는 수행하지 않았다. 위의 Jenkins 764개 통과 및 배포 성공은 수정 전 커밋 `d623f4e`의 제공된 로그에서 확인한 결과이며, 이번 후속 수정의 Jenkins 결과와는 구분한다.
