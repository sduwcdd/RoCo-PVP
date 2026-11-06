"""把本轮（悬浮 HUD App + rkpp 启动器 + 工作台排版修复）的验证结果写进 docs/WORKBENCH_STATUS.json。

跑法：
    $env:PYTHONPATH='.'; python scripts\_update_status_round2.py
"""
import json
import pathlib

PATH = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'WORKBENCH_STATUS.json'
data = json.loads(PATH.read_text(encoding='utf-8'))
data['date'] = '2026-10-28'
data['phase'] = 'hud-overlay-app-and-rkpp-launcher'
checks = data.setdefault('checks', {})
checks['desktop_hud_overlay'] = [
    'Electron transparent frameless window launched with --no-sandbox --disable-gpu --disable-gpu-sandbox --in-process-gpu; 3 processes alive after 12s, empty stderr',
    'Qt WebEngine (PySide6) rejected: webpage never renders inside WA_TranslucentBackground, implementation removed',
    'data chain verified: POST /api/hud/publish -> GET /api/hud/snapshot -> hud.html rendered 迪莫 198 / 幽影 249 and four skill slots',
    'enemy skill slots stay empty unless observed; no hidden move-set leak',
]
checks['rkpp_launcher'] = [
    'scripts/start_rkpp_live.ps1: project venv .venv-rkpp required, scapy 2.8.0 import self-check, admin guard with explicit message',
    'root cause of earlier ModuleNotFoundError: conda base has no scapy and ENABLE_USER_SITE=False',
    'live panel start hint rewritten: admin PowerShell + project root + venv python (copy button copies the full block)',
]
checks['workbench_record_panel_layout'] = [
    'root cause: @media(min-width:1050px) center-column grid-template-rows compressed max-content rows inside a fixed-height container',
    'fix: center-column is now a flex column with .panel{flex:0 0 auto}; measured record rect.h=520 >= scrollHeight=518, form bottom 1022 < record bottom 1032 < history top 1040',
    'my side = 受到伤害 | 剩余血量 | 总血量, opponent = 受到伤害 | 剩余血量(%) | 对方技能来源; both grids measured t=801 b=910',
]
checks['third_party_copy'] = [
    'vendor/洛克PVP助手 mirrors E:\\洛克PVP助手 exactly: 25908 files, 2834470415 bytes on both sides',
    'earlier attempt failed because robocopy is absent from this shell PATH; full path C:\\Windows\\System32\\robocopy.exe used instead',
]
checks['this_round_tests'] = {
    'node_ui_tests': '114 passed / 0 failed',
    'python_subset': '32 tests OK (mark_integration, mark_switch, live_bridge)',
    'star_mark_swift_probe': 'artifacts/_probe_swift_star.txt: 300 -> 293 -> 273, mark consumed, mark.trigger damage=20',
}

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('status updated:', PATH)
