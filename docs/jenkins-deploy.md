# DiscordBot Jenkins 자동 배포 가이드

## 구성 개요

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
- 런타임 영속 데이터 경로: `E:\docker_data\discord-data`

참고:
- Docker 컨테이너 이름은 공백과 특수 문자를 허용하지 않으므로 실제 `container_name`은 `discord-bot-shin`으로 사용한다.
- 운영 문서와 알림에는 표시용 이름 `discord bot 神`을 함께 표기한다.

## 필수 Jenkins Credential

다음 Credential 을 Jenkins 전역 영역에 추가한다.

1. `controlcenter-github`
   - 타입: `Username with password`
   - 용도: GitHub 저장소 checkout
2. `discordbot-env`
   - 타입: `Secret text`
   - 값: 운영 `.env` 전체 내용
3. `discordbot-github-webhook-secret`
   - 타입: `Secret text`
   - 값: GitHub webhook shared secret
4. `discordbot-n8n-webhook-url`
   - 타입: `Secret text`
   - 값: `https://your-n8n.example/webhook/replace-me`

## Jenkins Job 생성

1. Jenkins 에서 새 `Pipeline` Job `DiscordBot-Deploy` 를 만든다.
2. Pipeline 정의는 `Pipeline script from SCM` 을 선택한다.
3. Repository URL 은 `https://github.com/Me-in-U/DiscordBot.git` 로 설정한다.
4. Branch Specifier 는 `*/main` 으로 설정한다.
5. Script Path 는 `Jenkinsfile` 로 설정한다.
6. 빌드는 `controlcenter-docker` 라벨 agent 에서만 실행되도록 유지한다.

## GitHub Webhook 설정

- GitHub 저장소 Webhook URL: `https://jenkins.ios.kr/github-webhook/`
- 이벤트: `Just the push event`
- Secret: `discordbot-github-webhook-secret` 과 동일한 값
- Jenkins Global GitHub 설정에서도 같은 secret 을 사용해 서명을 검증한다.

## 배포 동작

- `main` 브랜치 push 시 Jenkins 가 자동 실행된다.
- Jenkins 는 저장소를 checkout 한 뒤 `discordbot-env` Credential 로 `.env` 를 복원한다.
- 배포 스크립트는 다음 순서로 동작한다.
  - `docker compose build discord-bot`
  - `docker compose up -d --no-build discord-bot`
  - `http://host.docker.internal:1557/health` 헬스체크 확인
- 배포 로그는 `.deploy-logs` 에 남고 Jenkins artifact 로 보관된다.

## n8n / Discord 알림

- n8n 워크플로우 `Discord Jenkins` 는 production webhook `https://your-n8n.example/webhook/replace-me` 을 사용한다.
- Jenkins `post` 단계는 빌드 상태, 커밋, 링크, 로그 요약, 서비스/컨테이너 정보를 n8n 으로 전달한다.
- n8n 은 기존 ControlCenter Jenkins Discord 채널로 같은 형식의 운영 알림을 보낸다.

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

위 스크립트는 수동 실행용 레거시로만 남기고, 자동배포 경로에서는 사용하지 않는다.
