/* LabelCheck frontend. No framework, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);

/* tabs */
$("tab-single").addEventListener("click", () => switchTab("single"));
$("tab-batch").addEventListener("click", () => switchTab("batch"));

function switchTab(name) {
  $("tab-single").classList.toggle("active", name === "single");
  $("tab-batch").classList.toggle("active", name === "batch");
  $("view-single").hidden = name !== "single";
  $("view-batch").hidden = name !== "batch";
}

/* helpers */
const VERDICT_LABEL = {
  match: "OK",
  review: "REVIEW",
  mismatch: "MISMATCH",
  not_found: "NOT ON LABEL",
  not_applicable: "N/A",
  error: "ERROR",
};

function chip(verdict) {
  const span = document.createElement("span");
  span.className = `chip ${verdict}`;
  span.textContent = VERDICT_LABEL[verdict] || verdict;
  return span;
}

function bannerClass(verdict) {
  if (verdict === "match") return "ok";
  if (verdict === "review") return "review";
  return "bad";
}

const BANNER_TEXT = {
  match: "Match: label agrees with the application",
  review: "Needs review: some fields require a judgment call",
  mismatch: "Mismatch: label disagrees with the application",
  not_found: "Mismatch: required items are missing from the label",
};

function showError(id, message) {
  const el = $(id);
  el.textContent = message;
  el.hidden = false;
}
function hideError(id) { $(id).hidden = true; }

/* samples and image input */
let sampleState = null; // { name, imageUrl } when a built-in sample is active

async function loadSamples() {
  try {
    const res = await fetch("/api/samples");
    const samples = await res.json();
    for (const s of samples) {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = s.title;
      opt.dataset.payload = JSON.stringify(s);
      $("sample-select").appendChild(opt);
    }
  } catch {
    /* samples are a convenience; ignore load failures */
  }
}
loadSamples();

$("sample-select").addEventListener("change", async (e) => {
  const opt = e.target.selectedOptions[0];
  const payload = opt && opt.dataset.payload ? JSON.parse(opt.dataset.payload) : null;
  clearImage();
  if (!payload) return;

  $("f-brand_name").value = payload.application.brand_name || "";
  $("f-class_type").value = payload.application.class_type ?? payload.application["class/type"] ?? "";
  $("f-alcohol_pct").value = payload.application.alcohol_pct ?? "";
  $("f-net_contents_ml").value = payload.application.net_contents_ml ?? "";
  $("f-bottler_name").value = payload.application.bottler_name || "";
  $("f-bottler_address").value = payload.application.bottler_address || "";
  const imported = !!payload.application.is_import;
  $("f-is_import").checked = imported;
  $("country-wrap").hidden = !imported;
  $("f-country_of_origin").value = payload.application.country_of_origin || "";

  const url = `/api/samples/${encodeURIComponent(payload.name)}/image`;
  $("preview").src = url;
  $("preview").hidden = false;
  $("dropzone-hint").hidden = true;
  sampleState = { name: payload.name, imageUrl: url };
});

/* image input + drag & drop */
const dropzone = $("dropzone");
let imageFile = null;

function setImage(file) {
  if (!file) return;
  if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) {
    showError("single-error", "That file type is not supported. Please use PNG, JPEG, or WebP.");
    return;
  }
  hideError("single-error");
  imageFile = file;
  sampleState = null;
  $("sample-select").value = "";
  $("preview").src = URL.createObjectURL(file);
  $("preview").hidden = false;
  $("dropzone-hint").hidden = true;
}
function clearImage() {
  imageFile = null;
  sampleState = null;
  $("preview").hidden = true;
  $("preview").removeAttribute("src");
  $("dropzone-hint").hidden = false;
}

$("image-input").addEventListener("change", (e) => setImage(e.target.files[0]));
["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); })
);
dropzone.addEventListener("drop", (e) => setImage(e.dataTransfer.files[0]));

$("f-is_import").addEventListener("change", (e) => {
  $("country-wrap").hidden = !e.target.checked;
});

/* single-label verification */
$("verify-btn").addEventListener("click", verifySingle);

async function verifySingle() {
  hideError("single-error");
  const btn = $("verify-btn");
  const missing = [];
  const need = [
    ["f-brand_name", "Brand name"],
    ["f-class_type", "Class / type"],
    ["f-alcohol_pct", "Alcohol content"],
    ["f-net_contents_ml", "Net contents"],
    ["f-bottler_name", "Bottler name"],
    ["f-bottler_address", "Bottler address"],
  ];
  for (const [id, label] of need) if (!$(id).value.trim()) missing.push(label);
  if (missing.length) {
    showError("single-error", `Please fill in: ${missing.join(", ")}.`);
    return;
  }

  let blob = imageFile;
  if (!blob && sampleState) {
    try {
      const res = await fetch(sampleState.imageUrl);
      blob = await res.blob();
    } catch {
      showError("single-error", "Could not load the sample image.");
      return;
    }
  }
  if (!blob) {
    showError("single-error", "Please choose a label image first (or pick a built-in sample).");
    return;
  }

  const application = {
    brand_name: $("f-brand_name").value.trim(),
    "class/type": $("f-class_type").value.trim(),
    alcohol_pct: parseFloat($("f-alcohol_pct").value),
    net_contents_ml: parseFloat($("f-net_contents_ml").value),
    bottler_name: $("f-bottler_name").value.trim(),
    bottler_address: $("f-bottler_address").value.trim(),
    is_import: $("f-is_import").checked,
    country_of_origin: $("f-is_import").checked ? $("f-country_of_origin").value.trim() : null,
  };

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Checking…';
  $("single-results").innerHTML = '<p class="placeholder">Reading the label…</p>';
  const started = performance.now();

  try {
    const form = new FormData();
    const ext = blob.type === "image/jpeg" ? "jpg" : blob.type.split("/")[1];
    form.append("image", blob, `label.${ext}`);
    form.append("application", JSON.stringify(application));

    const res = await fetch("/api/verify", { method: "POST", body: form });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `Server error (${res.status})`);
    }
    const result = await res.json();
    renderSingleResult(result, performance.now() - started);
  } catch (err) {
    showError("single-error", `Could not verify the label: ${err.message}`);
    $("single-results").innerHTML = '<p class="placeholder">Results will appear here.</p>';
  } finally {
    btn.disabled = false;
    btn.textContent = "Verify label";
  }
}

function renderSingleResult(result, uiElapsedMs) {
  const panel = $("single-results");
  panel.innerHTML = "";

  const head = document.createElement("div");
  head.className = `banner ${bannerClass(result.overall)}`;
  head.textContent = BANNER_TEXT[result.overall] || result.overall;
  const sub = document.createElement("span");
  sub.className = "sub";
  sub.textContent =
    result.overall === "match"
      ? "No discrepancies found against the application data."
      : "See the notes below for context. Final approval always stays with a human reviewer.";
  head.appendChild(sub);
  panel.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "meta-row";
  const secs = (result.elapsed_ms / 1000).toFixed(1);
  const target = result.elapsed_ms <= 5000 ? "(within the 5-second target)" : "(slower than the 5-second target)";
  meta.innerHTML = `<span>Processed in <strong>${secs} s</strong> ${target}</span>`;
  panel.appendChild(meta);

  const table = document.createElement("table");
  table.className = "checks";
  table.innerHTML =
    "<thead><tr><th>Status</th><th>Field</th><th>Application vs. label</th><th>Notes</th></tr></thead>";
  const body = document.createElement("tbody");
  for (const check of result.checks) {
    const tr = document.createElement("tr");

    const tdStatus = document.createElement("td");
    tdStatus.appendChild(chip(check.verdict));

    const tdField = document.createElement("td");
    tdField.textContent = check.label;

    const tdVals = document.createElement("td");
    tdVals.className = "vals";
    if (check.verdict !== "not_applicable") {
      const exp = document.createElement("div");
      exp.innerHTML = `<span class="who">Application:</span> ${escapeHtml(truncate(check.expected, 300))}`;
      const fnd = document.createElement("div");
      fnd.innerHTML = `<span class="who">Label:</span> ${escapeHtml(truncate(check.found, 300))}`;
      tdVals.append(exp, fnd);
    } else {
      tdVals.textContent = "n/a";
    }

    const tdNote = document.createElement("td");
    tdNote.className = "note";
    tdNote.textContent = check.note || "";

    tr.append(tdStatus, tdField, tdVals, tdNote);
    body.appendChild(tr);
  }
  table.appendChild(body);
  panel.appendChild(table);

  if (result.ocr_text) {
    const det = document.createElement("details");
    det.className = "ocr";
    det.innerHTML = `<summary>Show the text read from the label (OCR)</summary>`;
    const pre = document.createElement("pre");
    pre.textContent = result.ocr_text;
    det.appendChild(pre);
    panel.appendChild(det);
  }
}

function truncate(text, n) {
  if (text == null) return "(not found)";
  return text.length > n ? text.slice(0, n) + "…" : text;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/* batch check */
let csvFile = null;
let imageFiles = [];

$("csv-input").addEventListener("change", (e) => {
  csvFile = e.target.files[0] || null;
  $("csv-name").textContent = csvFile ? csvFile.name : "";
});
$("images-input").addEventListener("change", (e) => {
  imageFiles = Array.from(e.target.files || []);
  $("images-name").textContent = imageFiles.length
    ? `${imageFiles.length} image${imageFiles.length > 1 ? "s" : ""} selected`
    : "";
});

let pollTimer = null;
$("batch-btn").addEventListener("click", async () => {
  hideError("batch-error");
  if (!csvFile) return showError("batch-error", "Please choose the application CSV file first.");
  if (!imageFiles.length) return showError("batch-error", "Please choose the label image files.");

  const btn = $("batch-btn");
  btn.disabled = true;
  btn.textContent = "Uploading…";
  $("batch-results").hidden = false;
  $("batch-summary").innerHTML = "";
  $("download-btn").hidden = true;
  setProgress(0, 0);

  try {
    const form = new FormData();
    form.append("csv_file", csvFile, csvFile.name);
    for (const f of imageFiles) form.append("images", f, f.name);

    const res = await fetch("/api/batch", { method: "POST", body: form });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `Server error (${res.status})`);
    }
    const { job_id, total } = await res.json();
    btn.textContent = "Checking…";
    pollTimer = setInterval(() => pollJob(job_id, total, btn), 700);
  } catch (err) {
    showError("batch-error", `Could not start the batch: ${err.message}`);
    resetBatchBtn();
  }
});

async function pollJob(jobId, total, btn) {
  let job;
  try {
    const res = await fetch(`/api/batch/${jobId}`);
    if (!res.ok) throw new Error(`job status ${res.status}`);
    job = await res.json();
  } catch (err) {
    clearInterval(pollTimer);
    showError("batch-error", `Lost track of the batch job: ${err.message}`);
    resetBatchBtn();
    return;
  }

  setProgress(job.done, job.total || total);
  if (job.status !== "complete") return;

  clearInterval(pollTimer);
  resetBatchBtn();
  renderBatchResults(job);
}

function resetBatchBtn() {
  const btn = $("batch-btn");
  btn.disabled = false;
  btn.textContent = "Start batch check";
}

function setProgress(done, total) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("progress-fill").style.width = pct + "%";
  $("progress-text").textContent = `${done} / ${total} (${pct}%)`;
}

function renderBatchResults(job) {
  const rows = [...job.results, ...job.errors];
  const counts = { match: 0, review: 0, mismatch: 0, error: 0 };
  for (const r of rows) {
    if (r.overall === "error") counts.error++;
    else if (r.overall === "match") counts.match++;
    else if (r.overall === "review") counts.review++;
    else counts.mismatch++; // mismatch / not_found
  }

  const summary = $("batch-summary");
  summary.innerHTML = "";
  const labels = {
    match: ["Match", "ok"],
    review: ["Needs review", "review"],
    mismatch: ["Mismatch", "bad"],
    error: ["Errors", "err"],
  };
  for (const [key, [text, cls]] of Object.entries(labels)) {
    if (!counts[key] && key === "error") continue;
    const pill = document.createElement("div");
    pill.className = `summary-pill ${cls}`;
    pill.textContent = `${counts[key]} ${text}`;
    summary.appendChild(pill);
  }

  const tbody = $("batch-table").querySelector("tbody");
  tbody.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    idCell.textContent = r.application_id || "(no id)";
    const imgCell = document.createElement("td");
    imgCell.textContent = r.image || "";
    const verdictCell = document.createElement("td");
    if (r.overall === "error") {
      verdictCell.appendChild(chip("error"));
    } else {
      verdictCell.appendChild(chip(r.overall === "not_found" ? "mismatch" : r.overall));
    }
    const probCell = document.createElement("td");
    probCell.className = "problems";
    if (r.overall === "error") {
      probCell.textContent = r.error || "";
    } else {
      const bad = (r.checks || []).filter(
        (c) => c.verdict !== "match" && c.verdict !== "not_applicable"
      );
      probCell.textContent = bad.length
        ? bad.map((c) => `${c.label}${c.verdict === "review" ? " (review)" : ""}`).join("; ")
        : "None";
    }
    const timeCell = document.createElement("td");
    timeCell.textContent = r.elapsed_ms ? `${(r.elapsed_ms / 1000).toFixed(1)} s` : "";

    tr.append(idCell, imgCell, verdictCell, probCell, timeCell);
    tbody.appendChild(tr);
  }

  const dl = $("download-btn");
  dl.hidden = false;
  dl.onclick = () => downloadReport(rows);
}

function downloadReport(rows) {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = ["application_id,image,overall,attention,elapsed_ms"];
  for (const r of rows) {
    let attention = r.error || "";
    if (!attention && r.checks) {
      attention = r.checks
        .filter((c) => c.verdict !== "match" && c.verdict !== "not_applicable")
        .map((c) => `${c.label}: ${c.verdict} (${c.note || ""})`)
        .join(" | ");
    }
    lines.push(
      [esc(r.application_id), esc(r.image), esc(r.overall), esc(attention), r.elapsed_ms ?? ""].join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "labelcheck-report.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
