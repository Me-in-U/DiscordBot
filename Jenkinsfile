import groovy.json.JsonOutput

def tryReadCommand(scriptContext, String command, String fallback = '') {
  try {
    return scriptContext.sh(script: command, returnStdout: true).trim()
  } catch (Exception ignored) {
    return fallback
  }
}

def notifyN8n(scriptContext, String status) {
  try {
    def commitSha = tryReadCommand(scriptContext, "git rev-parse HEAD", (scriptContext.env.GIT_COMMIT ?: '').trim())
    def commitMessage = tryReadCommand(scriptContext, "git log -1 --pretty=%s", '')
    def deployMetadataRaw = tryReadCommand(scriptContext, '''
      set +e
      if [ -f .deploy-logs/jenkins-deploy.latest.meta ]; then
        cat .deploy-logs/jenkins-deploy.latest.meta
      fi
    ''', '')
    def deployMetadata = [:]
    deployMetadataRaw
      .split('\n')
      .findAll { it?.contains('=') }
      .each { line ->
        def separatorIndex = line.indexOf('=')
        def key = line.substring(0, separatorIndex).trim()
        def value = line.substring(separatorIndex + 1).trim()
        deployMetadata[key] = value
      }
    def logExcerpt = tryReadCommand(scriptContext, '''
      set +e
      if [ -f .deploy-logs/jenkins-deploy.latest.log ]; then
        tail -n 25 .deploy-logs/jenkins-deploy.latest.log
      else
        echo "jenkins-deploy.latest.log not found."
      fi
    ''', '')
    if (logExcerpt.length() > 1500) {
      logExcerpt = logExcerpt[-1500..-1]
    }

    def payload = [
      status          : status,
      jobName         : scriptContext.env.JOB_NAME,
      buildNumber     : scriptContext.env.BUILD_NUMBER as Integer,
      buildUrl        : scriptContext.env.BUILD_URL,
      consoleUrl      : "${scriptContext.env.BUILD_URL}console",
      branch          : (scriptContext.env.CHANGE_BRANCH ?: scriptContext.env.BRANCH_NAME ?: 'main'),
      commit          : commitSha,
      commitMessage   : commitMessage,
      deployMode      : scriptContext.params.DEPLOY_MODE,
      service         : (deployMetadata['service'] ?: 'discord-bot'),
      container       : (deployMetadata['container'] ?: 'discord-bot-shin'),
      displayContainer: (deployMetadata['displayContainer'] ?: 'discord bot 神'),
      durationMillis  : scriptContext.currentBuild.duration ?: 0L,
      finishedAt      : new Date().format("yyyy-MM-dd'T'HH:mm:ssXXX", TimeZone.getTimeZone('Asia/Seoul')),
      logExcerpt      : logExcerpt
    ]

    scriptContext.withCredentials([
      string(credentialsId: 'discordbot-n8n-webhook-url', variable: 'N8N_WEBHOOK_URL')
    ]) {
      scriptContext.writeFile file: '.n8n-build-notify.json', text: JsonOutput.toJson(payload)
      scriptContext.sh '''
        set +e
        curl -fsS \
          -X POST \
          -H "Content-Type: application/json" \
          --data @.n8n-build-notify.json \
          "${N8N_WEBHOOK_URL}" >/tmp/n8n-notify.out 2>/tmp/n8n-notify.err
        notify_exit=$?
        if [ "$notify_exit" -ne 0 ]; then
          echo "[WARN] n8n build notification failed."
          cat /tmp/n8n-notify.err || true
        fi
        rm -f .n8n-build-notify.json /tmp/n8n-notify.out /tmp/n8n-notify.err
        exit 0
      '''
    }
  } catch (Exception ex) {
    scriptContext.echo("[WARN] n8n build notification skipped: ${ex.message}")
  }
}

pipeline {
  agent {
    label 'discordbot-docker'
  }

  options {
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
    skipDefaultCheckout(true)
    timestamps()
  }

  triggers {
    githubPush()
  }

  parameters {
    choice(
      name: 'DEPLOY_MODE',
      choices: ['auto', 'force', 'restart'],
      description: '배포 실행 모드를 선택합니다.'
    )
  }

  environment {
    REPOSITORY_URL = 'https://github.com/Me-in-U/DiscordBot.git'
    REPOSITORY_BRANCH = '*/main'
    DOCKER_BUILDKIT = '1'
    COMPOSE_DOCKER_CLI_BUILD = '1'
    COMPOSE_FILE = 'docker-compose.yml'
    ENV_FILE = '.env'
    HEALTHCHECK_URL = 'http://host.docker.internal:1557/health'
    HEALTHCHECK_HOST_HEADER = 'host.docker.internal'
    ENV_CREDENTIAL_ID = 'discordbot-env'
  }

  stages {
    stage('Checkout') {
      steps {
        deleteDir()
        checkout([
          $class: 'GitSCM',
          branches: [[name: env.REPOSITORY_BRANCH]],
          doGenerateSubmoduleConfigurations: false,
          extensions: [
            [$class: 'CloneOption', depth: 20, noTags: true, shallow: true, timeout: 20]
          ],
          userRemoteConfigs: [[
            credentialsId: 'controlcenter-github',
            url: env.REPOSITORY_URL
          ]]
        ])
      }
    }

    stage('Validate Environment') {
      steps {
        withCredentials([
          string(credentialsId: env.ENV_CREDENTIAL_ID, variable: 'BOT_ENV_CONTENT')
        ]) {
          writeFile file: env.ENV_FILE, text: BOT_ENV_CONTENT
          sh '''
            set -e
            test -f "${ENV_FILE}"
            if [ ! -S /var/run/docker.sock ]; then
              echo "[ERROR] /var/run/docker.sock is not mounted on this Jenkins node."
              exit 1
            fi
            if ! command -v docker >/dev/null 2>&1; then
              echo "[ERROR] docker CLI is not installed on this Jenkins node."
              exit 1
            fi
            docker --version
            docker compose version
            docker info >/dev/null
            chmod +x scripts/jenkins_deploy.sh
          '''
        }
      }
    }

    stage('Deploy') {
      steps {
        sh '''
          set -e
          COMPOSE_FILE="${COMPOSE_FILE}" \
          ENV_FILE="${ENV_FILE}" \
          HEALTHCHECK_URL="${HEALTHCHECK_URL}" \
          HEALTHCHECK_HOST_HEADER="${HEALTHCHECK_HOST_HEADER}" \
          ./scripts/jenkins_deploy.sh "${DEPLOY_MODE}"
        '''
      }
    }
  }

  post {
    success {
      script {
        notifyN8n(this, 'SUCCESS')
      }
    }
    failure {
      script {
        notifyN8n(this, 'FAILURE')
      }
    }
    unstable {
      script {
        notifyN8n(this, 'UNSTABLE')
      }
    }
    aborted {
      script {
        notifyN8n(this, 'ABORTED')
      }
    }
    always {
      archiveArtifacts artifacts: '.deploy-logs/**/*.log,.deploy-logs/**/*.meta', allowEmptyArchive: true
      sh '''
        set +e
        if command -v docker >/dev/null 2>&1; then
          docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps
        fi
      '''
    }
  }
}
