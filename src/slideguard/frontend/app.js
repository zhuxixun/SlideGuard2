const fragment = new URLSearchParams(window.location.hash.slice(1));
const token = fragment.get("token");
history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

const nodes = {
  status: document.querySelector("#status"),
  exit: document.querySelector("#exit"),
  openPptx: document.querySelector("#open-pptx"),
  fileSummary: document.querySelector("#file-summary"),
  fileError: document.querySelector("#file-error"),
  startScan: document.querySelector("#start-scan"),
  cancelScan: document.querySelector("#cancel-scan"),
  scanProgress: document.querySelector("#scan-progress"),
  scanResult: document.querySelector("#scan-result"),
  customRules: document.querySelector("#custom-rules"),
  manage: document.querySelector("#manage-lexicon"),
  summary: document.querySelector("#lexicon-summary"),
  warning: document.querySelector("#lexicon-warning"),
  dialog: document.querySelector("#lexicon-dialog"),
  form: document.querySelector("#lexicon-form"),
  close: document.querySelector("#close-lexicon"),
  search: document.querySelector("#term-search"),
  newTerm: document.querySelector("#new-term"),
  addTerm: document.querySelector("#add-term"),
  list: document.querySelector("#term-list"),
  bulk: document.querySelector("#bulk-terms"),
  addBulk: document.querySelector("#add-bulk"),
  editSummary: document.querySelector("#edit-summary"),
};

let websocket;
let digest = "";
let originalTerms = [];
let workingTerms = [];
let dirty = false;

function apiFetch(path, options = {}) {
  return fetch(path, {
    ...options,
    cache: "no-store",
    headers: {
      ...(options.headers || {}),
      "Content-Type": "application/json",
      "X-SlideGuard-Token": token,
    },
  });
}

function normalizeTerms(terms) {
  return [...new Set(terms.map((term) => term.trim()).filter(Boolean))];
}

function updateDirtyState() {
  dirty = JSON.stringify(workingTerms) !== JSON.stringify(originalTerms);
  const added = workingTerms.filter((term) => !originalTerms.includes(term)).length;
  const removed = originalTerms.filter((term) => !workingTerms.includes(term)).length;
  nodes.editSummary.textContent = dirty ? `新增 ${added} 条，删除或修改 ${removed} 条` : "没有未保存修改";
}

function renderTerms() {
  const query = nodes.search.value.trim();
  nodes.list.replaceChildren();
  workingTerms.forEach((term, index) => {
    if (query && !term.includes(query)) return;
    const row = document.createElement("div");
    row.className = "term-row";
    const input = document.createElement("input");
    input.value = term;
    input.setAttribute("aria-label", `编辑词条 ${term}`);
    input.addEventListener("change", () => {
      workingTerms[index] = input.value.trim();
      workingTerms = normalizeTerms(workingTerms);
      renderTerms();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary";
    remove.textContent = "删除";
    remove.addEventListener("click", () => {
      workingTerms.splice(index, 1);
      renderTerms();
    });
    row.append(input, remove);
    nodes.list.append(row);
  });
  if (!nodes.list.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = query ? "没有匹配的词条。" : "词库为空。";
    nodes.list.append(empty);
  }
  updateDirtyState();
}

async function loadLexicon() {
  const response = await apiFetch("/api/lexicon");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  digest = data.digest;
  originalTerms = [...data.terms];
  workingTerms = [...data.terms];
  nodes.summary.textContent = `当前共有 ${data.count} 个有效词条。`;
  nodes.warning.hidden = !data.empty;
  nodes.manage.disabled = false;
  renderTerms();
}

function addTerms(terms) {
  workingTerms = normalizeTerms([...workingTerms, ...terms]);
  renderTerms();
}

function closeDialog() {
  if (dirty && !window.confirm("存在未保存修改，确定关闭吗？")) return;
  workingTerms = [...originalTerms];
  nodes.dialog.close();
}

if (!token) {
  nodes.status.textContent = "会话令牌缺失，请重新启动 SlideGuard。";
  nodes.exit.disabled = true;
} else {
  apiFetch("/api/health")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(async () => {
      nodes.openPptx.disabled = false;
      nodes.status.textContent = "本地服务连接成功。";
      await loadLexicon();
      const socketProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      websocket = new WebSocket(`${socketProtocol}//${window.location.host}/ws`, ["slideguard", token]);
      websocket.addEventListener("open", () => websocket.send("ping"));
      websocket.addEventListener("message", (event) => {
        if (event.data === "pong") return;
        const message = JSON.parse(event.data);
        if (message.type === "scan") renderScanState(message.payload);
      });
      websocket.addEventListener("close", () => { nodes.status.textContent = "本地服务连接已关闭。"; });
    })
    .catch(() => { nodes.status.textContent = "本地服务连接失败，请重新启动 SlideGuard。"; });
}

nodes.manage.addEventListener("click", () => {
  nodes.search.value = "";
  nodes.bulk.value = "";
  renderTerms();
  nodes.dialog.showModal();
});
nodes.openPptx.addEventListener("click", async () => {
  nodes.openPptx.disabled = true;
  nodes.fileError.hidden = true;
  nodes.fileSummary.textContent = "正在读取文件…";
  try {
    const response = await apiFetch("/api/dialog/open-pptx", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || "文件读取失败");
    if (data.cancelled) {
      nodes.fileSummary.textContent = "尚未打开文件";
      return;
    }
    const sizeMb = (data.file.size_bytes / 1024 / 1024).toFixed(2);
    nodes.fileSummary.textContent = `${data.file.name} · ${sizeMb} MB · ${data.file.slide_count} 页`;
    nodes.startScan.disabled = false;
    nodes.scanProgress.textContent = "请选择检查模式";
  } catch (error) {
    nodes.fileSummary.textContent = "尚未打开文件";
    nodes.fileError.textContent = error.message;
    nodes.fileError.hidden = false;
  } finally {
    nodes.openPptx.disabled = false;
  }
});
document.querySelectorAll('input[name="scan-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    nodes.customRules.hidden = selectedMode() !== "custom";
  });
});
nodes.startScan.addEventListener("click", async () => {
  const mode = selectedMode();
  const selectedRules = [...nodes.customRules.querySelectorAll('input[type="checkbox"]:checked')]
    .map((checkbox) => checkbox.value);
  if (mode === "custom" && !selectedRules.length) {
    window.alert("自定义检查至少选择一条规则。");
    return;
  }
  const response = await apiFetch("/api/scans", {
    method: "POST",
    body: JSON.stringify({ mode, selected_rules: selectedRules }),
  });
  const data = await response.json();
  if (!response.ok) {
    window.alert(data.detail?.message || "扫描启动失败");
    return;
  }
  nodes.startScan.disabled = true;
  nodes.cancelScan.hidden = false;
  nodes.scanResult.hidden = true;
  nodes.scanProgress.textContent = "正在解析文件…";
});
nodes.cancelScan.addEventListener("click", async () => {
  nodes.cancelScan.disabled = true;
  nodes.cancelScan.textContent = "正在取消";
  await apiFetch("/api/scans/current/cancel", { method: "POST" });
});

function selectedMode() {
  return document.querySelector('input[name="scan-mode"]:checked').value;
}

function renderScanState(state) {
  if (state.state === "running") {
    const labels = { parsing: "解析文件", preview: "生成页面预览", checking: "执行检查", summarizing: "汇总结果" };
    const progress = state.progress;
    nodes.scanProgress.textContent = progress
      ? `${labels[progress.stage]}${progress.current_rule ? ` · ${progress.current_rule}` : ""} · ${progress.completed_rules}/${progress.total_rules}`
      : "扫描准备中…";
    nodes.startScan.disabled = true;
    nodes.cancelScan.hidden = false;
    return;
  }
  if (["completed", "incomplete", "failed"].includes(state.state)) {
    nodes.cancelScan.hidden = true;
    nodes.cancelScan.disabled = false;
    nodes.cancelScan.textContent = "取消检查";
    nodes.startScan.disabled = false;
    if (state.result) {
      const counts = { S1: 0, S2: 0, S3: 0, S4: 0 };
      state.result.issues.forEach((found) => { counts[found.severity] += 1; });
      nodes.scanProgress.textContent = state.result.complete ? "检查完成" : "扫描未完成";
      nodes.scanResult.textContent = `共发现 ${state.result.issues.length} 个问题：S1 ${counts.S1}，S2 ${counts.S2}，S3 ${counts.S3}，S4 ${counts.S4}`;
      nodes.scanResult.hidden = false;
    } else {
      nodes.scanProgress.textContent = state.error || "扫描失败";
    }
  }
}
nodes.close.addEventListener("click", closeDialog);
nodes.search.addEventListener("input", renderTerms);
nodes.addTerm.addEventListener("click", () => {
  addTerms([nodes.newTerm.value]);
  nodes.newTerm.value = "";
});
nodes.addBulk.addEventListener("click", () => {
  addTerms(nodes.bulk.value.split(/\r?\n/));
  nodes.bulk.value = "";
});
nodes.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  updateDirtyState();
  if (!dirty) { nodes.dialog.close(); return; }
  if (!window.confirm(`${nodes.editSummary.textContent}，确定保存吗？`)) return;
  const response = await apiFetch("/api/lexicon", {
    method: "PUT",
    body: JSON.stringify({ terms: workingTerms, expected_digest: digest }),
  });
  if (response.status === 409) {
    window.alert("词库已被其他窗口修改，请刷新后重试。");
    await loadLexicon();
    return;
  }
  if (!response.ok) { window.alert("词库保存失败，原词库未改变。"); return; }
  const data = await response.json();
  digest = data.digest;
  originalTerms = [...data.terms];
  workingTerms = [...data.terms];
  nodes.summary.textContent = `当前共有 ${data.count} 个有效词条。`;
  nodes.warning.hidden = !data.empty;
  nodes.dialog.close();
});
nodes.exit.addEventListener("click", () => {
  nodes.exit.disabled = true;
  apiFetch("/api/exit", { method: "POST" })
    .then(() => { nodes.status.textContent = "SlideGuard 正在退出…"; })
    .catch(() => { nodes.status.textContent = "退出请求失败，请直接关闭页面。"; nodes.exit.disabled = false; });
});
