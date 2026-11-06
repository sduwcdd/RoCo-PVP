(function () {
  const DEFAULT_API = "http://server.hairuosky.cn:30006";
  const API_KEY = "roco.communityApiBase.v1";
  const DRAFT_KEY = "roco.communityDraft.v1";
  const AUTHOR_KEY = "roco.communityAuthor.v1";
  let requestedCommunity = false;
  let avatarMap = {};

  function apiBase() {
    return String(localStorage.getItem(API_KEY) || DEFAULT_API).replace(/\/+$/, "");
  }

  function readJson(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key) || "null") || fallback; }
    catch { return fallback; }
  }

  function injectStyles() {
    if (document.getElementById("roco-community-style")) return;
    const style = document.createElement("style");
    style.id = "roco-community-style";
    style.textContent = `
      .roco-team-modes{display:flex;align-items:center;gap:6px;padding:4px;border:1px solid #d7eaf3;border-radius:999px;background:#f7fcff;flex:none}
      .roco-team-mode{height:34px;border:0;border-radius:999px;background:transparent;color:#6c7480;padding:0 16px;font-size:12px;font-weight:900;cursor:pointer}
      .roco-team-mode.active{background:#9be6ff;color:#164256;box-shadow:0 2px 0 rgba(0,0,0,.12)}
      .roco-community{min-height:0;flex:1;display:flex;flex-direction:column;gap:10px;overflow:hidden}
      .roco-community-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:none}
      .roco-community-title{font-size:14px;font-weight:1000;color:#3b3426}
      .roco-community-sub{font-size:11px;color:#8b8375;margin-top:2px}
      .roco-community-actions{display:flex;gap:7px}
      .roco-community-button{border:1px solid #d8c99f;border-radius:999px;background:#fff;color:#6e6042;padding:7px 12px;font-size:11px;font-weight:900;cursor:pointer}
      .roco-community-button.primary{border-color:#f1b92f;background:#f8cf3a;color:#2a210d}
      .roco-community-status{border:1px solid #f0d9a2;border-radius:10px;background:#fff9e9;color:#8b6410;padding:8px 10px;font-size:11px;font-weight:800;flex:none}
      .roco-community-form{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:12px;border:1px solid #d7eaf3;border-radius:15px;background:#f8fcff;flex:none}
      .roco-community-form[hidden]{display:none!important}
      .roco-field{display:flex;flex-direction:column;gap:4px;min-width:0}
      .roco-field.full{grid-column:1/-1}
      .roco-field label{font-size:11px;font-weight:900;color:#696257}
      .roco-field input,.roco-field textarea{width:100%;box-sizing:border-box;border:1px solid #d8e1e6;border-radius:10px;background:#fff;padding:8px 10px;color:#39342b;font:12px system-ui;outline:none}
      .roco-field textarea{resize:vertical;min-height:64px}
      .roco-field input:focus,.roco-field textarea:focus{border-color:#70cde9}
      .roco-draft{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px dashed #d8c99f;border-radius:12px;background:#fffdf5;padding:9px 11px}
      .roco-draft-name{font-size:12px;font-weight:1000;color:#55492f}
      .roco-draft-record{font-size:12px;font-weight:1000;color:#e48700;white-space:nowrap}
      .roco-post-list{display:flex;flex-direction:column;gap:9px;overflow:auto;min-height:0;padding-right:3px}
      .roco-post-empty{padding:50px 20px;border:1px dashed #d7eaf3;border-radius:15px;background:#fbfdfe;text-align:center;color:#8a939a;font-size:12px;font-weight:800}
      .roco-post{border:1px solid #d7eaf3;border-radius:15px;background:#fff;padding:12px 14px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 16px}
      .roco-post-title{font-size:14px;font-weight:1000;color:#342e23}
      .roco-post-meta{margin-top:3px;color:#989082;font-size:10px;font-weight:800}
      .roco-post-rate{text-align:right;color:#ef8a00;font-size:19px;font-weight:1000}
      .roco-post-rate small{display:block;color:#8d8678;font-size:10px}
      .roco-post-lineup{display:flex;gap:5px;align-items:center;flex-wrap:wrap}
      .roco-post-pet{width:38px;height:38px;border-radius:999px;background:#eaf8ff;display:grid;place-items:center;overflow:hidden;color:#6690a0;font-size:10px;font-weight:1000}
      .roco-post-pet img{width:34px;height:34px;object-fit:contain}
      .roco-post-notes{grid-column:1/-1;color:#686155;font-size:11px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
      .roco-post-footer{grid-column:1/-1;display:flex;justify-content:flex-end}
      @media(max-width:780px){.roco-community-form{grid-template-columns:1fr}.roco-field.full,.roco-draft{grid-column:1}.roco-post{grid-template-columns:1fr}.roco-post-rate{text-align:left}}
    `;
    document.head.appendChild(style);
  }

  function renameTopNavigation() {
    const header = document.querySelector("header");
    if (!header) return;
    for (const button of header.querySelectorAll("button")) {
      if (button.textContent.trim() === "热门配队") button.textContent = "配队";
    }
  }

  function findTeamRoot() {
    const headings = [...document.querySelectorAll("h1,h2,h3,h4")];
    const heading = headings.find((node) => /^热门配队\s*\(/.test(node.textContent.trim()));
    if (!heading) return null;
    let root = heading.parentElement;
    while (root && root.parentElement && root.children.length < 3) root = root.parentElement;
    return root && root.parentElement ? root : null;
  }

  function setOriginalVisible(root, visible) {
    for (const child of [...root.children]) {
      if (child.classList.contains("roco-team-modes") || child.classList.contains("roco-community")) continue;
      child.style.display = visible ? "" : "none";
    }
  }

  function petBadge(id) {
    const badge = document.createElement("span");
    badge.className = "roco-post-pet";
    const avatar = avatarMap[String(id)] || "";
    if (avatar) {
      const image = document.createElement("img");
      image.src = avatar;
      image.alt = "";
      badge.appendChild(image);
    } else badge.textContent = `#${id}`;
    return badge;
  }

  function renderPosts(panel, posts) {
    const list = panel.querySelector("[data-roco-post-list]");
    list.innerHTML = "";
    if (!posts.length) {
      const empty = document.createElement("div");
      empty.className = "roco-post-empty";
      empty.textContent = "暂时还没有玩家阵容推荐，发布第一篇吧。";
      list.appendChild(empty);
      return;
    }
    posts.forEach((post) => {
      const card = document.createElement("article");
      card.className = "roco-post";
      const heading = document.createElement("div");
      const title = document.createElement("div");
      title.className = "roco-post-title";
      title.textContent = post.title || "未命名阵容";
      const meta = document.createElement("div");
      meta.className = "roco-post-meta";
      meta.textContent = `发布者 ${post.author || "匿名"} · ${post.created_at ? new Date(post.created_at).toLocaleString() : ""}`;
      heading.append(title, meta);
      const rate = document.createElement("div");
      rate.className = "roco-post-rate";
      rate.textContent = `${Math.round(Number(post.win_rate || 0) * 1000) / 10}%`;
      const sample = document.createElement("small");
      sample.textContent = `软件记录 ${post.wins || 0}胜 ${post.losses || 0}负`;
      rate.appendChild(sample);
      const lineup = document.createElement("div");
      lineup.className = "roco-post-lineup";
      (Array.isArray(post.lineup_ids) ? post.lineup_ids : []).forEach((id) => lineup.appendChild(petBadge(id)));
      const notes = document.createElement("div");
      notes.className = "roco-post-notes";
      notes.textContent = post.notes || "";
      const footer = document.createElement("div");
      footer.className = "roco-post-footer";
      const copy = document.createElement("button");
      copy.className = "roco-community-button";
      copy.textContent = "复制阵容代码";
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(post.team_code || ""); copy.textContent = "已复制"; }
        catch { window.prompt("复制阵容代码", post.team_code || ""); }
        window.setTimeout(() => { copy.textContent = "复制阵容代码"; }, 1200);
      };
      footer.appendChild(copy);
      card.append(heading, rate, lineup, notes, footer);
      list.appendChild(card);
    });
  }

  async function loadPosts(panel) {
    const status = panel.querySelector("[data-roco-community-status]");
    status.hidden = false;
    status.textContent = "正在读取玩家阵容推荐…";
    try {
      const response = await fetch(`${apiBase()}/api/recommendations`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      renderPosts(panel, Array.isArray(payload.items) ? payload.items : []);
      status.hidden = true;
    } catch (error) {
      status.hidden = false;
      status.textContent = `推荐服务器暂时无法连接：${error && error.message ? error.message : error}`;
      renderPosts(panel, []);
    }
  }

  function fillDraft(panel) {
    const draft = readJson(DRAFT_KEY, null);
    const box = panel.querySelector("[data-roco-draft]");
    const submit = panel.querySelector("[data-roco-submit]");
    if (!draft || !Array.isArray(draft.pets) || draft.pets.length !== 6 || !draft.total) {
      box.querySelector(".roco-draft-name").textContent = "请先到 战绩 → 个人胜率 选择一个阵容";
      box.querySelector(".roco-draft-record").textContent = "尚未选择";
      submit.disabled = true;
      submit.style.opacity = ".5";
      return null;
    }
    box.querySelector(".roco-draft-name").textContent = draft.name || "未命名阵容";
    box.querySelector(".roco-draft-record").textContent = `${draft.wins}胜 ${draft.losses}负 · ${Math.round(Number(draft.winRate || 0) * 1000) / 10}%`;
    panel.querySelector("[name=title]").value ||= draft.name || "";
    submit.disabled = false;
    submit.style.opacity = "";
    return draft;
  }

  function communityPanel() {
    const panel = document.createElement("section");
    panel.className = "roco-community";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="roco-community-head">
        <div><div class="roco-community-title">玩家阵容推荐</div><div class="roco-community-sub">胜率和场次来自软件记录，阵容心得由玩家填写</div></div>
        <div class="roco-community-actions"><button class="roco-community-button" data-roco-refresh>刷新</button><button class="roco-community-button primary" data-roco-open-form>发布推荐</button></div>
      </div>
      <div class="roco-community-status" data-roco-community-status hidden></div>
      <form class="roco-community-form" data-roco-community-form hidden>
        <div class="roco-draft" data-roco-draft><div class="roco-draft-name"></div><div class="roco-draft-record"></div></div>
        <div class="roco-field"><label>发布者</label><input name="author" maxlength="24" required placeholder="你的昵称"></div>
        <div class="roco-field"><label>阵容标题</label><input name="title" maxlength="60" required placeholder="给推荐起个标题"></div>
        <div class="roco-field full"><label>阵容代码</label><textarea name="teamCode" maxlength="12000" required placeholder="粘贴完整阵容代码"></textarea></div>
        <div class="roco-field full"><label>阵容心得</label><textarea name="notes" maxlength="4000" required placeholder="介绍阵容思路、先发、对局要点和注意事项"></textarea></div>
        <div class="roco-community-actions full"><button type="button" class="roco-community-button" data-roco-cancel>取消</button><button type="submit" class="roco-community-button primary" data-roco-submit>确认发布</button></div>
      </form>
      <div class="roco-post-list" data-roco-post-list></div>
    `;
    const form = panel.querySelector("[data-roco-community-form]");
    const author = panel.querySelector("[name=author]");
    author.value = localStorage.getItem(AUTHOR_KEY) || "";
    panel.querySelector("[data-roco-open-form]").onclick = () => { form.hidden = !form.hidden; fillDraft(panel); };
    panel.querySelector("[data-roco-cancel]").onclick = () => { form.hidden = true; };
    panel.querySelector("[data-roco-refresh]").onclick = () => loadPosts(panel);
    form.onsubmit = async (event) => {
      event.preventDefault();
      const draft = fillDraft(panel);
      if (!draft) return;
      const status = panel.querySelector("[data-roco-community-status]");
      const submit = panel.querySelector("[data-roco-submit]");
      const payload = {
        author: author.value.trim(),
        title: panel.querySelector("[name=title]").value.trim(),
        team_code: panel.querySelector("[name=teamCode]").value.trim(),
        notes: panel.querySelector("[name=notes]").value.trim(),
        lineup_key: draft.lineupKey,
        lineup_ids: draft.pets.map((pet) => Number(pet.id || 0)),
        wins: Number(draft.wins || 0),
        losses: Number(draft.losses || 0),
      };
      localStorage.setItem(AUTHOR_KEY, payload.author);
      submit.disabled = true;
      status.hidden = false;
      status.textContent = "正在发布…";
      try {
        const response = await fetch(`${apiBase()}/api/recommendations`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
        form.hidden = true;
        status.textContent = "发布成功";
        window.setTimeout(() => { status.hidden = true; }, 1300);
        await loadPosts(panel);
      } catch (error) {
        status.hidden = false;
        status.textContent = `发布失败：${error && error.message ? error.message : error}`;
      } finally {
        submit.disabled = false;
      }
    };
    return panel;
  }

  function installTeamModes(root) {
    if (!root || root.dataset.rocoCommunityInstalled === "1") return;
    root.dataset.rocoCommunityInstalled = "1";
    const modes = document.createElement("div");
    modes.className = "roco-team-modes";
    const popular = document.createElement("button");
    popular.className = "roco-team-mode active";
    popular.textContent = "热门配队";
    const community = document.createElement("button");
    community.className = "roco-team-mode";
    community.textContent = "玩家阵容推荐";
    modes.append(popular, community);
    const panel = communityPanel();
    root.insertBefore(modes, root.firstChild);
    root.appendChild(panel);

    const activate = (mode) => {
      const showCommunity = mode === "community";
      popular.classList.toggle("active", !showCommunity);
      community.classList.toggle("active", showCommunity);
      panel.hidden = !showCommunity;
      setOriginalVisible(root, !showCommunity);
      modes.style.display = "flex";
      if (showCommunity) { fillDraft(panel); loadPosts(panel); }
    };
    popular.onclick = () => activate("popular");
    community.onclick = () => activate("community");
    root.__rocoActivateCommunity = () => activate("community");
    if (requestedCommunity) { requestedCommunity = false; activate("community"); }
  }

  function openTeamsCommunity() {
    requestedCommunity = true;
    const overlay = document.getElementById("roco-history-overlay");
    if (overlay) overlay.style.display = "none";
    const header = document.querySelector("header");
    const teams = header && [...header.querySelectorAll("button")].find((button) => ["配队", "热门配队"].includes(button.textContent.trim()));
    if (teams) teams.click();
    window.setTimeout(scan, 80);
  }

  function scan() {
    renameTopNavigation();
    const root = findTeamRoot();
    if (root) {
      installTeamModes(root);
      if (requestedCommunity && root.__rocoActivateCommunity) {
        requestedCommunity = false;
        root.__rocoActivateCommunity();
      }
    }
  }

  window.addEventListener("message", (event) => {
    if (event && event.data && event.data.type === "roco-open-team-community") openTeamsCommunity();
  });
  window.RocoOpenTeamCommunity = openTeamsCommunity;
  injectStyles();
  fetch("/native-data/petAvatarIndex.json", { cache: "force-cache" }).then((response) => response.json()).then((data) => { avatarMap = data || {}; }).catch(() => {});
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();


(function () {
  "use strict";

  if (window.__qkEnemyPresetRuntimeV194) return;
  window.__qkEnemyPresetRuntimeV194 = "20260811-enemy-preset-runtime-v194";

  const STORAGE_KEY = "roco.enemySkillPresets.v192";
  const MESSAGE_KIND = "qk_enemy_skill_preset_write_v192";
  const SLOT_PREFIX = "slot:";
  let avatarMap = {};

  function readJson(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key) || "null") || fallback;
    } catch {
      return fallback;
    }
  }

  function normalize(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      version: 1,
      generation: String(source.generation || "0"),
      enabled: source.enabled === true,
      members: source.members && typeof source.members === "object" ? source.members : {},
    };
  }

  function persist(value) {
    const preset = normalize({ ...value, generation: String(Date.now()) });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preset));
    try {
      window.chrome?.webview?.postMessage({ kind: MESSAGE_KIND, data: preset });
    } catch {}
    return preset;
  }

  function catalog() {
    return window.RocoEnemyPresetCatalogV193 || null;
  }

  function currentEnemyRoster() {
    const state = readJson("roco.battleHud.state.v52", null) || readJson("roco.battleHud.state.v50", null);
    return Array.isArray(state?.enemyTeam) ? state.enemyTeam.slice(0, 6) : [];
  }

  function injectStyles() {
    if (document.getElementById("qk-enemy-preset-v194-style")) return;
    const style = document.createElement("style");
    style.id = "qk-enemy-preset-v194-style";
    style.textContent = `
      .qk-enemy-preset-v194{min-height:0;display:flex;flex-direction:column;gap:12px;overflow:auto;padding:18px 20px;border:1px solid rgba(230,193,105,.8);border-radius:20px;background:rgba(255,255,255,.88)}
      .qk-enemy-preset-v194[hidden]{display:none!important}
      .qk-preset-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
      .qk-preset-title{font-size:18px;font-weight:900;color:#5b4518}
      .qk-preset-actions{display:flex;align-items:center;gap:8px;flex:none}
      .qk-preset-button{height:38px;border:1px solid #e2c173;border-radius:999px;background:#fffdf8;color:#644d1b;padding:0 15px;font-size:13px;font-weight:900;cursor:pointer}
      .qk-preset-button.active{border-color:#69c8ee;background:#a9e8ff;color:#16506a}
      .qk-preset-status{min-height:20px;font-size:13px;font-weight:800;color:#986900}
      .qk-preset-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
      .qk-preset-slot{min-width:0;border:1px solid #cfe6f1;border-radius:14px;background:rgba(248,253,255,.96);padding:12px}
      .qk-preset-slot-head{display:flex;align-items:center;gap:9px;margin-bottom:9px}
      .qk-preset-avatar{width:40px;height:40px;display:grid;place-items:center;flex:none;border-radius:12px;background:#e7f7ff;color:#6191a5;font-size:13px;font-weight:900;overflow:hidden}
      .qk-preset-avatar img{width:38px;height:38px;object-fit:contain}
      .qk-preset-pet,.qk-preset-move{width:100%;box-sizing:border-box;border:1px solid #e4bd5d;border-radius:10px;background:#fffdf8;color:#4f3c15;padding:9px 10px;font:13px system-ui;outline:none}
      .qk-preset-pet:focus,.qk-preset-move:focus{border-color:#65c6eb}
      .qk-preset-moves{display:grid;grid-template-columns:1fr 1fr;gap:7px}
      @media(max-width:1100px){.qk-preset-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:760px){.qk-preset-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function createPanel() {
    const panel = document.createElement("section");
    panel.className = "qk-enemy-preset-v194";
    panel.dataset.qkEnemyPresetPanel = "1";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="qk-preset-head">
        <div class="qk-preset-title">敌方预设</div>
        <div class="qk-preset-actions">
          <button type="button" class="qk-preset-button" data-qk-load>载入当前阵容</button>
          <button type="button" class="qk-preset-button" data-qk-toggle></button>
        </div>
      </div>
      <div class="qk-preset-status" data-qk-status></div>
      <datalist id="qk-enemy-preset-pets-v194"></datalist>
      <div class="qk-preset-grid" data-qk-grid></div>
    `;

    let preset = normalize(readJson(STORAGE_KEY, {}));
    const status = panel.querySelector("[data-qk-status]");
    const grid = panel.querySelector("[data-qk-grid]");
    const toggle = panel.querySelector("[data-qk-toggle]");

    function entry(index) {
      return preset.members[SLOT_PREFIX + index] || null;
    }

    function setEntry(index, value) {
      const members = { ...preset.members, [SLOT_PREFIX + index]: value };
      if (value?.monsterId) members[String(value.monsterId)] = value;
      preset = { ...preset, members };
    }

    function flash(message) {
      status.textContent = message;
      window.setTimeout(() => {
        if (status.textContent === message) status.textContent = "";
      }, 1600);
    }

    function updateToggle() {
      toggle.textContent = preset.enabled ? "已启用" : "未启用";
      toggle.classList.toggle("active", preset.enabled);
    }

    function save(message) {
      preset = persist(preset);
      updateToggle();
      if (message) flash(message);
    }

    function ensureCatalog() {
      const api = catalog();
      if (!api) {
        status.textContent = "技能资料正在加载";
        window.setTimeout(render, 250);
        return null;
      }
      const list = panel.querySelector("#qk-enemy-preset-pets-v194");
      if (!list.dataset.ready) {
        const fragment = document.createDocumentFragment();
        api.allMonsters().forEach((monster) => {
          const option = document.createElement("option");
          option.value = monster.name;
          fragment.appendChild(option);
        });
        list.appendChild(fragment);
        list.dataset.ready = "1";
      }
      return api;
    }

    function render() {
      const api = ensureCatalog();
      if (!api) return;
      status.textContent = "";
      grid.replaceChildren();
      for (let index = 0; index < 6; index += 1) {
        const current = entry(index) || { monsterId: null, monsterName: "", skills: [] };
        const card = document.createElement("div");
        card.className = "qk-preset-slot";

        const head = document.createElement("div");
        head.className = "qk-preset-slot-head";
        const avatar = document.createElement("span");
        avatar.className = "qk-preset-avatar";
        const avatarUrl = current.monsterId ? avatarMap[String(current.monsterId)] : "";
        if (avatarUrl) {
          const image = document.createElement("img");
          image.src = avatarUrl;
          image.alt = "";
          avatar.appendChild(image);
        } else {
          avatar.textContent = String(index + 1);
        }

        const pet = document.createElement("input");
        pet.className = "qk-preset-pet";
        pet.setAttribute("list", "qk-enemy-preset-pets-v194");
        pet.placeholder = `第 ${index + 1} 只精灵`;
        pet.value = current.monsterName || "";
        head.append(avatar, pet);

        const moves = document.createElement("div");
        moves.className = "qk-preset-moves";
        const pool = current.monsterId ? api.movesForMonster(current.monsterId) : [];
        for (let moveIndex = 0; moveIndex < 4; moveIndex += 1) {
          const select = document.createElement("select");
          select.className = "qk-preset-move";
          const empty = document.createElement("option");
          empty.value = "";
          empty.textContent = `技能 ${moveIndex + 1}`;
          select.appendChild(empty);
          pool.forEach((move) => {
            const option = document.createElement("option");
            option.value = String(move.id);
            option.textContent = move.name;
            select.appendChild(option);
          });
          select.value = current.skills?.[moveIndex]?.id == null ? "" : String(current.skills[moveIndex].id);
          select.addEventListener("change", () => {
            const selected = pool.find((move) => String(move.id) === select.value) || null;
            const latest = entry(index) || current;
            const skills = Array.from({ length: 4 }, (_, itemIndex) => latest.skills?.[itemIndex] || null);
            skills[moveIndex] = selected ? { id: selected.id, name: selected.name } : null;
            setEntry(index, { ...latest, skills });
            save();
          });
          moves.appendChild(select);
        }

        pet.addEventListener("change", () => {
          const found = api.findMonster(pet.value);
          if (!found) {
            flash("请选择列表中的精灵");
            pet.value = current.monsterName || "";
            return;
          }
          setEntry(index, { monsterId: found.id, monsterName: found.name, skills: [] });
          save();
          render();
        });

        card.append(head, moves);
        grid.appendChild(card);
      }
      updateToggle();
    }

    toggle.addEventListener("click", () => {
      preset = { ...preset, enabled: !preset.enabled };
      save(preset.enabled ? "敌方预设已启用" : "敌方预设已关闭");
    });

    panel.querySelector("[data-qk-load]").addEventListener("click", () => {
      const roster = currentEnemyRoster();
      if (!roster.length) {
        flash("当前没有可载入的敌方阵容");
        return;
      }
      roster.forEach((member, index) => {
        const monster = member?.monster || member;
        const id = Number(monster?.id ?? monster?.petId ?? monster?.petBaseId);
        const name = monster?.localized?.zh?.name || monster?.monsterName || monster?.petName || monster?.name;
        if (Number.isFinite(id) && name) {
          setEntry(index, { monsterId: id, monsterName: name, skills: entry(index)?.skills || [] });
        }
      });
      save("已载入当前敌方阵容");
      render();
    });

    panel.__qkRender = render;
    return panel;
  }

  function isManualButton(button) {
    return button?.textContent?.trim() === "手动配队";
  }

  function restoreContent(root, modeBar, panel) {
    for (const child of root.children) {
      if (child === modeBar || child === panel) continue;
      if (child.dataset.qkPresetHiddenV194 === "1") {
        child.style.display = child.dataset.qkPresetDisplayV194 || "";
        delete child.dataset.qkPresetHiddenV194;
        delete child.dataset.qkPresetDisplayV194;
      }
    }
  }

  function hideContent(root, modeBar, panel) {
    for (const child of root.children) {
      if (child === modeBar || child === panel) continue;
      if (child.dataset.qkPresetHiddenV194 !== "1") {
        child.dataset.qkPresetHiddenV194 = "1";
        child.dataset.qkPresetDisplayV194 = child.style.display || "";
      }
      child.style.display = "none";
    }
  }

  function install(manual) {
    const modeBar = manual.parentElement;
    const root = modeBar?.parentElement;
    if (!modeBar || !root || modeBar.dataset.qkEnemyPresetInstalledV194 === "1") return;
    modeBar.dataset.qkEnemyPresetInstalledV194 = "1";

    modeBar.querySelectorAll("[data-qk-enemy-preset-button]").forEach((node) => node.remove());
    root.querySelectorAll(":scope > [data-qk-enemy-preset-panel]").forEach((node) => node.remove());

    const button = document.createElement("button");
    button.type = "button";
    button.className = manual.className;
    button.textContent = "敌方预设";
    button.dataset.qkEnemyPresetButton = "1";
    manual.insertAdjacentElement("afterend", button);

    const panel = createPanel();
    root.appendChild(panel);

    modeBar.addEventListener("click", (event) => {
      const clicked = event.target.closest("button");
      if (!clicked) return;
      if (clicked === button) {
        event.preventDefault();
        event.stopImmediatePropagation();
        for (const item of modeBar.querySelectorAll("button")) item.classList.toggle("active", item === button);
        hideContent(root, modeBar, panel);
        panel.hidden = false;
        panel.style.display = "flex";
        panel.__qkRender?.();
        return;
      }
      panel.hidden = true;
      panel.style.display = "none";
      restoreContent(root, modeBar, panel);
    }, true);
  }

  function scan() {
    injectStyles();
    const manual = [...document.querySelectorAll("button")].find(isManualButton);
    if (manual) install(manual);
  }

  fetch("/native-data/petAvatarIndex.json", { cache: "force-cache" })
    .then((response) => response.json())
    .then((value) => { avatarMap = value || {}; })
    .catch(() => {});

  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  window.setInterval(scan, 400);
  scan();
})();

