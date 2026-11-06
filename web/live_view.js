"use strict";
// 实时抓包面板：只读 /api/live/events，展示 rkpp 中继转出的战斗事件。
// 中继（vendor/rkpp 的 opencode-server）没有运行时，面板显示"未连接"并给出启动命令，
// 不伪造任何事件，也不改动工作台存档。
(() => {
  const POLL_MS = 3000;
  const MAX_ROWS = 60;
  let first = true;
  let timer = null;
  const rows = [];

  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const byId = (id) => document.getElementById(id);

  // 抓包中继必须在【管理员 PowerShell】里跑，并且要用项目自带的 venv 解释器：
  // 系统 python（含 conda base）没有 scapy，直接跑会 ModuleNotFoundError。
  function startHint() {
    return [
      "# 1) 右键「Windows PowerShell」→ 以管理员身份运行（抓包与 Npcap 旁路监听都需要提权）",
      "# 2) 在项目根目录执行（一条命令即可，脚本会检查 venv、scapy 和管理员权限）",
      "powershell -ExecutionPolicy Bypass -File scripts\\start_rkpp_live.ps1",
      "",
      "# 等价的手写方式：先 cd 到 vendor\\rkpp，再用 venv 里的 python",
      "cd vendor\\rkpp",
      "..\\..\\.venv-rkpp\\Scripts\\python.exe rkpp_live_tools.py opencode-server --iface WLAN --port 8195 --relay-host 127.0.0.1 --relay-port 8765"
    ].join("\n");
  }

  function describe(event) {
    const parts = [];
    if (event.side) parts.push(event.side === "my" ? "我方" : "敌方");
    if (event.turn) parts.push("第 " + event.turn + " 回合");
    if (event.skill_name || event.skill_id) parts.push("技能 " + (event.skill_name || "") + (event.skill_id ? "(" + event.skill_id + ")" : ""));
    if (event.damage != null) parts.push("伤害 " + event.damage);
    if (event.energy_delta != null) parts.push("能量 " + event.energy_delta + "→" + event.energy_after);
    return parts.length ? parts.join(" · ") : event.text || "(空摘要)";
  }

  function render() {
    const wrap = byId("live-events");
    if (!wrap) return;
    wrap.replaceChildren();
    if (!rows.length) {
      wrap.append(el("p", "还没有抓到事件。先启动中继，再进入游戏对战。", "section-note"));
      return;
    }
    for (const event of rows.slice(-MAX_ROWS).reverse()) {
      const row = el("div", "live-row" + (event.recognized ? "" : " unknown"));
      row.append(el("span", "#" + (event.row_index ?? "?"), "live-index"));
      row.append(el("span", describe(event), "live-text"));
      if (!event.recognized) row.append(el("span", event.summary_kind || "未识别", "live-kind"));
      row.setAttribute("title", event.text || "");
      wrap.append(row);
    }
  }

  function setState(text, ok) {
    const node = byId("live-state");
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("ok", !!ok);
    node.classList.toggle("bad", !ok);
  }

  async function poll() {
    try {
      const response = await fetch("/api/live/events" + (first ? "?limit=200&reset=1" : "?limit=200"), { cache: "no-store" });
      first = false;
      if (!response.ok) {
        setState("接口异常", false);
        return;
      }
      const payload = await response.json();
      if (!payload.relay_available) {
        setState("未连接", false);
        const hint = byId("live-hint");
        if (hint) hint.textContent = "抓包中继未运行（" + (payload.error || "127.0.0.1:8765 无响应") +
          "）。在【管理员 PowerShell】的项目根目录执行 scripts\\start_rkpp_live.ps1（或点右侧复制完整命令）。";
        render();
        return;
      }
      for (const event of payload.events || []) rows.push(event);
      if (rows.length > 400) rows.splice(0, rows.length - 400);
      setState("已连接 · " + rows.length + " 条", true);
      const hint = byId("live-hint");
      if (hint) hint.textContent = "只读事件流。技能、伤害、能量取自游戏结算通知；未识别的摘要会原样保留。";
      render();
    } catch (error) {
      setState("读取失败", false);
    }
  }

  function boot() {
    const refresh = byId("live-refresh");
    if (refresh) refresh.onclick = () => poll();
    const copy = byId("live-copy");
    if (copy) {
      copy.onclick = async () => {
        const text = startHint();
        try {
          await navigator.clipboard.writeText(text);
          copy.textContent = "已复制";
          setTimeout(() => { copy.textContent = "复制启动命令"; }, 1500);
        } catch (error) {
          const hint = byId("live-hint");
          if (hint) hint.textContent = "启动命令：" + text;
        }
      };
    }
    poll();
    timer = setInterval(poll, POLL_MS);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.addEventListener("beforeunload", () => timer && clearInterval(timer));
})();
