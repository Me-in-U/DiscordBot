# Discord All-in-One Bot

Discord 서버 운영, AI 보조, 음악 재생, 게임/도박, 일정, 외부 알림을 한 번에 처리하는 Python 기반 Discord 봇입니다.

이 저장소는 봇 애플리케이션 코드, Docker 실행 자산, Jenkins 예시 파이프라인, DB 마이그레이션 스크립트를 함께 관리합니다. 공유 Jenkins 컨트롤러나 외부 런타임 인프라는 이 저장소 범위가 아닙니다.

## 핵심 요약

- `discord.py` 기반 slash command/package cog 구조
- OpenAI Responses API 기반 질문, 검색, 요약, 번역, 해석, 설명, 음식 추천, 공지 요약
- YouTube 영상 요약, 댓글 요약, 라이브/업로드/WebSub/커뮤니티 게시물 알림
- 음악 재생, 대기열, 반복, 셔플, 즐겨찾기, 패널 UI
- MySQL 기반 길드 설정, 도박 잔액, 예약 메시지, YouTube 구독, DDAY, 기능 상태 저장
- `aiohttp.web` 기반 상태/외부 콜백 API
- Docker Compose 배포와 Jenkins 검증/마이그레이션/배포 단계

## 기술 스택

- Runtime: Python 3.11
- Discord: `discord.py`, `discord.py[voice]`, `discord-ext-voice-recv`
- HTTP/DB: `aiohttp`, `aiomysql`
- AI: OpenAI Responses API, hosted prompt payload
- 음성/미디어: `faster-whisper`, `pyttsx3`, `yt-dlp`, `ffmpeg`
- 외부 API: YouTube Data API, Riot API, 한국은행 ECOS
- 테스트: `unittest`, `compileall`
- 배포: Docker, Docker Compose, Jenkins Pipeline

## 프로젝트 구조

```text
.
├── bot.py                    # Bot 생성, Cog 자동 로드, 메시지 캐시, startup 초기화
├── api/                      # OpenAI, Riot, ECOS API adapter
├── cogs/                     # Slash command와 background/API cog
├── common/                   # 공통 OpenAI prompt payload helper
├── func/                     # YouTube 요약/미디어 처리와 1557 감지 기능
├── util/                     # DB, guild/message/music/youtube/maplestory/loop helper
├── scripts/migrate_db.py     # MySQL schema migration entrypoint
├── test/                     # unittest 기반 회귀 테스트
├── Dockerfile*               # runtime/dependency image
├── docker-compose.yml        # local/deploy compose service
└── Jenkinsfile               # checkout, verify, migrate, deploy 예시 pipeline
```

## 아키텍처

### Entry Point

`bot.py`가 `commands.Bot`을 생성하고 `cogs/` 아래의 단일 파일 cog와 package cog를 자동으로 발견해 로드합니다. `cogs.status_api`는 필수 cog로 취급되어 로드 실패 시 startup이 중단됩니다.

`bot.py`는 다음 전역 상태도 관리합니다.

- `DISCORD_CLIENT.USER_MESSAGES`: 길드별 최근 메시지 캐시. AI 요약/번역/해석/설명 컨텍스트로 사용합니다.
- `DISCORD_CLIENT.PARTY_LIST`: `-파티`로 끝나는 Discord 카테고리를 길드별로 추적합니다.

### Cog Layout

현재 주요 기능은 package cog 형태인 `cogs/<name>/__init__.py`에 위치합니다. 복잡한 기능은 해당 cog가 command surface만 담당하고 세부 로직은 `util/`, `func/`, 하위 모듈로 분리합니다.

대표 예시는 다음과 같습니다.

- `cogs/gambling/`: 도박 명령 surface, 잔액/게임 로직은 하위 파일로 분리
- `cogs/music/`: 음악 명령 surface, queue/playback/source/view helper는 `util/music/`
- `cogs/youtube_subscriptions/`: YouTube 구독 명령 surface, 상태/알림/WebSub helper는 `util/youtube/`
- `cogs/maplestory/`: MapleStory 명령 surface, fetch/parser/sender/state는 `util/maplestory/`
- `cogs/loop/`: background task orchestration, 세부 runner는 `util/loop/`, `util/youtube/`, `util/maplestory/`

## 명령어

### 기본/관리

| 명령어 | 설명 |
| --- | --- |
| `/도움` | 카테고리별 도움말 UI |
| `/기가채드` | 기가채드 이미지 전송 |
| `/핑` | 봇 latency 확인 |
| `/clean` | 관리자 전용 최근 메시지 정리 |
| `/채널설정` | 기념일, 도박, 음악, 유튜브 채널 지정/해제 |
| `/채널설정확인` | 현재 길드의 기능별 채널 설정 확인 |

### 기념일/DDAY/일정

| 명령어 | 설명 |
| --- | --- |
| `/기념일업데이트` | 오늘 기념일/사건 공지를 수동 갱신 |
| `/dday추가` | 서버 DDAY 추가 |
| `/dday삭제` | DDAY 목록에서 선택 삭제 |
| `/dday목록` | 서버 DDAY 목록 조회 |
| `/예약 일반` | 지정 시각에 메시지 예약 |
| `/예약 반복` | 매시간/매일/매주/매달 반복 메시지 예약 |
| `/예약 리스트` | 예약 목록 조회 및 삭제 |

### AI

| 명령어/액션 | 설명 |
| --- | --- |
| `/질문` | ChatGPT 질문 |
| `/신이시여` | 텍스트와 이미지 기반 질문 |
| `/검색` | 웹 검색용 OpenAI prompt 호출 |
| `/대화요약` | 최근 채팅 요약 |
| `/번역` | 입력 텍스트 또는 최근 메시지 번역 |
| `/해석` | 입력 텍스트/이미지 또는 최근 메시지 해석 |
| `/설명` | 입력 텍스트/이미지 또는 최근 메시지 설명 |
| `/뭐먹지` | `gpt-5.4-nano`로 메뉴 하나 추천, 직전 추천 반복 방지 |
| 컨텍스트 메뉴 `메시지 번역` | 선택 메시지 번역 |
| 컨텍스트 메뉴 `메시지 해석` | 선택 메시지 해석 |
| 컨텍스트 메뉴 `메시지 설명` | 선택 메시지 설명 |

OpenAI 호출은 `api/chatGPT.py`에서 감싸며, hosted prompt payload는 `common/openai_prompt.py`의 helper로 생성합니다. OpenAI SDK 예외는 `OpenAIModelError`로 매핑해 사용자에게 안전한 오류 메시지를 보냅니다.

### 음성 대화

| 명령어 | 설명 |
| --- | --- |
| `/대화` | 음성 채널에 참여해 실시간 음성 대화 시작 |
| `/대화종료` | 음성 대화 종료 및 퇴장 |

음성 처리는 `discord-ext-voice-recv` sink, PCM buffer, silence detection, `faster-whisper` STT, `pyttsx3` TTS 경로를 사용합니다. Windows 로컬 실행에서는 `bin/` 또는 PATH의 ffmpeg를 사용합니다.

### YouTube

| 명령어/기능 | 설명 |
| --- | --- |
| `/요약` | 최근 메시지의 YouTube 링크 10개를 선택해 영상/댓글/게시물 요약 |
| 컨텍스트 메뉴 `유튜브 요약` | 선택 메시지의 YouTube 링크 요약 |
| `/유튜브구독 추가` | 채널 URL, ID, `@handle`, 검색어로 구독 추가 |
| `/유튜브구독 알림설정` | 구독별 라이브/영상/커뮤니티 알림 on/off |
| `/유튜브구독 삭제` | 구독 목록에서 선택 삭제 |
| `/유튜브구독 목록` | 서버의 YouTube 구독 목록 확인 |

YouTube 요약은 자막을 우선 사용하고, 필요 시 오디오를 MP3로 변환해 STT 후 요약합니다. 댓글은 최대 40개를 요약합니다. 커뮤니티 게시물은 direct post URL과 channel posts page를 파싱합니다.

YouTube 알림은 다음 경로를 조합합니다.

- WebSub Atom callback 수신
- YouTube Data API `videos.list`로 live/upcoming/upload/shorts 분류
- Atom feed fallback polling
- 커뮤니티 게시물 10분 polling
- WebSub 구독 12시간 주기 갱신

### MapleStory

| 명령어/기능 | 설명 |
| --- | --- |
| `/썬데이메이플` | 진행 중인 스페셜 썬데이 메이플 이벤트 이미지 조회 |
| `/메이플공지구독` | 현재 채널에 메이플스토리 공지 알림 구독/해제 |

공지 알림은 3분마다 확인합니다. 새 점검 공지는 새 메시지로 보내고, 일반 수정은 기존 메시지를 수정합니다. 연장 공지는 별도 메시지로 알리고, 점검 완료 공지가 나오면 이전 점검 관련 메시지를 정리한 뒤 완료 공지를 전송합니다.

### 게임/랭크/투표

| 명령어 | 설명 |
| --- | --- |
| `/내전` | 음성방 인원과 추가/제외 인원으로 LoL 내전 10인 팀/포지션 배정 |
| `/솔랭` | Riot ID 기반 솔로 랭크 조회 |
| `/자랭` | Riot ID 기반 자유 랭크 조회 |
| `/일일랭크` | 자정 솔랭 조회 대상 확인 |
| `/일일랭크변경` | 자정 솔랭 조회 대상 변경 |
| `/일일랭크루프` | 자정 랭크 루프 on/off |
| `/투표` | 콤마 구분 항목과 참여 인원으로 버튼 투표 진행 |

### 도박

도박 명령은 `/채널설정 기능:도박`으로 지정한 채널에서만 사용할 수 있습니다.

| 명령어 | 설명 |
| --- | --- |
| `/뿌리기` | 지정 금액을 지정 인원에게 선착순 랜덤 분배 |
| `/돈줘` | 하루 1회 10,000원 지급 |
| `/잔액` | 보유 금액 확인 |
| `/순위` | 길드 내 보유 금액 순위 |
| `/송금` | 다른 사용자에게 송금 |
| `/가위바위보` | 승리 2배, 무승부 절반, 패배 손실 |
| `/도박` | 30-70% 랜덤 확률, 성공 시 2배 |
| `/즉석복권` | 300원 복권 구매 |
| `/사다리` | 3개 사다리 중 1개 당첨 선택 |
| `/슬롯` | 3개 슬롯 일치 시 배당 |
| `/블랙잭` | Hit/Stand/Double, 블랙잭 1.5배 추가 배당 |

### 음악

음악 명령은 `/채널설정 기능:음악`으로 채널을 제한할 수 있습니다.

| 명령어 | 설명 |
| --- | --- |
| `/음악` | 재생 상태와 버튼 패널 표시 |
| `/재생` | YouTube URL 또는 검색어 재생 |
| `/일시정지` | 현재 곡 일시정지 |
| `/다시재생` | 일시정지된 곡 재개 |
| `/정지` | 재생 정지 및 음성 채널 퇴장 |
| `/스킵` | 현재 곡 건너뛰기 |
| `/대기열` | 현재 대기열 조회 |
| `/구간이동` | 재생 위치 이동 |
| `/반복` | 반복 모드 on/off |
| `/대기열삭제` | 지정 번호의 대기열 항목 삭제 |
| `/대기열비우기` | 대기열 전체 비우기 |
| `/대기열이동` | 대기열 순서 변경 |
| `/셔플` | 대기열 무작위 섞기 |

### 파티

| 명령어 | 설명 |
| --- | --- |
| `/파티` | 현재 생성된 파티 목록 조회 |
| `/파티생성` | 비공개 카테고리/텍스트/음성 채널 생성 |
| `/파티초대` | 파티와 유저를 선택해 초대 |
| `/파티참가` | 파티 참가 |
| `/파티원` | 파티 멤버 목록 조회 |
| `/파티탈퇴` | 파티 권한 해제 |
| `/파티해제` | 파티 삭제 |

### 경제 지표

| 명령어 | 설명 |
| --- | --- |
| `/환율` | 한국은행 ECOS 기준 최신 환율과 기본 30일 그래프, 최대 365일 |
| `/외환보유액` | 한국은행 ECOS 기준 최신 외환보유액과 기본 12개월 그래프, 최대 60개월 |

## 메시지 listener 기능

- 단일 커스텀 이모지 입력 시 원본 크기 이미지 출력
- 일반 메시지를 `USER_MESSAGES`에 캐시해 AI 컨텍스트로 사용
- 메시지 내 YouTube 링크 감지 후 요약 UI 제공
- 특정 채널의 `1557` 감지 및 주간 리포트 집계

## 백그라운드 작업

| 주기 | 작업 |
| --- | --- |
| 60초 | Discord presence 갱신 |
| 매일 00:00 KST | 최근 메시지 재로딩, 기념일/DDAY/썬데이메이플 refresh |
| 매일 00:01 KST | 주간 1557 리포트 조건 확인 |
| 60초 | YouTube WebSub/Atom feed 후보 확인 |
| 10분 | YouTube 커뮤니티 게시물 polling |
| 3분 | MapleStory 공지 polling |
| 12시간 | YouTube WebSub 구독 갱신 |
| 30초 | 예약 메시지 발송 확인 |

## HTTP API

`cogs/status_api`가 `aiohttp.web` 서버를 실행합니다. 기본 포트는 `1557`이며 `API_PORT`로 변경할 수 있습니다.

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/` | 간단한 상태 문자열 |
| `GET` | `/health` | bot readiness, latency, uptime, guild/user/message count, schema version |
| `POST` | `/celebration/update` | 기념일 공지 수동 갱신 |
| `GET` | `/youtube/websub` | YouTube WebSub challenge 검증 |
| `POST` | `/youtube/websub` | YouTube Atom notification 수신 |

`/celebration/update`는 `X-API-Key: <CELEBRATION_UPDATE_API_KEY>` 헤더가 필요합니다. JSON body 또는 query string으로 `guild_id`를 넘기면 특정 길드만 갱신하고, 생략하면 기념일 채널이 설정된 모든 길드를 대상으로 합니다.

WebSub callback은 `YOUTUBE_WEBSUB_VERIFY_TOKEN`을 query의 `token` 또는 `hub.verify_token`으로 검증합니다. 배포 런타임에서는 이 값이 필수입니다.

## 데이터 저장소

MySQL을 사용합니다. 앱은 시작 시 schema version만 확인하고, 실제 DDL 적용은 `scripts/migrate_db.py`에서 수행합니다.

주요 테이블:

- `guild`, `discord_user`
- `channel_settings`
- `setting_data`
- `gambling_balances`
- `scheduled_messages`
- `panel_messages`
- `music_favorites`
- `counter_1557`
- `youtube_subscriptions`
- `dday_events`
- `special_days`
- `schema_migrations`

마이그레이션 실행:

```bash
python -m scripts.migrate_db
```

## 환경 변수

`.env`는 로컬 실행용, `.env.deploy`는 배포 실행용입니다. 둘 다 secret 파일이며 Git에 포함하지 않습니다.
처음 설정할 때는 `.env.example`을 복사해 실제 값을 채웁니다.

필수/주요 값:

```dotenv
DISCORD_TOKEN=...
OPENAI_KEY=...
GOOGLE_API_KEY=...
RIOT_KEY=...
ECOS_API_KEY=...

SONPANNO_GUILD_ID=...
SSAFY_GUILD_ID=...

DB_HOST=localhost:3306
DB_DATABASE=...
DB_USERNAME=...
DB_PASSWORD=...

API_PORT=1557
CELEBRATION_UPDATE_API_KEY=...

YOUTUBE_WEBSUB_CALLBACK_URL=https://example.com/youtube/websub
YOUTUBE_WEBSUB_VERIFY_TOKEN=...
```

Docker 배포에서 MySQL이 호스트 loopback에 바인딩되어 있으면 `DB_HOST=host.docker.internal:3306`처럼 Docker host gateway를 가리켜야 합니다.

## 로컬 실행

Python 3.11 기준으로 실행합니다.

```bash
pip install -r requirements.txt
python -m scripts.migrate_db
python bot.py
```

Windows에서는 아래 스크립트도 사용할 수 있습니다.

```powershell
.\_launchBot.ps1
```

또는:

```bat
_launchBot.bat
```

`pip_install.txt`는 legacy/manual 설치 메모이며, 기본 dependency entrypoint는 `requirements.txt`입니다.

## Docker 실행

```bash
docker build -f Dockerfile.deps -t bot-discord-bot-deps:latest .
docker compose --env-file .env up -d --build
docker compose --env-file .env ps
```

Compose는 `127.0.0.1:1557:1557`로 Status API를 노출하고, 컨테이너에서 호스트 DB 접근을 위해 `host.docker.internal` host gateway를 추가합니다.

## 검증

코드 변경 후 기본 검증:

```bash
python -m compileall -q bot.py api cogs common func util test
python -m unittest discover -s test
```

`test/`는 importable package가 아니므로 focused test도 discovery mode로 실행합니다.

```bash
python -m unittest discover -s test -p "test_scheduler.py"
```

Docker/Jenkins와 맞춰 DB migration까지 확인할 때:

```bash
python -m scripts.migrate_db
python -m compileall -q bot.py api cogs common func util test
python -m unittest discover -s test
```

## 배포

`Jenkinsfile`은 예시 pipeline으로 다음 단계를 수행합니다.

1. Checkout
2. `.env.deploy` 복원 및 Docker 환경 확인
3. dependency image 기반 `compileall`/`unittest` 검증
4. DB migration 실행
5. `scripts/jenkins_deploy.sh`로 Docker Compose 배포
6. 배포 로그와 상태 메타데이터 보관

Jenkins 배포는 Secret text credential `discordbot-env`에서 `.env.deploy` 내용을 복원하도록 구성되어 있습니다. 배포 환경 변수를 변경했다면 저장소 diff만으로는 배포 값이 바뀌지 않으므로 Jenkins credential의 Secret text payload도 같은 내용으로 갱신해야 합니다.

배포 스크립트 직접 실행 예:

```bash
ENV_FILE=.env.deploy ./scripts/jenkins_deploy.sh auto
ENV_FILE=.env.deploy ./scripts/jenkins_deploy.sh restart
ENV_FILE=.env.deploy ./scripts/jenkins_deploy.sh force
```

## 개발 규칙

- I/O, HTTP, DB 작업은 async 기반으로 작성합니다.
- HTTP client는 `aiohttp`를 우선 사용합니다.
- 길드별 채널 설정은 `util/guild/channel_settings.py` helper를 사용합니다.
- 기능 상태는 `setting_data` 또는 전용 테이블에 저장하고 로컬 JSON 파일을 새로 만들지 않습니다.
- 경로 처리는 `pathlib` 또는 `bot.py`의 `BASE_DIR` 기반으로 작성합니다.
- 사용자에게 보이는 실패는 Discord 메시지로 안전하게 안내하고, 내부 예외는 traceback과 함께 로그에 남깁니다.
- `.env`, `.env.deploy`, 내부 URL, 로컬 절대 경로, private 운영 세부사항은 커밋하지 않습니다.
