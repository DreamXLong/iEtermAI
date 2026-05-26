from __future__ import annotations


def render_mobile_console() -> str:
    """Return a small dependency-free mobile control page."""

    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>iEtermAI 手机查票</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f5f7fb; color: #172033; }
    main { max-width: 720px; margin: 0 auto; padding: 16px; }
    h1 { font-size: 24px; margin: 8px 0 16px; }
    section { background: white; border-radius: 16px; padding: 16px; margin: 12px 0; box-shadow: 0 8px 24px rgba(20, 36, 64, .08); }
    label { display: block; font-size: 14px; font-weight: 600; margin: 10px 0 6px; }
    input, select, textarea, button { width: 100%; box-sizing: border-box; font: inherit; border-radius: 10px; }
    input, select, textarea { border: 1px solid #cfd7e6; padding: 12px; background: #fff; color: #172033; }
    textarea { min-height: 120px; resize: vertical; }
    button { border: 0; padding: 12px; margin-top: 12px; background: #1769ff; color: white; font-weight: 700; }
    button:disabled { background: #98a2b3; color: #eef2f6; }
    button.secondary { background: #526071; }
    button.danger { background: #c62828; }
    pre { white-space: pre-wrap; word-break: break-word; background: #101828; color: #d6e4ff; padding: 12px; border-radius: 10px; overflow: auto; }
    img.screenshot { display: none; width: 100%; border-radius: 12px; border: 1px solid #cfd7e6; background: #101828; }
    img.screenshot.active { display: block; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .hint { color: #667085; font-size: 13px; line-height: 1.5; }
    .ok { color: #07883d; font-weight: 700; }
    .bad { color: #c62828; font-weight: 700; }
    .loading {
      display: none; position: sticky; top: 8px; z-index: 10; margin-bottom: 12px;
      padding: 12px; border-radius: 12px; background: #fff4d6; color: #7a4b00; font-weight: 700;
      box-shadow: 0 8px 20px rgba(122, 75, 0, .12);
    }
    .loading.active { display: flex; align-items: center; gap: 10px; }
    .spinner {
      width: 18px; height: 18px; border: 3px solid rgba(122, 75, 0, .2);
      border-top-color: #7a4b00; border-radius: 50%; animation: spin .8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-color-scheme: dark) {
      body { background: #101828; color: #f4f7fb; }
      section { background: #182230; }
      input, select, textarea { background: #101828; color: #f4f7fb; border-color: #344054; }
      img.screenshot { border-color: #344054; }
      .hint { color: #a8b3c7; }
      .loading { background: #3b2b08; color: #ffd778; }
      .spinner { border-color: rgba(255, 215, 120, .25); border-top-color: #ffd778; }
    }
  </style>
</head>
<body>
<main>
  <h1>iEtermAI 手机查票</h1>
  <div id="loading" class="loading"><span class="spinner"></span><span id="loadingText">执行中...</span></div>

  <section>
    <h2>访问密码</h2>
    <label for="token">Token</label>
    <input id="token" type="password" placeholder="请输入电脑服务配置的 Token" />
    <button class="secondary" onclick="saveToken()">保存 Token</button>
    <p class="hint">Token 只保存在手机浏览器本地，用来防止别人误操作你的电脑。</p>
  </section>

  <section>
    <h2>登录准备</h2>
    <button onclick="loadStatus()">刷新状态</button>
    <button onclick="loadAliases()">读取线路</button>
    <label for="alias">线路/别名</label>
    <select id="alias"></select>
    <button onclick="selectAlias()">选择线路</button>
    <button onclick="login()">登录并确认系统提示</button>
    <button class="danger" onclick="closeApp()">关闭 iEterm</button>
    <div id="status" class="hint">状态：未刷新</div>
  </section>

  <section>
    <h2>国际票价表单查询</h2>
    <div class="row">
      <div><label for="origin">出发</label><input id="origin" value="BJS" maxlength="3" /></div>
      <div><label for="destination">到达</label><input id="destination" value="TYO" maxlength="3" /></div>
    </div>
    <label for="departure_date">日期</label>
    <input id="departure_date" type="date" />
    <div class="row">
      <div><label for="airline">航司</label><input id="airline" value="CA" maxlength="3" /></div>
      <div><label for="passenger_type">乘客</label><input id="passenger_type" value="ADT" maxlength="3" /></div>
    </div>
    <button onclick="queryFare()">查国际票价</button>
  </section>

  <section>
    <h2>原始查询指令</h2>
    <label for="command">只允许查询类指令</label>
    <input id="command" placeholder="例如 XS FSD BJSTYO/CA" />
    <button onclick="runRawCommand()">发送查询指令</button>
    <p class="hint">系统会拦截订座、出票、退票、废票等高风险指令。</p>
  </section>

  <section>
    <h2>结果</h2>
    <pre id="output">暂无结果</pre>
  </section>

  <section>
    <h2>当前 iEterm 截图</h2>
    <button class="secondary" onclick="refreshScreenshot()">手动刷新截图</button>
    <p id="screenshotHint" class="hint">每次操作完成后会自动刷新。建议把 iEterm 窗口撑满，并保持在最前面。</p>
    <img id="screenshot" class="screenshot" alt="当前 iEterm 状态截图" />
  </section>
</main>

<script>
const output = document.getElementById("output");
const statusBox = document.getElementById("status");
const loadingBox = document.getElementById("loading");
const loadingText = document.getElementById("loadingText");
const screenshot = document.getElementById("screenshot");
const screenshotHint = document.getElementById("screenshotHint");
let screenshotObjectUrl = null;

document.getElementById("token").value = localStorage.getItem("ieterm_token") || "";
document.getElementById("departure_date").valueAsDate = new Date(Date.now() + 24 * 60 * 60 * 1000);

function saveToken() {
  localStorage.setItem("ieterm_token", document.getElementById("token").value.trim());
  output.textContent = "Token 已保存";
}

function tokenHeaders() {
  const token = document.getElementById("token").value.trim();
  return token ? {"X-IETERM-Token": token} : {};
}

async function api(path, options = {}) {
  const headers = Object.assign({"Content-Type": "application/json"}, tokenHeaders(), options.headers || {});
  const response = await fetch(path, Object.assign({}, options, {headers}));
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!response.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data, null, 2));
  return data;
}

function show(data) {
  output.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function setLoading(active, message = "执行中...") {
  loadingText.textContent = message;
  loadingBox.classList.toggle("active", active);
  for (const button of document.querySelectorAll("button")) {
    button.disabled = active;
  }
}

async function withLoading(message, task) {
  setLoading(true, message);
  output.textContent = `${message}\\n请稍等，不要重复点击...`;
  try {
    return await task();
  } finally {
    await refreshScreenshot({silent: true});
    setLoading(false);
  }
}

async function refreshScreenshot(options = {}) {
  try {
    const response = await fetch(`/session/screenshot?t=${Date.now()}`, {headers: tokenHeaders()});
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    if (screenshotObjectUrl) URL.revokeObjectURL(screenshotObjectUrl);
    screenshotObjectUrl = URL.createObjectURL(blob);
    screenshot.src = screenshotObjectUrl;
    screenshot.classList.add("active");
    screenshotHint.textContent = `截图已更新：${new Date().toLocaleTimeString()}`;
  } catch (error) {
    if (!options.silent) show(String(error));
    screenshotHint.textContent = "暂时无法获取截图，请确认 iEterm 已打开并且服务有屏幕录制/辅助功能权限。";
  }
}

async function loadStatus() {
  return withLoading("正在刷新登录状态...", async () => {
    const data = await api("/session/status", {method: "GET"});
    statusBox.innerHTML = `状态：<span class="${data.state === "logged_in" ? "ok" : "bad"}">${data.state}</span>`;
    show(data);
  }).catch(error => show(String(error)));
}

async function loadAliases() {
  return withLoading("正在读取线路列表...", async () => {
    const data = await api("/session/login-aliases", {method: "GET"});
    const aliasSelect = document.getElementById("alias");
    aliasSelect.innerHTML = "";
    for (const alias of data.aliases || []) {
      const option = document.createElement("option");
      option.value = alias;
      option.textContent = alias;
      if (alias === data.selected_alias) option.selected = true;
      aliasSelect.appendChild(option);
    }
    show(data);
  }).catch(error => show(String(error)));
}

async function selectAlias() {
  return withLoading("正在选择线路...", async () => {
    const alias = document.getElementById("alias").value;
    show(await api("/session/login-alias", {method: "POST", body: JSON.stringify({alias})}));
  }).catch(error => show(String(error)));
}

async function login() {
  return withLoading("正在登录并确认系统提示...", async () => {
    const data = await api("/session/login", {method: "POST", body: "{}"});
    statusBox.innerHTML = `状态：<span class="${data.state === "logged_in" ? "ok" : "bad"}">${data.state}</span>`;
    show(data);
  }).catch(error => show(String(error)));
}

async function closeApp() {
  if (!confirm("确定要关闭电脑上的 iEterm 吗？")) return;
  return withLoading("正在关闭 iEterm 并确认弹窗...", async () => {
    const data = await api("/session/close", {method: "POST", body: "{}"});
    statusBox.innerHTML = `状态：<span class="${data.state === "logged_out" ? "ok" : "bad"}">${data.state}</span>`;
    show(data);
  }).catch(error => show(String(error)));
}

async function queryFare() {
  return withLoading("正在查询国际票价...", async () => {
    const payload = {
      origin: document.getElementById("origin").value.trim().toUpperCase(),
      destination: document.getElementById("destination").value.trim().toUpperCase(),
      departure_date: document.getElementById("departure_date").value,
      airline: document.getElementById("airline").value.trim().toUpperCase() || null,
      passenger_type: document.getElementById("passenger_type").value.trim().toUpperCase() || "ADT"
    };
    show(await api("/query/international-fare", {method: "POST", body: JSON.stringify(payload)}));
  }).catch(error => show(String(error)));
}

async function runRawCommand() {
  return withLoading("正在发送原始查询指令...", async () => {
    const command = document.getElementById("command").value.trim();
    show(await api("/query/raw-command", {method: "POST", body: JSON.stringify({command, parse_fares: true})}));
  }).catch(error => show(String(error)));
}
</script>
</body>
</html>"""
