param(
    [int]$Port = 8766,
    [switch]$NoServer,
    # duel = 左右两块贴边竖面板（照游戏内原版布局，中间不遮挡）；single = 一条横条
    [ValidateSet('duel', 'single')]
    [string]$Mode = 'duel'
)

# 洛克 PVP 悬浮 HUD（Electron 桌面版）
# 半透明、无边框、置顶，直接叠在游戏画面上；数据来自本工程的服务。
#
# 注意：这个文件必须保存成「UTF-8 带 BOM」。Windows PowerShell 5.1 在
# 没有 BOM 时会按系统 ANSI（GBK）解码，中文注释被拆坏后连引号、花括号
# 都会失配，报 MissingEndCurlyBrace / 字符串缺少终止符。
#
# 为什么 Electron 的启动参数是必须的：本机 Chromium 的 GPU 子进程初始化会失败
# （0xC0000135 GPU process isn't usable），必须 --in-process-gpu 且关掉硬件加速，
# 否则进程直接退出，看不到任何窗口。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $root 'overlay\node_modules\electron\dist\electron.exe'

if (-not (Test-Path -LiteralPath $electron)) {
    Write-Host "Electron 还没装：在 $root\overlay 目录执行 npm install" -ForegroundColor Red
    exit 1
}

# 语法预检：Electron 遇到 main.js 语法错误会弹一个「A JavaScript error occurred in
# the main process」的错误框挡住屏幕，脚本这边看不出原因。先用 node --check 拦一下，
# 把真正的报错打在控制台里。
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node -and $node.Source) {
    $mainJs = Join-Path $root 'overlay\main.js'
    $check = & $node.Source --check $mainJs 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "overlay\main.js 有语法错误，先修好再启动：" -ForegroundColor Red
        $check | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
        exit 1
    }
}

function Find-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $venv = Join-Path $root '.venv-rkpp\Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) { return $venv }
    return $null
}

if (-not $NoServer) {
    $up = $false
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 2
        $up = ($r.StatusCode -eq 200)
    } catch { $up = $false }

    if (-not $up) {
        $py = Find-Python
        if (-not $py) {
            Write-Host "找不到 python，无法启动模拟服务；请先装 Python 或用 -NoServer 只开窗口。" -ForegroundColor Red
            exit 1
        }
        Write-Host "模拟服务未运行，正在后台启动（$py，端口 $Port）..." -ForegroundColor Yellow
        Start-Process -FilePath $py -ArgumentList '-m', 'lab.server', '--port', "$Port" `
            -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $root 'artifacts\_server_out.log') `
            -RedirectStandardError (Join-Path $root 'artifacts\_server_err.log')
        Start-Sleep -Seconds 6

        try {
            $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 3
            if ($r2.StatusCode -eq 200) {
                Write-Host "模拟服务已就绪：http://127.0.0.1:$Port" -ForegroundColor Green
            } else {
                Write-Host "模拟服务状态码 $($r2.StatusCode)，悬浮窗会显示离线提示。" -ForegroundColor Yellow
            }
        } catch {
            $errLog = Join-Path $root 'artifacts\_server_err.log'
            Write-Host "模拟服务没起来，悬浮窗会显示离线提示。日志：$errLog" -ForegroundColor Yellow
            if (Test-Path -LiteralPath $errLog) {
                Get-Content -LiteralPath $errLog -Tail 12 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
            }
        }
    } else {
        Write-Host "复用已在运行的模拟服务：http://127.0.0.1:$Port" -ForegroundColor Green
    }
}

$env:ROCO_HUD_MODE = $Mode

# 抓包前置提示：面板本身会写明 key_hits=0，但用户双击 HUD 时多半只看这个控制台窗口，
# 所以这里也把"现在能不能出数据"讲清楚，省得对着空白面板猜。
try {
    $live = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/live/battle" -TimeoutSec 3
    $st = $live.state
    if ($st) {
        $cap = $st.capture
        if (-not $st.relay_ok) {
            Write-Host "抓包中继没在运行：先以管理员身份双击「启动实时抓包.bat」，面板会一直是空白。" -ForegroundColor Yellow
        } elseif ($st.key_missing) {
            Write-Host ("抓到 " + $cap.target_packets + " 个包，但没拿到本次会话密钥（key_hits=0），业务帧解不开。" ) -ForegroundColor Yellow
            Write-Host "  0x1002 密钥只在客户端建连时发一次，所以抓包要比建连更早开着。" -ForegroundColor Yellow
            Write-Host "  请在游戏里退回登录界面重新进入，或重启游戏客户端；密钥到手会自动开始解码。" -ForegroundColor Yellow
        } elseif ($st.has_battle) {
            Write-Host ("解密正常，已在跟踪对局（第 " + $st.round + " 回合）。") -ForegroundColor Green
        } else {
            Write-Host ("解密正常（业务记录 " + $cap.parsed_business_records + " 条），进对局后自动填充。") -ForegroundColor Green
        }
    }
} catch {
    Write-Host "查不到抓包状态（服务刚起或未连上），先开面板，稍后可双击「查看抓包状态.bat」核对。" -ForegroundColor Gray
}

Start-Process -FilePath $electron `
    -ArgumentList '.', '--no-sandbox', '--disable-gpu', '--disable-gpu-sandbox', '--in-process-gpu' `
    -WorkingDirectory (Join-Path $root 'overlay')

Write-Host ""
Write-Host "悬浮 HUD 已启动：" -ForegroundColor Green
Write-Host "  布局：$Mode（duel = 左右两块贴边竖面板，各自带一条顶栏；single = 一条横条）" -ForegroundColor Gray
Write-Host "  每块面板右上角「×」只关那一块；Ctrl+Alt+Q 关掉全部（穿透后点不到按钮就用热键）" -ForegroundColor Gray
Write-Host "  拖动顶部深色条 = 移动窗口；双击顶部条 = 折叠成一条细条" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+H = 显示/隐藏；Ctrl+Alt+L = 点击穿透；Ctrl+Alt+F = 贴屏幕顶部居中" -ForegroundColor Gray
Write-Host "  托盘图标（右下角）可重载、打开网页版工作台、退出" -ForegroundColor Gray
Write-Host "网页版仍在 http://127.0.0.1:$Port/battle" -ForegroundColor Green
