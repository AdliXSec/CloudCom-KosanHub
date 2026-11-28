// KosanHub (K12) - CI/CD Jenkins, agent WINDOWS (Docker Desktop).
// Checkout -> Test -> Build Image -> Push Image -> Deploy -> Smoke Test
//
// Credential di Jenkins (Manage Jenkins > Credentials), TIDAK ada rahasia di file ini:
//   dockerhub-credentials : Username with password (username Docker Hub + personal access token)
//   kosanhub-env          : Secret file (isi = salinan .env produksi, lihat .env.example)
//
// Catatan Windows:
//   - Perintah docker memakai `bat`; setiap baris diakhiri `|| exit /b 1` supaya stage gagal bila perintah gagal.
//   - Smoke Test memakai `powershell` (pengganti bash + curl + jq).
//   - Jika Jenkins jalan sebagai Windows Service, set "Log On" service ke akun Windows yang
//     menjalankan Docker Desktop, agar tidak muncul named pipe error.

pipeline {
    agent any

    options {
        // Checkout hanya di stage 'Checkout' (di dalam node), jadi kalau gagal,
        // blok post tetap punya workspace dan tidak error "hudson.FilePath is missing".
        skipDefaultCheckout()
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        IMAGE                = 'attagetto/kosanhub'
        COMPOSE_PROJECT_NAME = 'kosanhub'
        // Variabel environment menang atas isi --env-file, jadi compose memakai tag build ini.
        APP_IMAGE            = "attagetto/kosanhub:${env.BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                script { env.FAILED_STAGE = env.STAGE_NAME }
                checkout scm
                bat 'git log -1 --oneline'
            }
        }

        // pytest dijalankan di dalam Dockerfile (stage "test"). Test gagal => build gagal
        // => pipeline berhenti dan container yang sedang jalan tidak disentuh.
        stage('Test') {
            steps {
                script { env.FAILED_STAGE = env.STAGE_NAME }
                bat 'docker build --target test -t kosanhub-test:%BUILD_NUMBER% . || exit /b 1'
            }
        }

        // Layer stage test sudah di-cache, jadi hanya merakit stage production.
        stage('Build Image') {
            steps {
                script { env.FAILED_STAGE = env.STAGE_NAME }
                bat 'docker build --target production -t "%IMAGE%:%BUILD_NUMBER%" -t "%IMAGE%:latest" . || exit /b 1'
            }
        }

        stage('Push Image') {
            steps {
                script {
                    env.FAILED_STAGE = env.STAGE_NAME
                    withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials',
                                                      usernameVariable: 'DH_USER',
                                                      passwordVariable: 'DH_TOKEN')]) {
                        try {
                            // Tanpa spasi sebelum "|", supaya token tidak ikut spasi di belakangnya.
                            bat '''
                                echo %DH_TOKEN%| docker login -u %DH_USER% --password-stdin || exit /b 1
                                docker push "%IMAGE%:%BUILD_NUMBER%" || exit /b 1
                                docker push "%IMAGE%:latest" || exit /b 1
                            '''
                        } finally {
                            bat 'docker logout >nul 2>&1 || exit /b 0'
                        }
                    }
                }
            }
        }

        // Deploy dari image yang baru di-push (bukan build lokal). Volume data TIDAK dihapus.
        stage('Deploy') {
            steps {
                script { env.FAILED_STAGE = env.STAGE_NAME }
                withCredentials([file(credentialsId: 'kosanhub-env', variable: 'ENV_FILE')]) {
                    bat '''
                        docker compose --env-file "%ENV_FILE%" config -q || exit /b 1
                        docker compose --env-file "%ENV_FILE%" pull || exit /b 1
                        docker compose --env-file "%ENV_FILE%" up -d --remove-orphans --wait --wait-timeout 180 || exit /b 1
                        docker compose --env-file "%ENV_FILE%" ps
                    '''
                }
            }
        }

        // 1) /health harus 200  2) API menerima login admin
        // 3) K12: picu job tagihan, lalu pastikan container worker menyelesaikannya.
        stage('Smoke Test') {
            steps {
                script { env.FAILED_STAGE = env.STAGE_NAME }
                withCredentials([file(credentialsId: 'kosanhub-env', variable: 'ENV_FILE')]) {
                    powershell '''
                        $ErrorActionPreference = 'Stop'

                        # Ambil login admin dari secret file; tidak pernah di-echo.
                        function Get-EnvValue([string]$Name) {
                            $line = Get-Content -LiteralPath $env:ENV_FILE |
                                Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
                            if (-not $line) { return '' }
                            return ($line.Substring($Name.Length + 1)).Trim().Trim('"')
                        }
                        $email = Get-EnvValue 'ADMIN_EMAIL'
                        $pass  = Get-EnvValue 'ADMIN_PASSWORD'
                        $port  = Get-EnvValue 'APP_PORT'
                        if (-not $port) { $port = '8000' }
                        if (-not $email -or -not $pass) {
                            Write-Host 'ADMIN_EMAIL/ADMIN_PASSWORD kosong di kosanhub-env'; exit 1
                        }
                        $base  = "http://localhost:$port"
                        $token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${email}:${pass}"))
                        $auth  = @{ Authorization = "Basic $token" }

                        function Get-StatusCode([string]$Uri, [hashtable]$Headers = @{}) {
                            try {
                                return [int](Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 10).StatusCode
                            } catch {
                                if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
                                return 0
                            }
                        }

                        Write-Host '== 1. /health'
                        $code = 0
                        for ($i = 1; $i -le 30; $i++) {
                            $code = Get-StatusCode "$base/health"
                            if ($code -eq 200) { break }
                            Start-Sleep -Seconds 1
                        }
                        if ($code -ne 200) { Write-Host "/health = $code"; exit 1 }
                        Write-Host 'OK (200)'

                        Write-Host '== 2. API + auth'
                        $code = Get-StatusCode "$base/api/jobs" $auth
                        if ($code -ne 200) { Write-Host "GET /api/jobs = $code (login admin gagal?)"; exit 1 }
                        Write-Host 'OK (200)'

                        Write-Host '== 3. Job tagihan diproses worker'
                        $job = Invoke-RestMethod -Method Post -Uri "$base/api/jobs/generate-bills" `
                            -Headers $auth -ContentType 'application/json' -Body '{}'
                        $jobId = $job.id
                        Write-Host "job id = $jobId"
                        $status = ''
                        for ($i = 1; $i -le 30; $i++) {
                            $status = (Invoke-RestMethod -Uri "$base/api/jobs/$jobId" -Headers $auth).status
                            Write-Host "  status = $status"
                            if ($status -eq 'COMPLETED' -or $status -eq 'FAILED') { break }
                            Start-Sleep -Seconds 2
                        }
                        if ($status -ne 'COMPLETED') { Write-Host "Worker tidak menyelesaikan job (status=$status)"; exit 1 }
                        Write-Host 'OK: worker memproses job'
                    '''
                }
            }
        }
    }

    // Ringkasan hasil di console log. Hanya metadata build, tidak ada rahasia yang dicetak.
    post {
        success {
            echo """
==================== RINGKASAN: SUCCESS ====================
 Job      : ${env.JOB_NAME} #${env.BUILD_NUMBER}
 Hasil    : SUCCESS (semua stage lolos, termasuk Smoke Test + worker K12)
 Image    : ${env.IMAGE}:${env.BUILD_NUMBER} (juga di-tag :latest, sudah di-push)
 Deploy   : compose project '${env.COMPOSE_PROJECT_NAME}' memakai compose.yaml
 Agent    : Windows
 Durasi   : ${currentBuild.durationString.replace(' and counting', '')}
 Detail   : ${env.BUILD_URL}
============================================================"""
        }
        failure {
            echo """
==================== RINGKASAN: FAILURE ====================
 Job      : ${env.JOB_NAME} #${env.BUILD_NUMBER}
 Hasil    : FAILURE, pipeline berhenti di stage '${env.FAILED_STAGE ?: 'tidak diketahui'}'
 Image    : ${env.IMAGE}:${env.BUILD_NUMBER}
 Catatan  : bila gagal di Test/Build/Push, container yang sedang berjalan tidak disentuh
 Durasi   : ${currentBuild.durationString.replace(' and counting', '')}
 Detail   : ${env.BUILD_URL}console
============================================================"""
            withCredentials([file(credentialsId: 'kosanhub-env', variable: 'ENV_FILE')]) {
                bat 'docker compose --env-file "%ENV_FILE%" logs --tail=40 app worker || exit /b 0'
            }
        }
        aborted {
            echo "RINGKASAN: ABORTED - ${env.JOB_NAME} #${env.BUILD_NUMBER} dihentikan di stage '${env.FAILED_STAGE ?: 'tidak diketahui'}'"
        }
        always {
            bat 'docker image rm kosanhub-test:%BUILD_NUMBER% >nul 2>&1 || exit /b 0'
        }
    }
}
