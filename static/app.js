let lrcResult = "";

function showProgress(percent, message) {
    const wrap = document.getElementById("progressWrap");
    const fill = document.getElementById("progressFill");
    const label = document.getElementById("progressLabel");
    wrap.style.display = "block";
    fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    label.textContent = `${message} (${Math.round(percent)}%)`;
}

function hideProgress() {
    document.getElementById("progressWrap").style.display = "none";
}

async function align() {
    const audioInput = document.getElementById("audio");
    const youtubeUrl = document.getElementById("youtubeUrl").value.trim();
    const lyrics = document.getElementById("lyrics").value;
    const model = document.getElementById("model").value;
    const language = document.getElementById("language").value || null;
    const offset = parseFloat(document.getElementById("offset").value) || 0;

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

        // Poll until done
        while (true) {
            await new Promise((r) => setTimeout(r, 1000));
            const poll = await fetch(`/api/jobs/${job_id}`);
            if (!poll.ok) throw new Error(`Job lost: ${poll.status}`);
            const job = await poll.json();

            if (job.stage === "error" || job.error) {
                throw new Error(job.error || job.message);
            }
            showProgress(job.percent || 0, job.message || job.stage);

            if (job.done) {
                lrcResult = job.lrc || "";
                result.textContent = lrcResult;
                resultCard.style.display = "block";
                status.textContent = "Done!";
                hideProgress();
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

async function publishToLrclib() {
    const track = document.getElementById("trackName").value.trim();
    const artist = document.getElementById("artistName").value.trim();
    const duration = parseFloat(document.getElementById("duration").value);
    const album = document.getElementById("albumName").value.trim();
    const publishStatus = document.getElementById("publishStatus");
    const btn = document.getElementById("publishBtn");

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
            : "Published to LRCLIB!";
    } catch (e) {
        publishStatus.textContent = `Publish failed: ${e.message}`;
    } finally {
        btn.disabled = false;
    }
}
