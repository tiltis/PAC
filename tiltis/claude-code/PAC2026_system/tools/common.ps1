# 설치·실행 스크립트 공통 함수

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Find-Python([string]$explicit) {
    # Python 3.10 이상을 찾는다. Microsoft Store 가짜 python.exe는 실행 실패로 걸러진다
    $cands = @()
    if ($explicit) { $cands += ,@($explicit) }
    foreach ($v in '3.13', '3.12', '3.11', '3.10') { $cands += ,@('py', "-$v") }
    $cands += ,@('python')
    foreach ($c in $cands) {
        $exe = $c[0]
        $pre = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            & $exe @pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $ver = & $exe @pre -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
                Write-Step "Python $ver ($($c -join ' '))"
                return ,$c
            }
        } catch { }
    }
    throw 'Python 3.10 이상이 없음. https://www.python.org/downloads/ 에서 설치(Add to PATH 체크) 후 다시 실행'
}

function New-Venv($py, [string]$venv) {
    $vpy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $vpy)) {
        Write-Step "가상환경 생성: $venv"
        $exe = $py[0]
        $pre = @($py | Select-Object -Skip 1)
        & $exe @pre -m venv $venv | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '가상환경 생성 실패' }
    }
    & $vpy -m pip install --disable-pip-version-check -q --upgrade pip | Out-Host  # 함수 반환값에 섞이지 않게
    return $vpy
}

function Install-Requirements([string]$vpy, [string]$dir, [switch]$NoLock) {
    $lock = Join-Path $dir 'requirements.lock.txt'
    if ((-not $NoLock) -and (Test-Path $lock)) {
        Write-Step "고정 버전 설치: $lock"
        & $vpy -m pip install --disable-pip-version-check -r $lock
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host '고정 버전 설치 실패(파이썬 버전 차이일 수 있음). 범위 버전으로 다시 설치' -ForegroundColor Yellow
    }
    Write-Step "범위 버전 설치: $dir\requirements.txt"
    & $vpy -m pip install --disable-pip-version-check -r (Join-Path $dir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '패키지 설치 실패' }
}
