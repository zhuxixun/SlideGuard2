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
  selectAllRules: document.querySelector("#select-all-rules"),
  clearAllRules: document.querySelector("#clear-all-rules"),
  defaultRules: document.querySelector("#default-rules"),
  viewIssues: document.querySelector("#view-issues"),
  issuesPanel: document.querySelector("#issues-panel"),
  issuesCount: document.querySelector("#issues-count"),
  issueList: document.querySelector("#issue-list"),
  issueDetail: document.querySelector("#issue-detail"),
  issuePreview: document.querySelector("#issue-preview"),
  issueHeading: document.querySelector("#issue-heading"),
  issueDescription: document.querySelector("#issue-description"),
  issueTechnical: document.querySelector("#issue-technical"),
  issueSearch: document.querySelector("#issue-search"),
  pageFilter: document.querySelector("#page-filter"),
  severityFilter: document.querySelector("#severity-filter"),
  ruleFilter: document.querySelector("#rule-filter"),
  fixableFilter: document.querySelector("#fixable-filter"),
  statusFilter: document.querySelector("#status-filter"),
  previousIssue: document.querySelector("#previous-issue"),
  nextIssue: document.querySelector("#next-issue"),
  ignoreIssue: document.querySelector("#ignore-issue"),
  exportHtml: document.querySelector("#export-html"),
  exportXlsx: document.querySelector("#export-xlsx"),
  exportStatus: document.querySelector("#export-status"),
  repairSelected: document.querySelector("#repair-selected"),
  repairDialog: document.querySelector("#repair-dialog"),
  closeRepair: document.querySelector("#close-repair"),
  repairSummary: document.querySelector("#repair-summary"),
  repairPath: document.querySelector("#repair-path"),
  repairOperations: document.querySelector("#repair-operations"),
  confirmRepair: document.querySelector("#confirm-repair"),
  repairStatus: document.querySelector("#repair-status"),
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
let scanIssues = [];
let filteredIssues = [];
let activeIssueIndex = -1;
let previewUrl;
let lastScanResult;
let currentFile;
let scanRunning = false;
const selectedIssueIds = new Set();

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
    currentFile = data.file;
    resetScanResult();
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

function resetScanResult() {
  scanIssues = [];
  filteredIssues = [];
  lastScanResult = undefined;
  activeIssueIndex = -1;
  selectedIssueIds.clear();
  nodes.scanResult.hidden = true;
  nodes.scanResult.replaceChildren();
  nodes.viewIssues.hidden = true;
  nodes.exportHtml.hidden = true;
  nodes.exportXlsx.hidden = true;
  nodes.repairSelected.hidden = true;
  nodes.issuesPanel.hidden = true;
  nodes.issueDetail.hidden = true;
}
document.querySelectorAll('input[name="scan-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    nodes.customRules.hidden = selectedMode() !== "custom";
    updateScanAvailability();
  });
});
const ruleCheckboxes = [...nodes.customRules.querySelectorAll("input[data-rule]")];
const ruleModules = [...nodes.customRules.querySelectorAll("[data-rule-module]")];

function syncRuleModules() {
  ruleModules.forEach((module) => {
    const master = module.querySelector(".module-rule");
    const children = [...module.querySelectorAll("input[data-rule]")];
    const checked = children.filter((checkbox) => checkbox.checked).length;
    master.checked = checked === children.length;
    master.indeterminate = checked > 0 && checked < children.length;
  });
}

function updateScanAvailability() {
  const customEmpty = selectedMode() === "custom" && !ruleCheckboxes.some((checkbox) => checkbox.checked);
  nodes.startScan.disabled = scanRunning || !currentFile || customEmpty;
}

ruleCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", () => {
  syncRuleModules();
  updateScanAvailability();
}));
ruleModules.forEach((module) => {
  module.querySelector(".module-rule").addEventListener("change", (event) => {
    module.querySelectorAll("input[data-rule]").forEach((checkbox) => {
      checkbox.checked = event.target.checked;
    });
    syncRuleModules();
    updateScanAvailability();
  });
});
function setAllRules(checked) {
  ruleCheckboxes.forEach((checkbox) => { checkbox.checked = checked; });
  syncRuleModules();
  updateScanAvailability();
}
nodes.selectAllRules.addEventListener("click", () => setAllRules(true));
nodes.clearAllRules.addEventListener("click", () => setAllRules(false));
nodes.defaultRules.addEventListener("click", () => setAllRules(true));

nodes.startScan.addEventListener("click", async () => {
  const mode = selectedMode();
  const selectedRules = [...nodes.customRules.querySelectorAll('input[data-rule]:checked')]
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
  scanRunning = true;
  nodes.cancelScan.hidden = false;
  nodes.scanResult.hidden = true;
  nodes.startScan.textContent = "开始检查";
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
    scanRunning = true;
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
    scanRunning = false;
    nodes.cancelScan.hidden = true;
    nodes.cancelScan.disabled = false;
    nodes.cancelScan.textContent = "取消检查";
    updateScanAvailability();
    if (state.result) {
      const counts = { S1: 0, S2: 0, S3: 0, S4: 0 };
      state.result.issues.forEach((found) => { counts[found.severity] += 1; });
      nodes.scanProgress.textContent = state.result.complete ? "检查完成" : "扫描未完成";
      renderResultSummary(state.result, counts);
      nodes.scanResult.hidden = false;
      scanIssues = state.result.issues.map((found) => ({ ...found }));
      lastScanResult = state.result;
      selectedIssueIds.clear();
      nodes.repairSelected.hidden = true;
      nodes.viewIssues.hidden = !scanIssues.length;
      nodes.exportHtml.hidden = false;
      nodes.exportXlsx.hidden = false;
      prepareIssueFilters();
      nodes.startScan.textContent = "重新扫描";
    } else {
      nodes.scanProgress.textContent = state.error || "扫描失败";
    }
  }
}

function renderResultSummary(result, counts) {
  const affectedPages = new Set(result.issues.map((found) => found.slide_index).filter((page) => page > 0)).size;
  const fixable = result.issues.filter((found) => found.can_auto_fix).length;
  const byRule = new Map();
  result.issues.forEach((found) => byRule.set(found.rule_id, (byRule.get(found.rule_id) || 0) + 1));
  const modeLabels = { quick: "快速检查", standard: "标准检查", custom: "自定义检查" };
  const completedAt = new Date(result.finished_at).toLocaleString("zh-CN", { hour12: false });
  const lines = [
    `${currentFile?.name || "当前文件"} · ${modeLabels[result.mode] || result.mode} · ${result.rule_set_version} · ${completedAt}`,
    `共发现 ${result.issues.length} 个问题：S1 ${counts.S1}，S2 ${counts.S2}，S3 ${counts.S3}，S4 ${counts.S4}；涉及 ${affectedPages} 页；可自动修复 ${fixable} 个。`,
    result.issues.length ? `按类型：${[...byRule].map(([rule, count]) => `${rule} ${count}`).join("，")}` : "未发现符合当前规则的问题。",
  ];
  if (!result.complete) lines.unshift("扫描未完成：以下结果仅包含已经完成的检查。");
  nodes.scanResult.replaceChildren(...lines.map((line, index) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    if (!result.complete && index === 0) paragraph.className = "error";
    return paragraph;
  }));
}
nodes.viewIssues.addEventListener("click", () => {
  nodes.issuesPanel.hidden = false;
  applyIssueFilters();
  nodes.issuesPanel.scrollIntoView({ behavior: "smooth" });
});
nodes.exportHtml.addEventListener("click", () => exportReport("html"));
nodes.exportXlsx.addEventListener("click", () => exportReport("xlsx"));

async function exportReport(format) {
  nodes.exportHtml.disabled = true;
  nodes.exportXlsx.disabled = true;
  nodes.exportStatus.hidden = false;
  nodes.exportStatus.textContent = "正在导出报告…";
  try {
    const response = await apiFetch("/api/reports/export", {
      method: "POST",
      body: JSON.stringify({ format }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || "报告导出失败");
    nodes.exportStatus.textContent = data.cancelled ? "已取消导出" : `报告已保存到：${data.path}`;
  } catch (error) {
    nodes.exportStatus.textContent = error.message;
  } finally {
    nodes.exportHtml.disabled = false;
    nodes.exportXlsx.disabled = false;
  }
}
[nodes.issueSearch, nodes.pageFilter, nodes.severityFilter, nodes.ruleFilter, nodes.fixableFilter, nodes.statusFilter]
  .forEach((control) => control.addEventListener("input", applyIssueFilters));
nodes.previousIssue.addEventListener("click", () => showIssue(Math.max(0, activeIssueIndex - 1)));
nodes.nextIssue.addEventListener("click", () => showIssue(Math.min(filteredIssues.length - 1, activeIssueIndex + 1)));
nodes.ignoreIssue.addEventListener("click", async () => {
  if (activeIssueIndex < 0) return;
  const found = filteredIssues[activeIssueIndex];
  const nextStatus = found.status === "ignored" ? "pending" : "ignored";
  nodes.ignoreIssue.disabled = true;
  try {
    const response = await apiFetch(`/api/scans/current/issues/${encodeURIComponent(found.issue_id)}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: nextStatus }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || "更新问题状态失败");
    found.status = data.status;
    nodes.ignoreIssue.textContent = found.status === "ignored" ? "取消忽略" : "忽略";
    renderIssueList();
  } catch (error) {
    nodes.scanProgress.textContent = error.message;
  } finally {
    nodes.ignoreIssue.disabled = false;
  }
});

function prepareIssueFilters() {
  nodes.pageFilter.replaceChildren(new Option("全部页面", ""));
  [...new Set(scanIssues.map((found) => found.slide_index))].sort((a, b) => a - b).forEach((page) => {
    nodes.pageFilter.append(new Option(`第 ${page} 页`, String(page)));
  });
  nodes.ruleFilter.replaceChildren(new Option("全部类型", ""));
  [...new Set(scanIssues.map((found) => found.rule_id))].forEach((rule) => {
    nodes.ruleFilter.append(new Option(rule, rule));
  });
}

function applyIssueFilters() {
  const query = nodes.issueSearch.value.trim().toLowerCase();
  filteredIssues = scanIssues.filter((found) => {
    const searchable = `${found.rule_id} ${found.actual_value} ${found.evidence} ${found.suggestion}`.toLowerCase();
    return (!query || searchable.includes(query))
      && (!nodes.pageFilter.value || found.slide_index === Number(nodes.pageFilter.value))
      && (!nodes.severityFilter.value || found.severity === nodes.severityFilter.value)
      && (!nodes.ruleFilter.value || found.rule_id === nodes.ruleFilter.value)
      && (!nodes.fixableFilter.value || found.can_auto_fix === (nodes.fixableFilter.value === "yes"))
      && (!nodes.statusFilter.value || found.status === nodes.statusFilter.value);
  });
  activeIssueIndex = filteredIssues.length ? 0 : -1;
  renderIssueList();
  if (activeIssueIndex >= 0) showIssue(activeIssueIndex);
  else nodes.issueDetail.hidden = true;
}

function renderIssueList() {
  nodes.issueList.replaceChildren();
  nodes.issuesCount.textContent = `${filteredIssues.length} 个问题`;
  filteredIssues.forEach((found, index) => {
    const row = document.createElement("div");
    row.className = "issue-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedIssueIds.has(found.issue_id);
    checkbox.disabled = !repairAllowed() || !found.can_auto_fix || found.status !== "pending";
    checkbox.setAttribute("aria-label", `选择 ${found.rule_id} 第 ${found.slide_index} 页问题`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedIssueIds.add(found.issue_id);
      else selectedIssueIds.delete(found.issue_id);
      nodes.repairSelected.hidden = selectedIssueIds.size === 0;
    });
    const button = document.createElement("button");
    button.type = "button";
    button.className = `issue-item${index === activeIssueIndex ? " active" : ""}`;
    button.textContent = `${found.severity} · 第 ${found.slide_index} 页 · ${found.rule_id} · ${found.status === "ignored" ? "已忽略" : "待处理"}`;
    button.addEventListener("click", () => showIssue(index));
    row.append(checkbox, button);
    nodes.issueList.append(row);
  });
}

function repairAllowed() {
  return lastScanResult?.complete && lastScanResult.mode === "standard";
}

nodes.repairSelected.addEventListener("click", async () => {
  const response = await apiFetch("/api/repairs/prepare", {
    method: "POST",
    body: JSON.stringify({ issue_ids: [...selectedIssueIds] }),
  });
  const data = await response.json();
  if (!response.ok) { window.alert(data.detail?.message || "无法生成修复计划"); return; }
  if (data.cancelled) return;
  const plan = data.plan;
  nodes.repairSummary.textContent = `共 ${plan.issue_count} 个问题，涉及 ${plan.page_count} 页、${plan.object_count} 个对象。`;
  nodes.repairPath.textContent = `输出路径：${plan.destination}`;
  nodes.repairOperations.replaceChildren();
  plan.operations.forEach((operation) => {
    const item = document.createElement("p");
    item.textContent = `${operation.property_name}：${operation.original_value} → ${operation.target_value}`;
    nodes.repairOperations.append(item);
  });
  nodes.repairStatus.textContent = "";
  nodes.confirmRepair.disabled = false;
  nodes.repairDialog.showModal();
});
nodes.closeRepair.addEventListener("click", async () => {
  await apiFetch("/api/repairs/prepare", { method: "DELETE" });
  nodes.repairDialog.close();
});
nodes.confirmRepair.addEventListener("click", async () => {
  nodes.confirmRepair.disabled = true;
  nodes.closeRepair.disabled = true;
  nodes.repairStatus.textContent = "正在修复并执行标准复检…";
  try {
    const response = await apiFetch("/api/repairs/execute", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || "自动修复失败");
    nodes.repairStatus.textContent = `修复完成：已修复 ${data.fixed_count}，未修复 ${data.unresolved_count}，新增问题 ${data.introduced_count}。文件：${data.destination}`;
    selectedIssueIds.clear();
    nodes.repairSelected.hidden = true;
    renderScanState(data.scan);
    applyIssueFilters();
  } catch (error) {
    nodes.repairStatus.textContent = error.message;
    nodes.confirmRepair.disabled = false;
  } finally {
    nodes.closeRepair.disabled = false;
  }
});

async function showIssue(index) {
  if (index < 0 || index >= filteredIssues.length) return;
  activeIssueIndex = index;
  renderIssueList();
  const found = filteredIssues[index];
  nodes.issueDetail.hidden = false;
  nodes.issueHeading.textContent = `${found.severity} · ${found.rule_id} · 第 ${found.slide_index} 页${found.introduced_by_repair ? " · 修复后新增问题" : ""}`;
  nodes.issueDescription.innerHTML = "<dl><dt>实际值</dt><dd></dd><dt>标准值</dt><dd></dd><dt>判断依据</dt><dd></dd><dt>修改建议</dt><dd></dd><dt>可修复性</dt><dd></dd></dl>";
  const values = nodes.issueDescription.querySelectorAll("dd");
  [found.actual_value, found.expected_value, found.evidence, found.suggestion, found.can_auto_fix ? "可自动修复" : "需手动处理"]
    .forEach((value, valueIndex) => { values[valueIndex].textContent = value; });
  nodes.issueTechnical.textContent = `规则：${found.rule_id}\n对象：${found.object_keys.join(", ")}\n标准来源：${found.standard_source}`;
  nodes.ignoreIssue.textContent = found.status === "ignored" ? "取消忽略" : "忽略";
  nodes.previousIssue.disabled = index === 0;
  nodes.nextIssue.disabled = index === filteredIssues.length - 1;
  const response = await apiFetch(`/api/scans/current/slides/${found.slide_index}/preview?issue_id=${encodeURIComponent(found.issue_id)}`);
  if (response.ok) {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(await response.blob());
    nodes.issuePreview.src = previewUrl;
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
