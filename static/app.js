(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    csrf: "",
    planReady: false,
    planReviewed: false,
    planHasMoves: false,
    planHasUnsubs: false,
    planApplied: false,
    configExists: false,
    busy: false,
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const clear = (node) => {
    while (node.firstChild) node.removeChild(node.firstChild);
  };

  const setStatus = (text, kind = "") => {
    const node = $("status");
    node.textContent = text;
    node.className = "badge" + (kind ? " " + kind : "");
  };

  const setBusy = (button, text) => {
    if (!button) return;
    if (text) {
      button.dataset.original = button.textContent;
      button.textContent = text;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.original || button.textContent;
      button.disabled = false;
    }
  };

  const api = async (path, body) => {
    const options = {
      method: body ? "POST" : "GET",
      headers: { Accept: "application/json" },
    };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.headers["X-CSRF-Token"] = state.csrf;
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = { ok: false, error: "Invalid response from the local app." };
    }
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
  };

  const secretBody = (body = {}) => {
    const password = $("password").value;
    if (password) body.password = password;
    return body;
  };

  const providerHints = {
    "gmail.com": "Gmail: enable IMAP and use a 16-character App Password with 2-Step Verification.",
    "googlemail.com": "Gmail: enable IMAP and use a 16-character App Password with 2-Step Verification.",
    "outlook.com": "Microsoft: use an OAuth2 access token; basic auth is disabled.",
    "hotmail.com": "Microsoft: use an OAuth2 access token; basic auth is disabled.",
    "live.com": "Microsoft: use an OAuth2 access token; basic auth is disabled.",
    "yahoo.com": "Yahoo: create an app password in Account Security.",
    "icloud.com": "iCloud: use an app-specific password; 2FA is required.",
    "me.com": "iCloud: use an app-specific password; 2FA is required.",
    "fastmail.com": "Fastmail: create a scoped app password with IMAP/SMTP access.",
    "proton.me": "Proton: run Proton Bridge and use its local password.",
    "protonmail.com": "Proton: run Proton Bridge and use its local password.",
  };

  const updateProviderHint = () => {
    const email = $("email").value.trim();
    const domain = email.includes("@") ? email.split("@").pop().toLowerCase() : "";
    $("providerHint").textContent = domain
      ? (providerHints[domain] || "Use an app password or OAuth2 token from your provider. Never your normal password.")
      : "Use an app password or OAuth2 token from your provider. Never your normal password.";
  };

  const action = async (button, label, fn) => {
    if (state.busy) return;
    state.busy = true;
    setBusy(button, label);
    setStatus(label);
    try {
      await fn();
    } catch (error) {
      showError(error && error.message ? error.message : String(error));
    } finally {
      state.busy = false;
      setBusy(button, "");
    }
  };

  const applyState = (data) => {
    state.csrf = data.csrf || state.csrf;
    state.configExists = Boolean(data.config_exists);
    state.planReady = Boolean(data.plan_ready);
    state.planReviewed = Boolean(data.plan_reviewed);
    state.planApplied = Boolean(data.plan_applied);
    $("cliPath").value = data.cli_path || "";
    $("configPath").value = data.config_path || "";
    $("envBadge").classList.toggle("hidden", !data.password_env_set);
    $("envNote").classList.toggle("hidden", !data.password_env_set);
    $("appVersion").textContent = data.app_version ? "v" + data.app_version : "";
    updateProviderHint();
    if (state.planReady) {
      $("planState").textContent = state.planApplied
        ? "Applied"
        : (state.planReviewed ? "Reviewed" : "Not reviewed");
      $("reviewPlan").checked = state.planReviewed;
      $("applyButton").disabled = !state.planReviewed || state.planApplied;
    }
  };

  const showError = (message) => {
    clear($("output"));
    $("output").append(el("p", "error", message));
    setStatus("Error", "error");
  };

  const statGrid = (entries) => {
    const grid = el("div", "stats");
    entries.forEach(([value, label]) => {
      const box = el("div", "stat");
      box.append(el("strong", "", value), el("span", "", label));
      grid.append(box);
    });
    return grid;
  };

  const table = (headers, rows, rowActions = null) => {
    const wrap = el("div", "table-wrap");
    const tableEl = el("table");
    const thead = el("thead");
    const headRow = el("tr");
    headers.forEach((header) => headRow.append(el("th", "", header)));
    if (rowActions) headRow.append(el("th", "", ""));
    thead.append(headRow);
    const tbody = el("tbody");
    rows.forEach((row, index) => {
      const tr = el("tr");
      row.forEach((cell) => tr.append(el("td", "", cell)));
      if (rowActions) {
        const cell = el("td");
        const info = rowActions[index];
        if (info) {
          const button = el("button", "button ghost small", info.label);
          button.type = "button";
          button.addEventListener("click", info.onClick);
          cell.append(button);
        }
        tr.append(cell);
      }
      tbody.append(tr);
    });
    tableEl.append(thead, tbody);
    wrap.append(tableEl);
    return wrap;
  };

  const planTables = (plan) => {
    const actions = Array.isArray(plan.actions) ? plan.actions : [];
    const moves = actions.filter((item) => item.type === "move");
    const unsubs = actions.filter((item) => item.type === "unsubscribe");
    const nodes = [];
    if (moves.length) {
      nodes.push(el("h4", "", "Moves"));
      nodes.push(table(
        ["Category", "Destination", "Messages", "Mailbox"],
        moves.map((item) => [
          item.category || "",
          item.dest || "",
          (item.uids || []).length,
          item.mailbox || "",
        ])
      ));
    }
    if (unsubs.length) {
      nodes.push(el("h4", "", "Unsubscribe requests"));
      nodes.push(table(
        ["Category", "Sender", "Mode"],
        unsubs.map((item) => [item.category || "", item.sender || item.domain || "", item.mode || ""])
      ));
    }
    return nodes;
  };

  const renderPlanSummary = (data) => {
    const plan = data.plan || {};
    const stats = plan.stats || {};
    const actions = Array.isArray(plan.actions) ? plan.actions : [];
    const moves = actions.filter((item) => item.type === "move");
    const unsubs = actions.filter((item) => item.type === "unsubscribe");
    state.planHasMoves = moves.length > 0;
    state.planHasUnsubs = unsubs.length > 0;
    state.planApplied = false;
    const summary = $("planSummary");
    clear(summary);
    summary.append(statGrid([
      [stats.messages || 0, "messages"],
      [stats.actionable || 0, "actionable"],
      [moves.length, "move actions"],
      [unsubs.length, "unsubscribe"],
    ]));
    summary.append(el("p", "muted", `Plan file: ${data.path || ""}`));
    planTables(plan).forEach((node) => summary.append(node));
    $("planPanel").classList.remove("hidden");
    $("reviewPlan").checked = false;
    $("confirmUnsub").checked = false;
    $("applyButton").disabled = true;
    $("applyButton").textContent = state.planHasMoves ? "Apply moves" : "No moves to apply";
    $("unsubscribeButton").disabled = true;
    $("unsubscribeButton").textContent = state.planHasUnsubs
      ? "Send unsubscribe requests"
      : "No unsubscribe requests";
    $("confirmUnsub").disabled = !state.planHasUnsubs;
    $("planState").textContent = "Not reviewed";
  };

  const renderPlan = (data) => {
    const output = $("output");
    clear(output);
    output.append(el("h3", "", "Plan ready — review before applying"));
    output.append(el("p", "muted", "The actions are in the Clean up panel above. Nothing has changed yet."));
    output.append(el("p", "muted", `Plan file: ${data.path || ""}`));
    renderPlanSummary(data);
  };

  const renderReport = (data) => {
    const totals = data.totals || {};
    const categories = data.categories || {};
    const groups = Array.isArray(data.groups) ? data.groups : [];
    const output = $("output");
    clear(output);
    output.append(el("h3", "", "Inbox report"));
    output.append(statGrid([
      [totals.unread || 0, "unread"],
      [totals.protected || 0, "protected"],
      [groups.length, "sender groups"],
      [data.oldest || "?", data.newest ? "oldest → " + data.newest : "oldest"],
    ]));
    if (Object.keys(categories).length) {
      const pills = el("div");
      Object.entries(categories).sort((a, b) => b[1] - a[1]).forEach(([name, count]) => {
        pills.append(el("span", "pill", `${name} ${count}`));
      });
      output.append(pills);
    }
    if (groups.length) {
      output.append(el("h3", "", "Sender groups"));
      output.append(table(
        ["Sender", "Category", "Messages", "Actionable", "Unsubscribe"],
        groups.slice(0, 50).map((group) => [
          group.domain || "",
          group.category || "",
          group.count || 0,
          group.actionable || 0,
          (group.unsubscribe && group.unsubscribe.mode) || "-",
        ])
      ));
    }
  };

  const renderScan = (data) => {
    const mailboxes = data.mailboxes || {};
    const categories = data.categories || {};
    const output = $("output");
    clear(output);
    output.append(el("h3", "", "Scan complete"));
    output.append(statGrid([
      [data.total || 0, "cached messages"],
      [Object.keys(mailboxes).length, "mailboxes"],
      [Object.keys(categories).length, "categories"],
      [Object.values(mailboxes).reduce((sum, item) => sum + (item.failed || 0), 0), "failed"],
    ]));
    output.append(table(
      ["Mailbox", "Found", "Cached", "Failed", "Pruned"],
      Object.entries(mailboxes).map(([name, item]) => [
        name,
        item.found || 0,
        item.cached || 0,
        item.failed || 0,
        item.pruned || 0,
      ])
    ));
  };

  const renderJournal = (data) => {
    const runs = Array.isArray(data.runs) ? data.runs : [];
    const output = $("output");
    clear(output);
    output.append(el("h3", "", "Undo journal"));
    if (!runs.length) {
      output.append(el("p", "muted", "No moves have been recorded yet."));
      return;
    }
    output.append(table(
      ["Run", "When", "Ops", "Messages", "Unsubs"],
      runs.map((run) => [
        run.run || "",
        (run.ts || "").slice(0, 16),
        run.ops || 0,
        run.messages || 0,
        run.unsubs || 0,
      ]),
      runs.map((run) => ({ label: "Undo", onClick: () => undoRun(run.run) }))
    ));
    output.append(el("p", "muted", "Undo restores moves and Gmail archives. Unsubscribe cannot be undone."));
  };

  const renderUndo = (data) => {
    const operations = Array.isArray(data.operations) ? data.operations : [];
    const output = $("output");
    clear(output);
    output.append(el("h3", "", "Undo complete"));
    output.append(statGrid([
      [data.restored || 0, "restored"],
      [data.failed || 0, "failed"],
      [operations.length, "operations"],
      [data.run || "", "run"],
    ]));
    if (operations.length) {
      output.append(table(
        ["Operation", "Count", "Source", "Destination"],
        operations.map((item) => [
          item.op || "",
          item.count || 0,
          item.src || item.mailbox || "",
          item.dst || "",
        ])
      ));
    }
  };

  const renderResult = (result) => {
    const data = result.data;
    if (data && data.plan) {
      renderPlan(data);
    } else if (data && data.runs) {
      renderJournal(data);
    } else if (data && data.mailboxes) {
      renderScan(data);
    } else if (data && data.totals) {
      renderReport(data);
    } else if (data && data.restored !== undefined) {
      renderUndo(data);
    } else {
      const output = $("output");
      clear(output);
      output.append(el("h3", "", result.ok ? "Done" : "The CLI returned an error"));
      if (data) {
        output.append(el("pre", "json", JSON.stringify(data, null, 2)));
      } else if (result.stdout) {
        output.append(el("pre", "json", result.stdout));
      }
    }
    if (result.stderr) {
      $("output").append(el("pre", "json", result.stderr));
    }
    if (!result.ok) {
      setStatus("Error", "error");
      $("output").append(el("p", "error", `CLI exit code ${result.exit_code}.`));
    } else {
      setStatus("Done");
    }
  };

  const saveSettings = (button) => action(button, "Saving…", async () => {
    const data = await api("/api/settings", {
      cli_path: $("cliPath").value.trim(),
      config_path: $("configPath").value.trim(),
    });
    applyState(data);
    setStatus("Saved");
    clear($("output"));
    $("output").append(el("p", "success", "Settings saved."));
  });

  const createConfig = (button) => action(button, "Creating…", async () => {
    const email = $("email").value.trim();
    if (!email || !email.includes("@")) throw new Error("Enter a valid email address.");
    const force = state.configExists
      ? window.confirm("A config file already exists. Overwrite it?")
      : false;
    if (state.configExists && !force) return;
    const result = await api("/api/init", { email, force });
    applyState(await api("/api/state"));
    renderResult(result);
  });

  const runCommand = (button, label, path, body, options = {}) => action(button, label, async () => {
    const result = await api(path, secretBody(body));
    renderResult(result);
    if (options.after) options.after(result);
  });

  const scan = (button) => runCommand(button, "Scanning…", "/api/scan", {
    days: Number($("days").value || 365),
  });

  const report = (button) => runCommand(button, "Reading…", "/api/report", {
    top: Number($("top").value || 30),
  });

  const plan = (button) => runCommand(button, "Planning…", "/api/plan", {
    mode: $("mode").value,
    categories: Array.from(document.querySelectorAll("#planCategories input:checked"))
      .map((item) => item.value),
  }, {
    after: (result) => {
      if (result.ok && result.data && result.data.plan) {
        state.planReady = true;
        state.planReviewed = false;
        state.planApplied = false;
      }
    },
  });

  const reviewPlan = async () => {
    const checked = $("reviewPlan").checked;
    try {
      await api("/api/plan/review", { reviewed: checked });
      state.planReviewed = checked;
      $("applyButton").disabled = !checked || !state.planHasMoves || state.planApplied;
      $("planState").textContent = checked ? "Reviewed" : "Not reviewed";
    } catch (error) {
      $("reviewPlan").checked = !checked;
      showError(error.message || String(error));
    }
  };

  const applyMoves = (button) => {
    if (!$("reviewPlan").checked) return;
    if (!window.confirm("Apply the planned moves? This changes your mailbox. Moves are reversible.")) return;
    action(button, "Applying…", async () => {
      const result = await api("/api/apply", secretBody({
        confirm: "APPLY",
        limit: Number($("applyLimit").value || 50),
      }));
      $("reviewPlan").checked = false;
      $("applyButton").disabled = true;
      $("planState").textContent = "Applied";
      state.planReviewed = false;
      state.planApplied = true;
      renderResult(result);
    });
  };

  const unsubscribe = (button) => {
    if (!$("confirmUnsub").checked) return;
    if (!window.confirm("Send unsubscribe requests? This cannot be undone.")) return;
    action(button, "Sending…", async () => {
      const result = await api("/api/unsubscribe", secretBody({
        confirm: "UNSUBSCRIBE",
        limit: Number($("unsubLimit").value || 10),
      }));
      renderResult(result);
    });
  };

  const showJournal = (button) => runCommand(button, "Loading…", "/api/journal", {});

  const undoRun = async (run) => {
    if (!window.confirm(`Restore run ${run}? This moves messages back.`)) return;
    try {
      const result = await api("/api/undo", secretBody({ confirm: "UNDO", run }));
      renderResult(result);
    } catch (error) {
      showError(error.message || String(error));
    }
  };

  const lock = (button) => action(button, "Locking…", async () => {
    await api("/api/lock", {});
    state.csrf = "";
    $("password").value = "";
    clear($("output"));
    $("output").append(el("p", "success", "Session ended. Close this tab and restart the app to open a new session."));
    setStatus("Locked");
    document.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  });

  const wire = () => {
    $("email").addEventListener("input", updateProviderHint);
    $("saveSettings").addEventListener("click", () => saveSettings($("saveSettings")));
    $("createConfig").addEventListener("click", () => createConfig($("createConfig")));
    $("validate").addEventListener("click", () => runCommand($("validate"), "Validating…", "/api/validate", {}));
    $("doctor").addEventListener("click", () => runCommand($("doctor"), "Connecting…", "/api/doctor", {}));
    $("scan").addEventListener("click", () => scan($("scan")));
    $("report").addEventListener("click", () => report($("report")));
    $("plan").addEventListener("click", () => plan($("plan")));
    $("reviewPlan").addEventListener("change", reviewPlan);
    $("applyButton").addEventListener("click", () => applyMoves($("applyButton")));
    $("confirmUnsub").addEventListener("change", () => {
      $("unsubscribeButton").disabled = !$("confirmUnsub").checked || !state.planHasUnsubs;
    });
    $("unsubscribeButton").addEventListener("click", () => unsubscribe($("unsubscribeButton")));
    $("journalButton").addEventListener("click", () => showJournal($("journalButton")));
    $("lockButton").addEventListener("click", () => lock($("lockButton")));
  };

  const init = async () => {
    wire();
    try {
      const data = await api("/api/state");
      applyState(data);
      setStatus("Ready");
    } catch (error) {
      showError(error.message || String(error));
    }
  };

  init();
})();
