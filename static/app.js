let lrcResult = "";
let lastJobId = "";
let lastSyncFilename = "";
let paxSyncJson = "";
let lastLrclibSearchResults = [];

let displayedPercent = 0;
let targetPercent = 0;
let rafId = null;
let lastFrameAt = 0;

function animateProgress() {
    if (rafId !== null) return;
    lastFrameAt = performance.now();
    const step = (now) => {
        const dt = Math.min(200, now - lastFrameAt);
        lastFrameAt = now;
        const delta = targetPercent - displayedPercent;
        if (Math.abs(delta) < 0.2) {
            displayedPercent = targetPercent;
            renderProgress(displayedPercent);
            rafId = null;
            return;
        }
        // Exponential ease-out; time constant ~150ms so every update eases smoothly
        displayedPercent += delta * (1 - Math.exp(-dt / 150));
        renderProgress(displayedPercent);
        rafId = requestAnimationFrame(step);
    };
    rafId = requestAnimationFrame(step);
}

function renderProgress(percent) {
    const fill = document.getElementById("progressFill");
    fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
}

function showProgress(percent, message) {
    const wrap = document.getElementById("progressWrap");
    const label = document.getElementById("progressLabel");
    wrap.style.display = "block";
    targetPercent = Math.min(100, Math.max(0, percent));
    animateProgress();
    const pct = Math.round(targetPercent);
    label.textContent = /\d+%/.test(message) ? message : `${message} (${pct}%)`;
}

function hideProgress() {
    document.getElementById("progressWrap").style.display = "none";
    if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
    displayedPercent = 0;
    targetPercent = 0;
}

function showTab(name) {
    const panels = {
        main: 'tabMainPanel',
        advanced: 'tabAdvancedPanel',
        paxsenix: 'tabPaxsenixPanel',
        lrclib: 'tabLrclibPanel',
        check: 'tabCheckPanel',
    };
    for (const [key, panelId] of Object.entries(panels)) {
        document.getElementById(panelId).style.display = name === key ? '' : 'none';
    }
    document.getElementById('tabMain').classList.toggle('active', name === 'main');
    document.getElementById('tabAdvanced').classList.toggle('active', name === 'advanced');
    document.getElementById('tabPaxsenix').classList.toggle('active', name === 'paxsenix');
    document.getElementById('tabLrclib').classList.toggle('active', name === 'lrclib');
    document.getElementById('tabCheck').classList.toggle('active', name === 'check');
    // Whisper controls only belong to the alignment flow.
    const isAlignTab = name === 'main' || name === 'advanced';
    document.getElementById('whisperActions').style.display = isAlignTab ? '' : 'none';
    if (name === 'lrclib') {
        // Hand a freshly generated LRC over, but never clobber typed or loaded text.
        const box = document.getElementById('lrclibLrc');
        if (box && !box.value.trim() && lrcResult) box.value = lrcResult;
        syncLrclibFields('search');
    }
    if (name === 'check') syncLrclibFields('lrclib');
}

function updateEnWarning() {
    const model = document.getElementById("model")?.value || "";
    const warn = document.getElementById("enWarning");
    if (!warn) return;
    warn.style.display = model.endsWith(".en") ? "block" : "none";
}

function resetLanguageDropdown() {
    const langSelect = document.getElementById("language");
    if (!langSelect) return;
    const autoOpt = Array.from(langSelect.options).find(o => o.dataset.detectedApplied);
    if (autoOpt) {
        autoOpt.text = autoOpt.dataset.originalText || "Auto-detect";
        autoOpt.value = "";
        delete autoOpt.dataset.detectedApplied;
    }
    langSelect.value = "";
}

const hfTokenBox = document.getElementById("hfToken");
if (hfTokenBox) {
    if (localStorage.getItem("hfToken")) hfTokenBox.value = localStorage.getItem("hfToken");
    hfTokenBox.addEventListener("input", () => localStorage.setItem("hfToken", hfTokenBox.value));
}

const lyricsBox = document.getElementById("lyrics");
if (lyricsBox) lyricsBox.addEventListener("input", resetLanguageDropdown);

// Search and Upload panels share the same song fields — keep each pair in sync.
const lrclibPairs = [["lrclibTrack", "searchTrack"], ["lrclibArtist", "searchArtist"], ["lrclibDuration", "searchDuration"], ["lrclibAlbum", "searchAlbum"]];
function syncLrclibFields(from) {
    const fromSearch = from === "search" || (from && from.startsWith("search"));
    for (const [a, b] of lrclibPairs) {
        const elA = document.getElementById(a);
        const elB = document.getElementById(b);
        if (!elA || !elB) continue;
        const src = fromSearch ? elB : elA;
        const dst = fromSearch ? elA : elB;
        if (from) dst.value = src.value;
        else if (!dst.value) dst.value = src.value;
        else if (!src.value) src.value = dst.value;
    }
    const hintA = document.getElementById("lrclibDurationHint");
    const hintB = document.getElementById("searchDurationHint");
    if (hintA && hintB) (fromSearch ? hintA : hintB).textContent = (fromSearch ? hintB : hintA).textContent;
}
for (const [a, b] of lrclibPairs) {
    for (const [id, other] of [[a, b], [b, a]]) {
        const el = document.getElementById(id);
        if (el) el.addEventListener("input", () => syncLrclibFields(id));
    }
}

// LRC files in the wild are often Shift-JIS, which FileReader's UTF-8 default
// turns into mojibake, so try each encoding strictly and keep the first that
// decodes cleanly.
function decodeLyrics(buffer) {
    for (const encoding of ["utf-8", "shift_jis", "windows-1252"]) {
        try {
            return new TextDecoder(encoding, { fatal: true }).decode(buffer);
        } catch (e) {
            // wrong encoding, try the next one
        }
    }
    return new TextDecoder().decode(buffer);
}

function validateLrc(text) {
    const duplicates = [], out_of_order = [];
    let prev = null, maxSoFar = null;
    text.split("\n").forEach((line, idx) => {
        const m = line.match(/\[(\d{2}):(\d{2})\.(\d{2})\]/);
        if (!m) return;
        const t = (+m[1]) * 60 + (+m[2]) + (+m[3]) / 100;
        if (prev !== null && t === prev) duplicates.push(idx + 1);
        else if (maxSoFar !== null && t < maxSoFar) out_of_order.push(idx + 1);
        prev = t;
        maxSoFar = maxSoFar === null ? t : Math.max(maxSoFar, t);
    });
    return { duplicates, out_of_order };
}

function lrcIssuesText(v, text) {
    const lines = text != null ? String(text).split("\n") : null;
    const fmt = (nums) => {
        const arr = nums || [];
        const shown = arr.slice(0, 3).map((n) => {
            if (!lines) return `line ${n}`;
            return `line ${n}: "${((lines[n - 1] || "").trim().slice(0, 60))}"`;
        });
        return shown.join(", ") + (arr.length > 3 ? ` (+${arr.length - 3} more)` : "");
    };
    const parts = [];
    if ((v.duplicates || []).length) parts.push(`duplicates ${fmt(v.duplicates)}`);
    if ((v.out_of_order || []).length) parts.push(`out of order ${fmt(v.out_of_order)}`);
    return parts.join("; ");
}

function setPublishEnabled(ok) {
    const btn = document.getElementById("lrclibPublishBtn");
    if (btn) btn.disabled = !ok;
}

function updateLrcIssues() {
    const box = document.getElementById("lrclibLrc");
    const v = box ? box.value : "";
    const issues = lrcIssuesText(validateLrc(v), v);
    const el = document.getElementById("lrclibIssues");
    if (el) el.textContent = issues;
    setPublishEnabled(!issues);
    return issues;
}

const lrclibFileBox = document.getElementById("lrclibFile");
if (lrclibFileBox) {
    lrclibFileBox.addEventListener("change", () => {
        const file = lrclibFileBox.files[0];
        const box = document.getElementById("lrclibLrc");
        const status = document.getElementById("lrclibStatus");
        if (!file || !box) return;
        const reader = new FileReader();
        reader.onload = () => {
            box.value = decodeLyrics(reader.result);
            updateLrcIssues();
            if (status) {
                const lines = box.value.split("\n").filter((l) => l.trim()).length;
                status.textContent = `Loaded ${file.name} — ${lines} non-empty line${lines === 1 ? "" : "s"}.`;
            }
        };
        reader.onerror = () => {
            if (status) status.textContent = `Could not read ${file.name}.`;
        };
        reader.readAsArrayBuffer(file);
    });
}

const lrclibLrcBox = document.getElementById("lrclibLrc");
if (lrclibLrcBox) lrclibLrcBox.addEventListener("input", updateLrcIssues);

const downloadModelsBtn = document.getElementById("downloadModelsBtn");
if (downloadModelsBtn) {
    downloadModelsBtn.addEventListener("click", async () => {
        const st = document.getElementById("downloadModelsStatus");
        downloadModelsBtn.disabled = true;
        try {
            const r = await fetch("/api/models/download-all", { method: "POST" });
            if (!r.ok) {
                const d = await r.json().catch(() => ({}));
                throw new Error(d.error || "Failed to start download");
            }
            if (st) st.textContent = "Starting model downloads...";
            while (true) {
                await new Promise((r2) => setTimeout(r2, 1000));
                const s = await fetch("/api/models/download-status");
                const d = await s.json();
                if (d.need_token) {
                    const ov = document.getElementById("tokenOverlay");
                    const msg = document.getElementById("tokenMsg");
                    if (msg) msg.textContent = `Model "${d.need_token}" is not downloaded. Enter an HF token to continue, or continue without one.`;
                    if (ov) ov.style.display = "flex";
                    await new Promise((r2) => { window._tokenResolved = r2; });
                    continue;
                }
                if (st) {
                    if (d.running) {
                        st.textContent = `Downloading '${d.current || "..."}'... (${(d.downloaded || []).length}/${d.total} done)`;
                    } else if (d.done) {
                        const errs = Object.keys(d.errors || {});
                        st.textContent = `Done. Downloaded ${(d.downloaded || []).length}/${d.total} models.` + (errs.length ? ` Errors: ${errs.join(", ")}` : "");
                        break;
                    }
                }
                if (!d.running && d.done) break;
            }
        } catch (e) {
            if (st) st.textContent = `Error: ${e.message}`;
        } finally {
            downloadModelsBtn.disabled = false;
        }
    });
}

async function submitHfToken(withToken) {
    const ov = document.getElementById("tokenOverlay");
    const input = document.getElementById("tokenInput");
    const token = withToken && input ? input.value.trim() : "";
    try {
        const fd = new FormData();
        fd.append("token", token);
        await fetch("/api/token", { method: "POST", body: fd });
    } catch (e) {}
    if (ov) ov.style.display = "none";
    if (!withToken) {
        const error = document.getElementById("error");
        if (error) error.textContent = "Continuing without HF token — download may fail for gated models.";
    }
    // Resume the job poll that is waiting on the token prompt.
    if (window._tokenResolved) {
        const r = window._tokenResolved;
        window._tokenResolved = null;
        r();
    }
}

async function cancelJob() {
    const cancelBtn = document.getElementById("cancelBtn");
    if (!lastJobId) return;
    try {
        await fetch(`/api/jobs/${lastJobId}/cancel`, { method: "POST" });
    } catch (e) {
        // best effort
    }
    if (cancelBtn) cancelBtn.style.display = "none";
    hideProgress();
    const alignBtn = document.getElementById("alignBtn");
    if (alignBtn) alignBtn.disabled = false;
}

async function align() {
    const audioInput = document.getElementById("audio");
    const youtubeUrl = document.getElementById("youtubeUrl").value.trim();
    const lyrics = document.getElementById("lyrics").value;
    const model = document.getElementById("model").value;
    const method = document.getElementById("method")?.value || "stable-ts";
    const language = document.getElementById("language").value || null;
    const offset = parseFloat(document.getElementById("offset").value) || 0;
    const temperature = parseFloat(document.getElementById("temperature").value) || 0;
    const beamSize = parseInt(document.getElementById("beamSize").value, 10) || 5;
    const bestOf = parseInt(document.getElementById("bestOf").value, 10) || 5;

    const status = document.getElementById("status");
    const error = document.getElementById("error");
    const resultCard = document.getElementById("resultCard");
    const result = document.getElementById("result");
    const btn = document.getElementById("alignBtn");

    // Validation
    const hasAudio = audioInput.files.length > 0;
    const hasYoutube = youtubeUrl.length > 0;
    if (!hasAudio && !hasYoutube) {
        error.textContent = "Please select an audio file or enter a YouTube URL.";
        return;
    }
    if (!lyrics.trim()) {
        error.textContent = "Please enter lyrics.";
        return;
    }

    // UI state
    error.textContent = "";
    btn.disabled = true;
    resultCard.style.display = "none";
    showProgress(0, "Starting...");

    // Build form data (one endpoint handles both file and YouTube)
    const formData = new FormData();
    if (hasYoutube) {
        formData.append("url", youtubeUrl);
    } else {
        formData.append("audio", audioInput.files[0]);
    }
    formData.append("lyrics", lyrics);
    formData.append("model", model);
    formData.append("method", method);
    if (language) formData.append("language", language);
    formData.append("offset", offset);
    formData.append("temperature", temperature);
    formData.append("beam_size", beamSize);
    formData.append("best_of", bestOf);
    formData.append("separate_vocals", document.getElementById("separateVocals").checked);
    // Matching knobs: server defaults are the tuned values, so only send
    // overrides when the user has actually changed them.
    const simEl = document.getElementById("similarity");
    if (simEl && simEl.value) formData.append("similarity", simEl.value);
    const thrEl = document.getElementById("acceptThreshold");
    const DEFAULT_ACCEPT_THRESHOLD = 0.4;
    if (thrEl && thrEl.value &&
        Math.abs(parseFloat(thrEl.value) - DEFAULT_ACCEPT_THRESHOLD) > 1e-9) {
        formData.append("accept_threshold", thrEl.value);
    }

    try {
        // Start job
        let response = await fetch("/api/jobs", {
            method: "POST",
            body: formData,
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || `Server error: ${response.status}`);
        }
        const { job_id } = await response.json();
        window._tokenAskedForJob = false;
        window._tokenJobModel = null;
        window._tokenResolved = null;
        lastJobId = job_id;
        // Reset per-run state so a previous song's name can't leak into this one.
        lastSyncFilename = "";
        const cancelBtn = document.getElementById("cancelBtn");
        if (cancelBtn) cancelBtn.style.display = "block";

        // Poll until done
        while (true) {
            await new Promise((r) => setTimeout(r, 250));
            const poll = await fetch(`/api/jobs/${job_id}`);
            if (!poll.ok) throw new Error(`Job lost: ${poll.status}`);
            const job = await poll.json();

            if (job.stage === "error" || job.error) {
                throw new Error(job.error || job.message);
            }
            // Track the real download name as soon as the server knows it, so
            // the sync button label updates even if polling ends early.
            if (job.sync_filename) lastSyncFilename = job.sync_filename;
            if (job.stage === "cancelled") {
                status.textContent = "Cancelled.";
                error.textContent = "";
                hideProgress();
                btn.disabled = false;
                const cancelBtn = document.getElementById("cancelBtn");
                if (cancelBtn) cancelBtn.style.display = "none";
                return;
            }
            if (job.need_token) {
                if (window._tokenJobModel !== job.need_token) {
                    window._tokenJobModel = job.need_token;
                    const ov = document.getElementById("tokenOverlay");
                    const msg = document.getElementById("tokenMsg");
                    if (msg) msg.textContent = `Model "${job.need_token}" is not downloaded. Enter an HF token to continue, or continue without one.`;
                    if (ov) ov.style.display = "flex";
                    // Wait for the user to resolve the token prompt, then
                    // resume polling this job instead of leaving the UI stuck.
                    await new Promise((r) => { window._tokenResolved = r; });
                }
                continue;
            } else {
                window._tokenJobModel = null;
            }
            if (job.detected_language) {
                const langSelect = document.getElementById("language");
                if (langSelect) {
                    const autoOpt = Array.from(langSelect.options).find(o => o.value === "" || o.dataset.detectedApplied);
                    if (autoOpt && !autoOpt.dataset.detectedApplied) {
                        const detectedOpt = Array.from(langSelect.options).find(o => o.value === job.detected_language);
                        if (!autoOpt.dataset.originalText) autoOpt.dataset.originalText = autoOpt.text;
                        autoOpt.text = (detectedOpt ? detectedOpt.text : job.detected_language) + " (Detected)";
                        autoOpt.value = job.detected_language;
                        autoOpt.dataset.detectedApplied = "1";
                    }
                    langSelect.value = job.detected_language;
                }
            }
            showProgress(job.percent || 0, job.message || job.stage);

            const wordsBtn = document.getElementById("wordsBtn");
            const syncBtn = document.getElementById("syncBtn");
            if (wordsBtn) wordsBtn.style.display = job.character_level ? "" : "none";
            if (syncBtn) {
                syncBtn.style.display = job.character_level ? "" : "none";
                syncBtn.onclick = downloadSync;
            }

            if (job.done) {
                const cancelBtn = document.getElementById("cancelBtn");
                if (cancelBtn) cancelBtn.style.display = "none";
                lrcResult = job.lrc || "";
                paxSyncJson = "";
                result.textContent = lrcResult;
                resultCard.style.display = "block";
                status.textContent = "Done!";
                if (job.warnings && job.warnings.length) {
                    status.textContent += " (" + job.warnings.join("; ") + ")";
                }
                hideProgress();
                btn.disabled = false;
                if (job.sync_filename) updateSyncButtonLabel(job.sync_filename);
                autofillDuration(job.duration);
                break;
            }
        }
    } catch (e) {
        error.textContent = `Error: ${e.message}`;
        status.textContent = "";
        hideProgress();
    } finally {
        btn.disabled = false;
    }
}

// Never clobber a value the user typed — only fill an empty field.
function autofillDuration(duration) {
    if (!duration || !isFinite(duration) || duration <= 0) return;
    const field = document.getElementById("lrclibDuration");
    if (!field) return;
    const current = parseFloat(field.value);
    if (current && current > 0) return;
    field.value = Math.round(duration);
    const hint = document.getElementById("lrclibDurationHint");
    if (hint) hint.textContent = `auto-filled from audio length (${duration.toFixed(1)}s)`;
    syncLrclibFields("lrclib");
}

function updateSyncButtonLabel(filename) {
    const btn = document.getElementById("syncBtn");
    if (btn) btn.textContent = `Download ${filename}`;
}

function downloadLRC() {
    if (!lrcResult) return;
    const blob = new Blob([lrcResult], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "lyrics.lrc";
    a.click();
    URL.revokeObjectURL(url);
}

async function downloadWords() {
    if (!lastJobId) return;
    if (document.getElementById("resultCard").style.display === "none") return;
    const status = document.getElementById("status");
    try {
        const response = await fetch(`/api/jobs/${lastJobId}/words`);
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "words.json";
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        if (status) status.textContent = `Words download failed: ${e.message}`;
    }
}

async function downloadSync() {
    if (!lastJobId) return;
    if (document.getElementById("resultCard").style.display === "none") return;
    const status = document.getElementById("status");
    try {
        const response = await fetch(`/api/jobs/${lastJobId}/sync`);
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = lastSyncFilename || "audio_sync.json";
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        if (status) status.textContent = `Sync download failed: ${e.message}`;
    }
}

async function downloadPaxSync() {
    if (!paxSyncJson) return;
    const blob = new Blob([paxSyncJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "paxsenix_sync.json";
    a.click();
    URL.revokeObjectURL(url);
}

async function fetchPaxsenix() {
    const input = document.getElementById("paxId").value.trim();
    const status = document.getElementById("paxStatus");
    const error = document.getElementById("paxError");
    const badge = document.getElementById("paxBadge");
    const btn = document.getElementById("paxFetchBtn");
    const resultCard = document.getElementById("resultCard");
    const result = document.getElementById("result");

    if (!input) {
        error.textContent = "Paste an Apple Music track URL or ID.";
        return;
    }
    error.textContent = "";
    if (badge) badge.textContent = "";
    btn.disabled = true;
    status.textContent = "Fetching from Paxsenix...";
    try {
        const response = await fetch(`/api/paxsenix?${new URLSearchParams({ id: input })}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Server error: ${response.status}`);

        lrcResult = data.lrc || "";
        paxSyncJson = data.syncJson || "";
        lastJobId = "";
        result.textContent = lrcResult;
        resultCard.style.display = "block";
        if (badge) badge.textContent = data.timing === "word" ? "Word-timed: LRC + char sync" : "Line-timed: LRC only";

        const wordsBtn = document.getElementById("wordsBtn");
        const syncBtn = document.getElementById("syncBtn");
        if (wordsBtn) wordsBtn.style.display = "none";
        if (syncBtn) {
            if (paxSyncJson) {
                syncBtn.style.display = "";
                syncBtn.onclick = downloadPaxSync;
                updateSyncButtonLabel("paxsenix_sync.json");
            } else {
                syncBtn.style.display = "none";
            }
        }
        status.textContent = "Done! Scroll down to download or publish.";
        resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
        status.textContent = "";
        error.textContent = `Error: ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}

async function publishToLrclib() {
    const box = document.getElementById("lrclibLrc");
    const lrc = box ? box.value : "";
    const track = document.getElementById("lrclibTrack").value.trim();
    const artist = document.getElementById("lrclibArtist").value.trim();
    const duration = parseFloat(document.getElementById("lrclibDuration").value);
    const album = document.getElementById("lrclibAlbum").value.trim();
    const publishStatus = document.getElementById("lrclibStatus");
    const btn = document.getElementById("lrclibPublishBtn");
    const retryBtn = document.getElementById("lrclibRetryBtn");
    if (retryBtn) retryBtn.style.display = "none";

    if (!lrc.trim()) {
        // LRCLIB stores a track with no lyrics at all as instrumental, so
        // never let an empty box through.
        publishStatus.textContent = "Paste lyrics or load a file first.";
        return;
    }
    if (!track || !artist) {
        publishStatus.textContent = "Song name and artist are required.";
        return;
    }
    if (!duration || duration <= 0) {
        publishStatus.textContent = "Enter a valid duration in seconds.";
        return;
    }
    const issues = updateLrcIssues();
    if (issues) {
        document.getElementById("lrclibIssues").textContent = `Fix timestamps before publishing: ${issues}.`;
        return;
    }

    publishStatus.textContent = "Publishing to LRCLIB (solving proof-of-work)...";
    btn.disabled = true;

    const formData = new FormData();
    formData.append("track", track);
    formData.append("artist", artist);
    formData.append("duration", duration);
    formData.append("lrc", lrc);
    if (album) formData.append("album", album);

    try {
        const response = await fetch("/api/publish", {
            method: "POST",
            body: formData,
        });
        const data = await response.json();
        if (!response.ok) {
            const extra = lrcIssuesText({ duplicates: data.duplicates, out_of_order: data.out_of_order }, lrc);
            if (extra) document.getElementById("lrclibIssues").textContent = extra;
            throw new Error((data.message || data.error || `Server error: ${response.status}`) + (extra ? ` (${extra})` : ""));
        }
        publishStatus.textContent = data.status === "published" && data.id
            ? `Published! ID: ${data.id}`
            : "Submitted — not yet visible on LRCLIB, retry search in a bit.";
        if (!data.id && retryBtn) retryBtn.style.display = "block";
    } catch (e) {
        publishStatus.textContent = `Publish failed: ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}

async function retryLookup() {
    const track = document.getElementById("lrclibTrack").value.trim();
    const artist = document.getElementById("lrclibArtist").value.trim();
    const duration = parseFloat(document.getElementById("lrclibDuration").value);
    const publishStatus = document.getElementById("lrclibStatus");
    const retryBtn = document.getElementById("lrclibRetryBtn");

    publishStatus.textContent = "Checking LRCLIB for ID...";
    try {
        if (!duration || !isFinite(duration) || duration <= 0) {
            const params = new URLSearchParams({ artist_name: artist, track_name: track });
            const response = await fetch(`/api/search?${params}`);
            const data = await response.json().catch(() => ([]));
            if (!response.ok) {
                throw new Error(data.error || `Server error: ${response.status}`);
            }
            const list = Array.isArray(data) ? data : [];
            publishStatus.textContent = `Found ${list.length} result(s), add duration to confirm ID.`;
            return;
        }
        const params = new URLSearchParams({ artist, track, duration });
        const response = await fetch(`/api/lookup?${params}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `Server error: ${response.status}`);
        }
        publishStatus.textContent = data.id
            ? `Published! ID: ${data.id}`
            : "Submitted — not yet visible on LRCLIB, retry search in a bit.";
        if (data.id && retryBtn) retryBtn.style.display = "none";
    } catch (e) {
        publishStatus.textContent = `Still not on LRCLIB: ${e.message} — wait a bit and retry.`;
    }
}

function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

async function searchLrclib() {
    const val = (id, fb) => document.getElementById(id)?.value.trim() || document.getElementById(fb)?.value.trim() || "";
    const artist = val("searchArtist", "lrclibArtist");
    const track = val("searchTrack", "lrclibTrack");
    const durRaw = val("searchDuration", "lrclibDuration");
    const duration = parseFloat(durRaw);
    const hasDuration = durRaw !== "" && isFinite(duration) && duration > 0;
    // If the song-name field holds a pure number, treat it as an LRCLIB id.
    const lrclibId = /^\d+$/.test(track) ? track : "";
    const status = document.getElementById("checkStatus");
    const error = document.getElementById("checkError");
    const results = document.getElementById("checkResults");
    const btn = document.getElementById("checkSearchBtn");

    if (!lrclibId && (!artist || !track)) {
        error.textContent = "Artist and song name are required (or provide an LRCLIB ID).";
        return;
    }
    error.textContent = "";
    results.innerHTML = "";
    status.textContent = "Searching LRCLIB...";
    btn.disabled = true;
    try {
        let list = [];
        let publishedId = null;
        let possibleId = null;
        if (lrclibId) {
            const response = await fetch(`/api/lookup?id=${encodeURIComponent(lrclibId)}`);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || `Server error: ${response.status}`);
            list = [data];
            publishedId = data.id ?? null;
        } else {
            const params = new URLSearchParams({ artist_name: artist, track_name: track });
            const response = await fetch(`/api/search?${params}`);
            const data = await response.json().catch(() => ([]));
            if (!response.ok) throw new Error(data.error || `Server error: ${response.status}`);
            list = Array.isArray(data) ? data : [];
            if (hasDuration) {
                list = list.slice().sort((a, b) =>
                    Math.abs((a.duration || 0) - duration) - Math.abs((b.duration || 0) - duration));
            }
            if (hasDuration) {
                try {
                    const lookupParams = new URLSearchParams({ artist, track, duration });
                    const lookupResp = await fetch(`/api/lookup?${lookupParams}`);
                    if (lookupResp.ok) {
                        const lookupData = await lookupResp.json();
                        publishedId = lookupData.id ?? null;
                    }
                } catch (e) {
                }
                if (publishedId === null && list.length) {
                    const best = list[0];
                    if (best.duration != null && Math.abs(best.duration - duration) <= 2 && best.id != null) {
                        try {
                            const confirmResp = await fetch(`/api/lookup?${new URLSearchParams({ id: best.id })}`);
                            if (confirmResp.ok) {
                                const confirmData = await confirmResp.json();
                                publishedId = confirmData.id ?? null;
                            } else {
                                possibleId = best.id;
                            }
                        } catch (e) {
                            possibleId = best.id;
                        }
                    }
                }
            }
        }
        if (!list.length) {
            status.textContent = "No matches found.";
            return;
        }
        status.textContent = `${list.length} match${list.length === 1 ? "" : "es"} found.`;
        lastLrclibSearchResults = list;
        results.innerHTML = list.map((r, i) => {
            const synced = !!((r.syncedLyrics || "").trim());
            const isPub = publishedId !== null && r.id === publishedId;
            const isPoss = !isPub && publishedId === null && possibleId !== null && r.id === possibleId;
            const hl = isPub ? " published" : "";
            const dur = r.duration != null ? `${escHtml(Math.round(r.duration))}s` : "—";
            const lrc = escHtml((r.syncedLyrics || r.plainLyrics || "").trim());
            return `<div class="check-row${hl}" style="cursor:pointer;" onclick="toggleLrclibDetail(${i})"><strong>${escHtml(r.trackName)}` +
                `</strong> — ${escHtml(r.artistName)}<br>` +
                `<span class="hint">ID: ${escHtml(r.id)} · ${escHtml(r.albumName || "no album")} · ${dur} · ` +
                `${synced ? "synced" : "plain only"}${isPoss ? " · possible match (unconfirmed)" : ""}</span></div>` +
                `<div class="check-detail" id="checkDetail-${i}" style="display:none; margin:0.5rem 0 1rem 0; padding:0.5rem; border:1px solid var(--field-border, #ccc); border-radius:6px;">` +
                `<label>Full LRC (LRCLIB id: ${escHtml(r.id)})</label>` +
                `<textarea readonly style="width:100%; min-height:10rem; margin-top:0.25rem;">${lrc}</textarea>` +
                `<div style="margin-top:0.5rem;"><button class="download-btn" onclick="event.stopPropagation(); copyLrclibId(${i})">Copy LRCLIB ID</button></div>` +
                `</div>`;
        }).join("");
    } catch (e) {
        status.textContent = "";
        error.textContent = `Error: ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}

function toggleLrclibDetail(i) {
    const detail = document.getElementById("checkDetail-" + i);
    if (!detail) return;
    const willShow = detail.style.display === "none" || detail.style.display === "";
    document.querySelectorAll(".check-detail").forEach((el) => {
        if (el !== detail) el.style.display = "none";
    });
    detail.style.display = willShow ? "block" : "none";
}

async function copyLrclibId(i) {
    const r = lastLrclibSearchResults[i];
    if (!r || r.id == null) return;
    try {
        await navigator.clipboard.writeText(String(r.id));
    } catch (e) {
        const ta = document.createElement("textarea");
        ta.value = String(r.id);
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
    }
}
