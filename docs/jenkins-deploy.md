# DiscordBot Jenkins 자동 배포 가이드

## 문서 범위

- 이 공개 레포는 DiscordBot 자체의 예시 `Jenkinsfile` 과 앱별 `scripts/jenkins_deploy.sh` 를 제공한다.
- 실제 프로덕션 Jenkins controller, Jenkins agents, n8n 런타임은 이 공개 레포 밖의 external/private 환경에서 관리된다.
- 배포 자동화를 구성할 때는 credential ID, agent label, webhook URL, compose 설정을 자신의 환경에 맞게 조정한다.

## 레포가 직접 소유하는 파일

- Jenkins 파이프라인 정의: `Jenkinsfile`
- Docker 실행 정의: `docker-compose.yml`
- 배포 스크립트: `scripts/jenkins_deploy.sh`
- 애플리케이션 이미지 정의: `Dockerfile`
- 런타임 의존성 정의: `requirements.txt`

## Docker 운영 기준

- Docker Compose project name: `bot`
- Docker service name: `discord-bot`
- 실제 컨테이너 이름: `discord-bot-shin`
- 표시용 운영 이름: `discord bot 神`

참고:
- Docker 컨테이너 이름은 공백과 특수 문자를 허용하지 않으므로 실제 `container_name` 은 `discord-bot-shin` 으로 사용한다.
- 운영 문서와 알림에는 표시용 이름 `discord bot 神` 을 함께 표기할 수 있다.

## 예시 Jenkins Credential

현재 예시 `Jenkinsfile` 은 아래 Credential ID 를 사용한다.

1. `controlcenter-github`
   - 타입: `Username with password`
   - 용도: Git 저장소 checkout
2. `discordbot-env`
   - 타입: `Secret text`
   - 값: 운영 `.env` 전체 내용
3. `discordbot-github-webhook-secret`
   - 타입: `Secret text`
   - 값: GitHub webhook shared secret
4. `discordbot-n8n-webhook-url`
   - 타입: `Secret text`
   - 값: Jenkins `post` 단계가 호출할 알림 webhook URL

- 다른 ID 를 쓰려면 자신의 Jenkins 환경에 맞게 `Jenkinsfile` 을 함께 수정한다.

## Jenkins Job 생성 예시

1. Jenkins 에서 새 `Pipeline` Job 을 만든다.
2. Pipeline 정의는 `Pipeline script from SCM` 을 선택한다.
3. Repository URL 은 `https://github.com/Me-in-U/DiscordBot.git` 로 설정한다.
4. Branch Specifier 는 `*/main` 으로 설정한다.
5. Script Path 는 `Jenkinsfile` 로 설정한다.
6. 예시 파이프라인은 `discordbot-docker` 라벨 agent 에서 실행되도록 되어 있으므로, 다른 label 을 쓰면 `Jenkinsfile` 도 같이 바꾼다.

## GitHub Webhook 설정 예시

- GitHub 저장소 Webhook URL 은 자신의 Jenkins endpoint 로 설정한다.
- 이벤트는 `Just the push event` 로 제한한다.
- Secret 은 `discordbot-github-webhook-secret` 과 같은 값을 사용한다.
- Jenkins Global GitHub 설정에서도 같은 secret 으로 서명을 검증한다.

## 배포 동작

- `main` 브랜치 push 시 Jenkins 가 자동 실행된다.
- Jenkins 는 저장소를 checkout 한 뒤 `discordbot-env` Credential 로 `.env` 를 복원한다.
- 배포 스크립트는 다음 순서로 동작한다.
  - `docker compose build discord-bot`
  - `docker compose up -d --no-build discord-bot`
  - `http://host.docker.internal:1557/health` 헬스체크 확인
- 배포 로그는 `.deploy-logs` 에 남고 Jenkins artifact 로 보관된다.

## 알림 연동

- 예시 파이프라인은 Jenkins `post` 단계에서 빌드 상태, 커밋, 링크, 로그 요약, 서비스/컨테이너 정보를 webhook 으로 전달한다.
- 알림 전송이 필요하면 자신이 운영하는 n8n, Slack, Discord, 또는 다른 webhook consumer 를 연결하면 된다.
- 현재 공개 문서에는 프로덕션 webhook URL 이나 내부 운영 경로를 적지 않는다.

## 수동 복구 명령

```bash
docker compose --env-file .env build discord-bot
docker compose --env-file .env up -d --no-build discord-bot
curl -H "Host: host.docker.internal" http://127.0.0.1:1557/health
```

## 레거시 실행 스크립트

- `_autoPullAndLaunch.py`
- `_launchBot.bat`
- `_launchBot.ps1`
- `_scheduler.bat`
- `_scheduler.ps1`

위 스크립트는 수동 실행용 레거시로만 남기고 자동배포 경로에서는 사용하지 않는다.
