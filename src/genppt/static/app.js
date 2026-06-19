// GenPPT v2.0 — SSE streaming progress UI

const NODE_LABELS = {
  content_director: { name: "需求分析", icon: "🎯" },
  content_design: { name: "文案撰写", icon: "✍️" },
  ppt_design: { name: "版式设计", icon: "🎨" },
  chart_drawing: { name: "图表绘制", icon: "📊" },
  quality_review: { name: "质量审查", icon: "🔍" },
};

const PHASE_MESSAGES = {
  init: "初始化中…",
  director: "正在分析主题与受众需求…",
  content: "正在撰写逐页文案…",
  design: "正在设计每页版式…",
  chart: "正在分析数据并绘制图表…",
  review: "正在进行12维度质量审查…",
  done: "生成完成",
};

const state = {
  running: false,
  eventSource: null,
  reviewShown: false,
};

function $(id) { return document.getElementById(id); }

function setStatus(text, cls) {
  const el = $("status-text");
  el.textContent = text;
  el.className = "status " + (cls || "idle");
}

// ── SSE Streaming ──

async function startGenerate() {
  const topic = $("topic").value.trim();
  const requirements = $("requirements").value.trim();

  if (!topic) { setStatus("请输入主题", "error"); return; }

  state.running = true;
  state.reviewShown = false;
  $("generate-btn").disabled = true;
  $("progress-panel").style.display = "";
  $("download-area").style.display = "none";
  $("content-preview").style.display = "none";
  $("human-intervention").style.display = "none";
  $("agent-list").innerHTML = "";
  setStatus("正在连接…", "running");

  // Abort previous connection
  if (state.eventSource) { state.eventSource.close(); }

  const params = new URLSearchParams({ topic, requirements });
  const url = "/api/generate/stream?" + params.toString();
  const es = new EventSource(url);
  state.eventSource = es;

  es.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data);
      handleStreamEvent(data);
    } catch (_) { /* ignore parse errors on heartbeat */ }
  });

  es.addEventListener("error", () => {
    if (!state.running) return;
    es.close();
    state.running = false;
    $("generate-btn").disabled = false;
    setStatus("连接中断，请重试", "error");
  });

  es.addEventListener("close", () => {
    es.close();
    state.running = false;
    $("generate-btn").disabled = false;
  });
}

function handleStreamEvent(data) {
  const { event: evType, agent, phase, message, data: evData } = data;

  switch (evType) {
    case "agent_start":
      addAgentItem(agent);
      updateAgentStatus(agent, "active", message || PHASE_MESSAGES[phase] || "工作中…");
      setStatus(message || NODE_LABELS[agent]?.name || agent, "running");
      break;

    case "agent_end":
      updateAgentStatus(agent, "done", message || "完成");
      break;

    case "review":
      showReviewResult(evData);
      break;

    case "progress":
      if (evData && evData.state === "awaiting_human") {
        showHumanIntervention(evData);
      } else if (message) {
        setStatus(message, "running");
      }
      break;

    case "error":
      addAgentItem(agent);
      updateAgentStatus(agent, "error", message || "执行出错");
      setStatus("出错: " + (message || ""), "error");
      finishGeneration();
      break;

    case "done":
      setStatus("生成完成", "done");
      finishGeneration();
      break;
  }
}

// ── Agent Progress UI ──

function addAgentItem(node) {
  if (!node || node === "system") return;
  const existing = document.querySelector(`.agent-item[data-node="${node}"]`);
  if (existing) return;
  const info = NODE_LABELS[node] || { name: node, icon: "🤖" };
  const el = document.createElement("div");
  el.className = "agent-item pending";
  el.setAttribute("data-node", node);
  el.innerHTML = `<span class="agent-icon">${info.icon}</span>
    <span class="agent-name">${info.name}</span>
    <span class="agent-summary"></span>`;
  $("agent-list").appendChild(el);
}

function updateAgentStatus(node, status, summary) {
  if (!node || node === "system") return;
  const el = document.querySelector(`.agent-item[data-node="${node}"]`);
  if (!el) return;
  el.className = "agent-item " + status;
  if (summary) el.querySelector(".agent-summary").textContent = summary;
}

function showReviewResult(evData) {
  if (state.reviewShown) return;
  state.reviewShown = true;
  const passed = evData.passed;
  const score = evData.overall_score || "?";
  const issues = evData.issue_count || 0;

  const reviewEl = document.createElement("div");
  reviewEl.className = "agent-item " + (passed ? "done" : "warning");
  reviewEl.innerHTML = `<span class="agent-icon">${passed ? "✅" : "⚠️"}</span>
    <span class="agent-name">质量审查</span>
    <span class="agent-summary">${passed ? "通过" : issues + "个问题"} — ${score}分</span>`;
  $("agent-list").appendChild(reviewEl);
}

function showHumanIntervention(evData) {
  const panel = $("human-intervention");
  panel.style.display = "";

  const issues = evData.issues || [];
  const issuesHtml = issues.map((iss, i) =>
    `<div class="issue-card">
      <span class="issue-severity ${iss.severity || 'minor'}">${iss.severity || 'minor'}</span>
      <span>${iss.message || ''}</span>
    </div>`
  ).join("");

  $("intervention-summary").textContent =
    `自动审查已尽力，以下 ${issues.length} 个问题需要您确认：`;
  $("intervention-issues").innerHTML = issuesHtml;
  $("intervention-actions").style.display = "";
  $("intervention-waiting").style.display = "";
}

async function submitHumanDecision(action) {
  const btn = document.querySelector(`[data-action="${action}"]`);
  if (btn) btn.disabled = true;
  $("intervention-waiting").style.display = "none";

  try {
    await fetch("/api/human/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, task_id: "" }),
    });
  } catch (_) {}

  $("human-intervention").style.display = "none";
  if (action === "accept") {
    setStatus("已接受当前版本，继续…", "running");
  }
}

function finishGeneration() {
  state.running = false;
  $("generate-btn").disabled = false;
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  $("download-area").style.display = "";
}

// ── Event binding ──

$("generate-btn").addEventListener("click", startGenerate);

$("topic").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    startGenerate();
  }
});

$("view-content-btn").addEventListener("click", async () => {
  const preview = $("content-preview");
  preview.style.display = preview.style.display === "none" ? "" : "none";
  if (preview.style.display !== "none") {
    const topic = $("topic").value.trim();
    const req = $("requirements").value.trim();
    try {
      const resp = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, requirements }),
      });
      const data = await resp.json();
      if (data.slides) {
        let md = `# ${data.deck_plan?.title || "PPT 内容稿"}\n\n`;
        for (const s of data.slides) {
          md += `### ${s.index}. ${s.headline}\n`;
          for (const b of (s.body || [])) md += `- ${b}\n`;
          md += "\n";
        }
        $("content-md").textContent = md;
      }
    } catch (_) {}
  }
});

document.querySelectorAll(".intervention-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const action = btn.getAttribute("data-action");
    if (action) submitHumanDecision(action);
  });
});
