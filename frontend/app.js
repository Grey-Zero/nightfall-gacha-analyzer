const categories = [
  { id: "overview", label: "所有类别" },
  { id: "limited", label: "活动契约" },
  { id: "standard", label: "常驻契约" },
  { id: "selection", label: "遴选契约" },
  { id: "starter", label: "新手池" },
];
const navigation = [
  { id: "home", label: "首页" },
  ...categories,
];

const state = {
  accounts: [],
  dashboard: null,
  page: "home",
  category: "overview",
  showDates: localStorage.getItem("nightfall-show-dates") === "true",
  showFiveStars: localStorage.getItem("nightfall-show-five-stars") === "true",
  capture: { status: "idle", message: "", captured_bytes: 0, result: null, error: null },
};
const $ = (selector) => document.querySelector(selector);
let capturePollTimer = null;

async function api(method, payload = {}) {
  if (!window.pywebview?.api) {
    throw new Error("请启动桌面应用 desktop.py，不要直接打开网页文件。");
  }
  const result = Object.keys(payload).length
    ? await window.pywebview.api[method](payload)
    : await window.pywebview.api[method]();
  if (result?.error) throw new Error(result.error);
  return result;
}

function showStatus(message = "", isError = false) {
  const status = $("#app-status");
  status.textContent = message;
  status.classList.toggle("error", isError);
  status.hidden = !message;
}

function setCaptureState(capture) {
  state.capture = capture;
  const action = $("#capture-action");
  const inProgress = ["waiting", "recording", "processing"].includes(capture.status);
  action.disabled = capture.status === "processing" || !$("#account-select").value;
  $("#account-select").disabled = inProgress;

  if (capture.status === "waiting") action.textContent = "取消等待";
  else if (capture.status === "recording") action.textContent = "停止并解析";
  else if (capture.status === "processing") action.textContent = "正在解析…";
  else action.textContent = "开始采集记录";

  let message = capture.message || "开始前请启动并登录游戏。采集时需要打开「契约记录 → 全部记录」并逐页翻阅。";
  if (capture.status === "recording" && capture.captured_bytes) {
    const sizeKb = Math.max(1, Math.round(capture.captured_bytes / 1024));
    message += ` 已录制约 ${sizeKb} KB。`;
  }
  $("#capture-message").textContent = message;
  $("#capture-error").textContent = capture.error || "";
  $("#capture-error").hidden = !capture.error;

  const warnings = $("#capture-warnings");
  warnings.replaceChildren();
  (capture.result?.warnings || []).forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    warnings.appendChild(item);
  });
  if (capture.result?.single_pool_queries && !capture.result.records) {
    const item = document.createElement("li");
    item.textContent = `检测到 ${capture.result.single_pool_queries} 个单池筛选请求，这类数据不会导入。`;
    warnings.appendChild(item);
  }
  warnings.hidden = !warnings.childElementCount;
}

async function pollCaptureState() {
  try {
    const capture = await api("get_capture_state");
    setCaptureState(capture);
    if (["completed", "error", "cancelled", "idle"].includes(capture.status)) {
      clearInterval(capturePollTimer);
      capturePollTimer = null;
      if (capture.status === "completed" && capture.result?.inserted) {
        await loadDashboard();
      }
      return;
    }
  } catch (error) {
    clearInterval(capturePollTimer);
    capturePollTimer = null;
    setCaptureState({
      ...state.capture,
      status: "error",
      message: "无法读取采集状态。",
      error: error.message,
    });
  }
}

function beginCapturePolling() {
  if (capturePollTimer) clearInterval(capturePollTimer);
  capturePollTimer = setInterval(pollCaptureState, 1000);
  pollCaptureState();
}

function colorFor(pulls) {
  if (pulls <= 50) return "green";
  if (pulls <= 59) return "yellow";
  return "red";
}

function matchesCategory(group) {
  return state.category === "overview"
    || group.id === state.category
    || (state.category === "starter" && group.id.startsWith("starter:"));
}

function renderNavigation() {
  const nav = $("#category-nav");
  nav.replaceChildren();
  navigation.forEach((item) => {
    const button = document.createElement("button");
    button.textContent = item.label;
    const active = item.id === "home"
      ? state.page === "home"
      : state.page === "records" && item.id === state.category;
    button.className = active ? "active" : "";
    button.addEventListener("click", () => {
      if (item.id === "home") {
        state.page = "home";
      } else {
        state.page = "records";
        state.category = item.id;
      }
      render();
    });
    nav.appendChild(button);
  });
}

function createEventRow(event, group) {
  const block = document.createElement("div");
  block.className = "event-block";
  const row = document.createElement("div");
  row.className = "event-row";
  if (!state.showDates) row.classList.add("without-date");

  const card = document.createElement("div");
  card.className = "card-name";
  card.append(document.createTextNode(event.card_name));
  if (event.miss) {
    const miss = document.createElement("span");
    miss.className = "miss";
    miss.textContent = "歪";
    card.appendChild(miss);
  }
  const character = document.createElement("small");
  character.textContent = event.character;
  card.appendChild(character);

  const track = document.createElement("div");
  track.className = "bar-track";
  const bar = document.createElement("div");
  bar.className = `bar ${colorFor(event.pulls)}`;
  bar.style.width = `${Math.min(event.value / group.cap * 100, 100)}%`;
  track.appendChild(bar);
  const label = document.createElement("span");
  label.className = "bar-label";
  label.textContent = event.pulls;
  track.appendChild(label);

  row.append(card, track);
  if (state.showDates) {
    const meta = document.createElement("div");
    meta.className = "event-meta";
    meta.textContent = event.date || "进行中";
    row.appendChild(meta);
  }
  block.appendChild(row);

  if (state.showFiveStars && event.five_stars?.length) {
    const fiveStars = document.createElement("div");
    fiveStars.className = "five-star-list";
    event.five_stars.forEach((fiveStar, index) => {
      if (index) fiveStars.append(document.createTextNode("、"));
      const name = document.createElement("span");
      name.textContent = `${fiveStar.card_name}（${fiveStar.character}）`;
      fiveStars.appendChild(name);
    });
    block.appendChild(fiveStars);
  }
  return block;
}

function renderGroups() {
  const container = $("#groups");
  const groups = (state.dashboard?.groups || [])
    .filter(matchesCategory)
    .filter((group) => group.pulls);
  container.replaceChildren();
  if (!groups.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = state.accounts.length
      ? "当前类别暂无可展示的记录"
      : "还没有账号，请先新建账号";
    container.appendChild(empty);
    return;
  }

  groups.forEach((group) => {
    const panel = document.createElement("section");
    panel.className = "group-panel";
    const header = document.createElement("div");
    header.className = "group-header";
    const title = document.createElement("h2");
    title.textContent = group.label;
    const summary = document.createElement("span");
    summary.className = "group-summary";
    summary.textContent = `${group.pulls} 抽 · ${group.six_stars} 个六星 · 当前 ${group.current_pity} / ${group.cap}`;
    header.append(title, summary);
    panel.appendChild(header);

    const events = document.createElement("div");
    events.className = "events";
    if (group.current_pity > 0 && !group.completed) {
      events.appendChild(createEventRow({
        pulls: Math.min(group.current_pity, group.cap),
        value: Math.min(group.current_pity, group.cap),
        card_name: "当前垫抽",
        character: "尚未出六星",
        date: "",
      }, group));
    }
    [...group.events].reverse().forEach(
      (event) => events.appendChild(createEventRow(event, group)),
    );
    panel.append(header, events);
    container.appendChild(panel);
  });
}

function render() {
  const category = categories.find((item) => item.id === state.category);
  $("#page-title").textContent = state.page === "home"
    ? "首页"
    : category?.label || "契约记录";
  $("#total-records").textContent = state.dashboard?.total_records || 0;
  $("#overview-page").hidden = state.page !== "home";
  $("#records-page").hidden = state.page !== "records";
  renderNavigation();
  renderOverview();
  renderGroups();
}

function renderOverview() {
  const dashboard = state.dashboard;
  $("#overview-account").textContent = dashboard?.account
    ? `${dashboard.account.nickname}${dashboard.account.uid ? ` · UID ${dashboard.account.uid}` : ""}`
    : state.accounts.length ? "请选择账号以查看分析" : "请先新建账号";
  $("#overview-pulls").textContent = dashboard?.total_records || 0;
  $("#overview-six-stars").textContent = dashboard?.total_six_stars || 0;
  $("#overview-on-rate").textContent = dashboard?.on_rate == null
    ? "—"
    : `${(dashboard.on_rate * 100).toFixed(1)}%`;
  $("#export-records").disabled = !dashboard;
  $("#export-diagnostics").disabled = !dashboard;

  const groupContainer = $("#overview-groups");
  groupContainer.replaceChildren();
  (dashboard?.groups || []).filter((group) => group.pulls).forEach((group) => {
    const item = document.createElement("article");
    item.className = "overview-group";
    const name = document.createElement("strong");
    name.textContent = group.label;
    const detail = document.createElement("span");
    detail.textContent = `${group.pulls} 抽 · ${group.six_stars} 个六星 · 当前垫抽 ${group.current_pity}`;
    item.append(name, detail);
    groupContainer.appendChild(item);
  });
  if (!groupContainer.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "当前账号还没有抽卡记录。";
    groupContainer.appendChild(empty);
  }

  const recent = $("#recent-six-stars");
  recent.replaceChildren();
  const recentEvents = (dashboard?.groups || [])
    .flatMap((group) => group.events.map((event) => ({ ...event, group_label: group.label })))
    .sort((left, right) => right.timestamp_ms - left.timestamp_ms)
    .slice(0, 6);
  recentEvents.forEach((event) => {
    const item = document.createElement("div");
    item.className = "recent-six-star";
    const name = document.createElement("strong");
    name.textContent = event.card_name;
    const detail = document.createElement("span");
    detail.textContent = `${event.group_label} · ${event.pulls} 抽 · ${event.date}`;
    item.append(name, detail);
    recent.appendChild(item);
  });
  if (!recent.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "还没有六星获取记录。";
    recent.appendChild(empty);
  }
}

async function loadDashboard() {
  const accountId = Number($("#account-select").value);
  if (!accountId) {
    state.dashboard = null;
    render();
    return;
  }
  try {
    state.dashboard = await api("get_dashboard", { account_id: accountId });
    state.category = "overview";
    showStatus();
    render();
  } catch (error) {
    showStatus(`读取抽卡记录失败：${error.message}`, true);
  }
}

async function loadAccounts(preferredAccountId = null) {
  try {
    state.accounts = await api("get_accounts");
    const select = $("#account-select");
    select.replaceChildren();
    state.accounts.forEach((account) => {
      const option = document.createElement("option");
      option.value = account.account_id;
      option.textContent = account.uid
        ? `${account.nickname} · UID ${account.uid}`
        : account.nickname;
      select.appendChild(option);
    });
    if (preferredAccountId !== null) {
      select.value = String(preferredAccountId);
    }
    if (state.accounts.length) {
      await loadDashboard();
    } else {
      state.dashboard = null;
      render();
    }
    const capture = await api("get_capture_state");
    setCaptureState(capture);
    if (["waiting", "recording", "processing"].includes(capture.status)) {
      beginCapturePolling();
    }
  } catch (error) {
    showStatus(`读取账号失败：${error.message}`, true);
  }
}

const savedTheme = localStorage.getItem("nightfall-theme");
if (savedTheme === "night" || savedTheme === "day") {
  document.body.dataset.theme = savedTheme;
}
$("#theme-toggle").textContent = document.body.dataset.theme === "night"
  ? "切换至白天"
  : "切换至夜间";

$("#account-select").addEventListener("change", loadDashboard);
$("#theme-toggle").addEventListener("click", () => {
  const night = document.body.dataset.theme !== "night";
  document.body.dataset.theme = night ? "night" : "day";
  localStorage.setItem("nightfall-theme", document.body.dataset.theme);
  $("#theme-toggle").textContent = night ? "切换至白天" : "切换至夜间";
});
$("#new-account").addEventListener("click", () => {
  $("#account-error").hidden = true;
  $("#account-error").textContent = "";
  $("#new-account-dialog").showModal();
});
$("#cancel-account").addEventListener("click", () => $("#new-account-dialog").close());
$("#edit-account").addEventListener("click", () => {
  const selectedAccount = state.accounts.find(
    (account) => String(account.account_id) === $("#account-select").value,
  );
  if (!selectedAccount) {
    showStatus("请先选择要编辑的账号。", true);
    return;
  }
  $("#edit-account-error").textContent = "";
  $("#edit-account-error").hidden = true;
  $("#edit-nickname").value = selectedAccount.nickname;
  $("#edit-uid").value = selectedAccount.uid || "";
  $("#edit-account-dialog").showModal();
});
$("#cancel-edit-account").addEventListener("click", () => $("#edit-account-dialog").close());
$("#edit-account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const accountId = Number($("#account-select").value);
  const nickname = $("#edit-nickname").value.trim();
  const uid = $("#edit-uid").value.trim();
  const error = $("#edit-account-error");
  error.textContent = "";
  error.hidden = true;
  if (!nickname) {
    error.textContent = "账号昵称不能为空。";
    error.hidden = false;
    return;
  }
  try {
    await api("update_account", {
      account_id: accountId,
      nickname,
      uid: uid || null,
    });
    $("#edit-account-dialog").close();
    showStatus("账号信息已更新。");
    await loadAccounts(accountId);
  } catch (updateError) {
    error.textContent = `保存账号信息失败：${updateError.message}`;
    error.hidden = false;
  }
});
$("#capture-action").addEventListener("click", async () => {
  if (state.capture.status === "waiting" || state.capture.status === "recording") {
    try {
      setCaptureState(await api("stop_capture"));
      beginCapturePolling();
    } catch (error) {
      setCaptureState({ ...state.capture, error: error.message });
    }
    return;
  }
  if (!$("#account-select").value) {
    setCaptureState({
      ...state.capture,
      error: "请先新建或选择一个账号，再开始采集。",
    });
    return;
  }
  $("#capture-dialog").showModal();
});
$("#toggle-dates").checked = state.showDates;
$("#toggle-dates").addEventListener("change", (event) => {
  state.showDates = event.target.checked;
  localStorage.setItem("nightfall-show-dates", String(state.showDates));
  renderGroups();
});
$("#toggle-five-stars").checked = state.showFiveStars;
$("#toggle-five-stars").addEventListener("change", (event) => {
  state.showFiveStars = event.target.checked;
  localStorage.setItem("nightfall-show-five-stars", String(state.showFiveStars));
  renderGroups();
});
$("#export-records").addEventListener("click", async () => {
  try {
    const result = await api("export_records", {
      account_id: Number($("#account-select").value),
    });
    showStatus(result.cancelled ? "已取消导出抽卡记录。" : `抽卡记录已导出：${result.path}`);
  } catch (error) {
    showStatus(`导出抽卡记录失败：${error.message}`, true);
  }
});
$("#export-diagnostics").addEventListener("click", async () => {
  try {
    const result = await api("export_diagnostics", {
      account_id: Number($("#account-select").value),
    });
    showStatus(result.cancelled ? "已取消导出诊断信息。" : `诊断信息已导出：${result.path}`);
  } catch (error) {
    showStatus(`导出诊断信息失败：${error.message}`, true);
  }
});
$("#cancel-capture").addEventListener("click", () => $("#capture-dialog").close());
$("#confirm-capture").addEventListener("click", async () => {
  const confirmButton = $("#confirm-capture");
  confirmButton.disabled = true;
  try {
    const capture = await api("start_capture", {
      account_id: Number($("#account-select").value),
    });
    $("#capture-dialog").close();
    setCaptureState(capture);
    beginCapturePolling();
  } catch (error) {
    $("#capture-dialog").close();
    setCaptureState({ ...state.capture, error: error.message });
  } finally {
    confirmButton.disabled = false;
  }
});
$("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const nickname = $("#nickname").value.trim();
  const uid = $("#uid").value.trim();
  if (!nickname) return;
  const error = $("#account-error");
  error.hidden = true;
  try {
    await api("create_account", { nickname, uid: uid || null });
    $("#new-account-dialog").close();
    $("#account-form").reset();
    await loadAccounts();
  } catch (error) {
    const message = $("#account-error");
    message.textContent = `创建账号失败：${error.message}`;
    message.hidden = false;
  }
});

window.addEventListener("pywebviewready", () => loadAccounts());
