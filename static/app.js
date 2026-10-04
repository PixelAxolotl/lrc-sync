let lrcResult = "";
let lastJobId = "";

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
    const main = name === 'main';
    document.getElementById('tabMainPanel').style.display = main ? '' : 'none';
    document.getElementById('tabAdvancedPanel').style.display = main ? 'none' : '';
    document.getElementById('tabMain').classList.toggle('active', main);
    document.getElementById('tabAdvanced').classList.toggle('active', !main);
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

const lyricsBox = document.getElementById("lyrics");
if (lyricsBox) lyricsBox.addEventListener("input", resetLanguageDropdown);

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
    if (language) formData.append("language", language);
    formData.append("offset", offset);
    formData.append("temperature", temperature);
    formData.append("beam_size", beamSize);
    formData.append("best_of", bestOf);

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
        lastJobId = job_id;
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
            if (job.stage === "cancelled") {
                status.textContent = "Cancelled.";
                error.textContent = "";
                hideProgress();
                btn.disabled = false;
                const cancelBtn = document.getElementById("cancelBtn");
                if (cancelBtn) cancelBtn.style.display = "none";
                return;
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
            if (syncBtn) syncBtn.style.display = job.character_level ? "" : "none";

            if (job.done) {
                const cancelBtn = document.getElementById("cancelBtn");
                if (cancelBtn) cancelBtn.style.display = "none";
                lrcResult = job.lrc || "";
                result.textContent = lrcResult;
                resultCard.style.display = "block";
                status.textContent = "Done!";
                hideProgress();
                btn.disabled = false;
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
        a.download = "output_sync.json";
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        if (status) status.textContent = `Sync download failed: ${e.message}`;
    }
}

async function publishToLrclib() {
    const track = document.getElementById("trackName").value.trim();
    const artist = document.getElementById("artistName").value.trim();
    const duration = parseFloat(document.getElementById("duration").value);
    const album = document.getElementById("albumName").value.trim();
    const publishStatus = document.getElementById("publishStatus");
    const btn = document.getElementById("publishBtn");
    const retryBtn = document.getElementById("retryBtn");
    if (retryBtn) retryBtn.style.display = "none";

    if (!lrcResult) {
        publishStatus.textContent = "Generate an LRC first.";
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

    publishStatus.textContent = "Publishing to LRCLIB...";
    btn.disabled = true;

    const formData = new FormData();
    formData.append("track", track);
    formData.append("artist", artist);
    formData.append("duration", duration);
    formData.append("lrc", lrcResult);
    if (album) formData.append("album", album);

    try {
        const response = await fetch("/api/publish", {
            method: "POST",
            body: formData,
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || `Server error: ${response.status}`);
        }
        publishStatus.textContent = data.id
            ? `Published to LRCLIB! ID: ${data.id}`
            : "Published to LRCLIB! ID not indexed yet — wait a bit, then hit “Check again for ID”.";
        if (!data.id && retryBtn) retryBtn.style.display = "block";
    } catch (e) {
        publishStatus.textContent = `Publish failed: ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}

async function retryLookup() {
    const track = document.getElementById("trackName").value.trim();
    const artist = document.getElementById("artistName").value.trim();
    const duration = parseFloat(document.getElementById("duration").value);
    const publishStatus = document.getElementById("publishStatus");
    const retryBtn = document.getElementById("retryBtn");

    publishStatus.textContent = "Checking LRCLIB for ID...";
    try {
        const params = new URLSearchParams({ artist, track, duration });
        const response = await fetch(`/api/lookup?${params}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `Server error: ${response.status}`);
        }
        publishStatus.textContent = data.id
            ? `Published to LRCLIB! ID: ${data.id}`
            : "Published to LRCLIB!";
        if (data.id && retryBtn) retryBtn.style.display = "none";
    } catch (e) {
        publishStatus.textContent = `Still not on LRCLIB: ${e.message} — wait a bit and retry.`;
    }
}
