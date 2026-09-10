(() => {
  const root = document.querySelector("[data-testid=chat-live]");
  if (!root) return;
  const runId = root.getAttribute("data-run-id");
  if (!runId) return;

  const steps = document.querySelector("[data-testid=chat-steps]");
  const ticketId = root.getAttribute("data-ticket-id");
  const cancelBtn = document.querySelector("[data-testid=run-cancel]");
  const seen = new Set();

  const STATE_ZH = {
    created: "已创建任务",
    admitted: "已受理",
    running: "开始处理",
    waiting_tool: "等待工具返回",
    waiting_approval: "等待管理员审批",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消",
  };

  function stepText(kind, data) {
    if (kind === "state") return STATE_ZH[data.status] || "状态更新";
    if (kind === "action") {
      if (data.action_kind === "tool") return "准备调用 " + (data.name || "工具");
      if (data.action_kind === "skill") return "准备执行技能 " + (data.name || "");
      if (data.action_kind === "answer") return "正在汇总答复";
      return "下一步";
    }
    if (kind === "skill") {
      return (data.matched ? "执行技能 " : "未匹配技能 ") + (data.name || "");
    }
    if (kind === "observation") {
      const flag = data.ok ? "工具成功" : "工具失败";
      return flag + "：" + (data.tool || "") + (data.code ? "（" + data.code + "）" : "");
    }
    if (kind === "retry") return "工具超时，正在重试 " + (data.tool || "");
    if (kind === "clarify") return data.message || "需要补充信息";
    if (kind === "answer") return data.text || "已给出答复";
    if (kind === "brake") return "已达步数上限，安全停止";
    if (kind === "hitl") return "权限变更草案已提交，等待审批";
    if (kind === "llm") return "已接模型 " + (data.model || "");
    if (kind === "memory") return "已记录不可信笔记";
    if (kind === "waiting_approval") return "等待管理员审批";
    return "处理中";
  }

  function appendStep(kind, data, eventId) {
    if (!steps) return;
    if (eventId != null) {
      const key = String(eventId);
      if (seen.has(key)) return;
      seen.add(key);
    }
    const el = document.createElement("div");
    el.className = "chat-step";
    el.setAttribute("data-testid", "chat-step");
    el.textContent = stepText(kind, data);
    steps.appendChild(el);
  }

  function ensureNode(testid, tag, className) {
    let el = document.querySelector("[data-testid=" + testid + "]");
    if (el) return el;
    el = document.createElement(tag);
    el.setAttribute("data-testid", testid);
    if (className) el.className = className;
    if (testid === "chat-clarify") {
      const wrap = document.createElement("div");
      wrap.className = "flash-warn";
      wrap.appendChild(el);
      root.appendChild(wrap);
    } else if (testid === "chat-deny") {
      const wrap = document.createElement("div");
      wrap.className = "flash-bad";
      wrap.appendChild(el);
      root.appendChild(wrap);
    } else {
      root.appendChild(el);
    }
    return el;
  }

  function markDone(status) {
    if (cancelBtn) cancelBtn.remove();
    if (!document.querySelector("[data-testid=run-done]")) {
      const done = document.createElement("p");
      done.className = "sr-only";
      done.setAttribute("data-testid", "run-done");
      done.textContent = status || "completed";
      root.appendChild(done);
    } else {
      document.querySelector("[data-testid=run-done]").textContent = status || "completed";
    }
  }

  function applyAnswer(data) {
    const text = data.text || data.message || "";
    if (data.code === "not_enough_info" || data.kind === "clarify") {
      ensureNode("chat-clarify", "p").textContent = text;
      return;
    }
    if (data.code === "unauthorized") {
      ensureNode("chat-deny", "p").textContent = text;
      return;
    }
    const stream = ensureNode("chat-stream", "pre", "chat-answer");
    stream.textContent = text;
  }

  async function refreshTicket() {
    if (!ticketId) return;
    const res = await fetch("/api/tickets/" + encodeURIComponent(ticketId), { credentials: "same-origin" });
    if (!res.ok) return;
    const body = await res.json();
    const ticket = body.ticket || {};
    const statusEl = document.querySelector("[data-testid=ticket-status]");
    if (statusEl && ticket.status) statusEl.textContent = ticket.status;
    const citation = document.querySelector("[data-testid=ticket-citation]");
    if (citation) {
      citation.textContent = ticket.kb_doc_id ? ticket.kb_doc_id + "@" + ticket.kb_version : "—";
    }
    const comments = document.querySelector("[data-testid=ticket-comments]");
    if (comments && Array.isArray(body.comments)) {
      comments.innerHTML = "";
      if (!body.comments.length) {
        const li = document.createElement("li");
        li.className = "empty";
        li.textContent = "暂无评论";
        comments.appendChild(li);
      } else {
        body.comments.forEach((c) => {
          const li = document.createElement("li");
          li.className = "timeline-item";
          const who = document.createElement("span");
          who.className = "mono";
          who.textContent = c.author_id;
          li.appendChild(who);
          li.appendChild(document.createTextNode(" " + c.body));
          comments.appendChild(li);
        });
      }
    }
  }

  const source = new EventSource("/api/runs/" + encodeURIComponent(runId) + "/events");

  function onFrame(ev) {
    let data = {};
    try {
      data = JSON.parse(ev.data || "{}");
    } catch {
      return;
    }
    const kind = data.kind || ev.type;
    appendStep(kind, data, ev.lastEventId || data.id);
    if (kind === "clarify" || kind === "answer") applyAnswer(Object.assign({ kind: kind }, data));
  }

  ["step", "tool", "answer", "llm", "hitl", "memory", "waiting_approval"].forEach((name) => {
    source.addEventListener(name, onFrame);
  });
  source.addEventListener("done", (ev) => {
    let data = {};
    try {
      data = JSON.parse(ev.data || "{}");
    } catch {
      data = {};
    }
    source.close();
    markDone(data.status || root.getAttribute("data-run-status") || "completed");
    refreshTicket();
    fetch("/api/runs/" + encodeURIComponent(runId), { credentials: "same-origin" })
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => {
        if (!body) return;
        if (body.status) markDone(body.status);
        if (body.final_answer) {
          applyAnswer({
            text: body.final_answer,
            code: body.outcome_code,
            kind: body.outcome_code === "not_enough_info" ? "clarify" : "answer",
          });
        }
      });
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      fetch("/api/runs/" + encodeURIComponent(runId) + "/cancel", {
        method: "POST",
        credentials: "same-origin",
      });
    });
  }
})();
