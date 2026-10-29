<#
.SYNOPSIS
  为知识库与检索层准备 Python 虚拟环境。

.DESCRIPTION
  做三件事：建 venv（复用系统已装的 torch/numpy）、装固定版本依赖、跑自检。
  默认把临时目录指向工作区内的 .tmp —— 在没有写系统 TEMP 权限的环境里，
  pip 会反复空转（本项目实测），这一步能避免。

.PARAMETER Python
  用来创建 venv 的解释器，默认从 PATH 找 python。

.PARAMETER Index
  可选：pip 镜像地址，默认清华源。

.PARAMETER DryRun
  只打印将要执行的命令，不实际执行。

.EXAMPLE
  .\scripts\setup_env.ps1
  .\scripts\setup_env.ps1 -DryRun
#>
param(
    [string]$Python = "python",
    [string]$Index = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$kb = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $kb ".venv\Scripts\python.exe"
$tmp = Join-Path $kb ".tmp"

function Run([string]$what, [scriptblock]$block) {
    Write-Host "==> $what" -ForegroundColor Cyan
    if ($DryRun) { Write-Host "    (dry-run) $($block.ToString().Trim())" -ForegroundColor DarkGray; return }
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$what 失败（退出码 $LASTEXITCODE）" }
}

Write-Host "知识库目录：$kb" -ForegroundColor DarkGray

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $env:TEMP = $tmp
    $env:TMP = $tmp
}

if (-not (Test-Path $venvPy)) {
    Run "创建虚拟环境（复用系统 site-packages）" { & $Python -m venv --system-site-packages (Join-Path $kb ".venv") }
} else {
    Write-Host "==> 虚拟环境已存在，跳过创建" -ForegroundColor DarkGray
}

Run "安装依赖" {
    & $venvPy -m pip install --upgrade pip -i $Index --trusted-host ([uri]$Index).Host --quiet
    & $venvPy -m pip install -r (Join-Path $kb "requirements.txt") -i $Index --trusted-host ([uri]$Index).Host
}

Run "环境自检" { & $venvPy (Join-Path $kb "scripts\doctor.py") }

Write-Host "`n下一步：& `"$venvPy`" scripts\build_index.py" -ForegroundColor Green
