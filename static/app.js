/* ===================================================================
   app.js  –  Music Library Demo
   =================================================================== */

'use strict';

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function fmt(sec) {
  if (!sec || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function statusLabel(s) {
  const map = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '解析完成',
    waveform_generating: '波形生成中',
    waveform_ready: '波形就绪',
    analysis_failed: '解析失败',
    stream: '平台曲目',
  };
  return map[s] || s;
}

function showToast(msg, type = 'info', duration = 3000) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), duration);
}

async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(json.error || res.statusText), { status: res.status });
  return json;
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

const tabs = document.querySelectorAll('.nav-tab');
const panels = document.querySelectorAll('.tab-panel');

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    panels.forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'library') loadLibrary();
  });
});

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

let pollTimer = null;
let librarySongs = [];

async function loadLibrary() {
  try {
    librarySongs = await apiFetch('/api/library');
    renderLibrary(librarySongs);
    schedulePoll();
  } catch (e) {
    showToast('加载曲库失败: ' + e.message, 'error');
  }
}

function renderLibrary(songs) {
  const container = document.getElementById('library-list');
  document.getElementById('library-count').textContent = `${songs.length} 首`;

  if (!songs.length) {
    container.innerHTML = '<div class="empty-state">暂无歌曲，请上传音频文件</div>';
    return;
  }

  container.innerHTML = songs.map((s, i) => `
    <div class="song-card" data-id="${s.id}">
      <span class="song-num">${i + 1}</span>
      <span class="song-icon">🎵</span>
      <div class="song-info">
        <div class="song-title">${esc(s.title)}</div>
        <div class="song-artist">${esc(s.artist || '未知艺术家')}</div>
      </div>
      <span class="song-duration">${fmt(s.duration)}</span>
      <span class="status-badge status-${s.status}">${statusLabel(s.status)}</span>
      <div class="song-actions">
        <button class="btn btn-ghost" onclick="openSongModal(${s.id})">查看</button>
        <button class="btn btn-danger" onclick="deleteSong(${s.id})">删除</button>
      </div>
    </div>
  `).join('');
}

function schedulePoll() {
  clearTimeout(pollTimer);
  const hasPending = librarySongs.some(
    s => ['uploaded', 'parsing', 'waveform_generating'].includes(s.status)
  );
  if (hasPending) {
    pollTimer = setTimeout(loadLibrary, 2500);
  }
}

async function deleteSong(id) {
  if (!confirm('确定从曲库删除？')) return;
  try {
    await apiFetch(`/api/library/${id}`, { method: 'DELETE' });
    showToast('已删除', 'success');
    loadLibrary();
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error');
  }
}

function esc(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadProgress = document.getElementById('upload-progress');
const progressBar = document.getElementById('progress-bar');
const uploadStatusText = document.getElementById('upload-status-text');

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => uploadFiles(fileInput.files));

async function uploadFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;

  let done = 0;
  uploadProgress.classList.remove('hidden');

  for (const file of files) {
    uploadStatusText.textContent = `上传中 ${file.name}…`;
    progressBar.style.width = `${Math.round((done / files.length) * 100)}%`;

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      const json = await res.json().catch(() => ({}));

      if (res.status === 409 && json.duplicate) {
        showToast(`"${file.name}" 已存在（重复文件）`, 'warning');
      } else if (!res.ok) {
        showToast(`上传失败: ${json.error || res.statusText}`, 'error');
      } else {
        showToast(`"${json.title}" 上传成功，正在生成波形…`, 'success');
      }
    } catch (e) {
      showToast(`上传出错: ${e.message}`, 'error');
    }
    done++;
  }

  progressBar.style.width = '100%';
  uploadStatusText.textContent = '上传完成';
  setTimeout(() => {
    uploadProgress.classList.add('hidden');
    progressBar.style.width = '0%';
  }, 1500);

  fileInput.value = '';
  loadLibrary();
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

document.getElementById('search-btn').addEventListener('click', doSearch);
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch();
});

async function doSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  try {
    const data = await apiFetch(`/api/search?q=${encodeURIComponent(q)}`);
    renderSearchResults(data);
  } catch (e) {
    showToast('搜索失败: ' + e.message, 'error');
  }
}

function renderSearchResults({ my_library = [], platform = [] }) {
  const myEl = document.getElementById('search-my-list');
  const platEl = document.getElementById('search-platform-list');

  myEl.innerHTML = my_library.length
    ? my_library.map(s => `
        <div class="song-card">
          <span class="song-icon">🎵</span>
          <div class="song-info">
            <div class="song-title">${esc(s.title)}</div>
            <div class="song-artist">${esc(s.artist)}</div>
          </div>
          <span class="song-duration">${fmt(s.duration)}</span>
          <div class="song-actions">
            <button class="btn btn-ghost" onclick="openSongModal(${s.id})">查看</button>
          </div>
        </div>`).join('')
    : '<div class="empty-state">未找到相关歌曲</div>';

  platEl.innerHTML = platform.length
    ? platform.map(s => `
        <div class="song-card">
          <span class="song-icon">🎶</span>
          <div class="song-info">
            <div class="song-title">${esc(s.title)}</div>
            <div class="song-artist">${esc(s.artist)}</div>
          </div>
          <span class="song-duration">${fmt(s.duration)}</span>
          <div class="song-actions">
            <button class="btn btn-success" onclick="addPlatformSong(${s.id}, this)">加入曲库</button>
          </div>
        </div>`).join('')
    : '<div class="empty-state">平台曲库中未找到相关歌曲</div>';
}

async function addPlatformSong(platformId, btn) {
  btn.disabled = true;
  btn.textContent = '添加中…';
  try {
    const data = await apiFetch(`/api/library/add/${platformId}`, { method: 'POST' });
    if (data.already_added) {
      showToast('该歌曲已在曲库中', 'info');
    } else {
      showToast('已加入我的曲库', 'success');
    }
    btn.textContent = '已加入';
  } catch (e) {
    showToast('添加失败: ' + e.message, 'error');
    btn.disabled = false;
    btn.textContent = '加入曲库';
  }
}

// ---------------------------------------------------------------------------
// Song Detail Modal
// ---------------------------------------------------------------------------

let modalSongId = null;
let waveformPoints = [];
let waveformPollTimer = null;
const audio = document.getElementById('audio-player');

document.getElementById('modal-close-btn').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
});

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  audio.pause();
  audio.src = '';
  clearTimeout(waveformPollTimer);
  modalSongId = null;
  waveformPoints = [];
}

async function openSongModal(songId) {
  modalSongId = songId;
  clearTimeout(waveformPollTimer);

  try {
    const song = await apiFetch(`/api/song/${songId}`);
    populateModal(song);
    document.getElementById('modal-overlay').classList.remove('hidden');

    if (song.source === 'local') {
      // Try to load the audio – the file path is on the server, we can't stream it
      // directly unless we add a /stream endpoint. For the demo we just show metadata + waveform.
      document.getElementById('play-pause-btn').disabled = true;
      document.getElementById('player-note').classList.add('hidden');
    } else {
      document.getElementById('play-pause-btn').disabled = true;
      document.getElementById('player-note').classList.remove('hidden');
    }

    loadWaveform(songId, song.status);
  } catch (e) {
    showToast('加载歌曲失败: ' + e.message, 'error');
  }
}

function populateModal(s) {
  document.getElementById('modal-title').textContent = s.title || '未知';
  document.getElementById('modal-artist').textContent = s.artist || '未知艺术家';
  document.getElementById('modal-status-badge').textContent = statusLabel(s.status);
  document.getElementById('modal-status-badge').className = `status-badge status-${s.status}`;
  document.getElementById('d-duration').textContent = fmt(s.duration);
  document.getElementById('d-format').textContent = s.format || '—';
  document.getElementById('d-sample-rate').textContent = s.sample_rate ? `${s.sample_rate} Hz` : '—';
  document.getElementById('d-channels').textContent = s.channels ? (s.channels === 1 ? '单声道' : '立体声') : '—';
  document.getElementById('d-bitrate').textContent = s.bitrate ? `${s.bitrate} kbps` : '—';
  document.getElementById('d-source').textContent = s.source === 'local' ? '本地上传' : '平台曲库';
  document.getElementById('duration-display').textContent = fmt(s.duration);
}

async function loadWaveform(songId, currentStatus) {
  const placeholder = document.getElementById('waveform-placeholder');
  const canvas = document.getElementById('waveform-canvas');

  if (['uploaded', 'parsing', 'waveform_generating'].includes(currentStatus)) {
    placeholder.classList.remove('hidden');
    placeholder.textContent = '波形生成中…';
    waveformPollTimer = setTimeout(() => pollWaveform(songId), 2000);
    return;
  }

  if (currentStatus === 'analysis_failed') {
    placeholder.classList.remove('hidden');
    placeholder.textContent = '波形生成失败';
    return;
  }

  try {
    const data = await apiFetch(`/api/waveform/${songId}`);
    if (data.points && data.points.length) {
      waveformPoints = data.points;
      placeholder.classList.add('hidden');
      drawWaveform(canvas, waveformPoints);
    } else {
      placeholder.classList.remove('hidden');
      placeholder.textContent = '波形生成中…';
      waveformPollTimer = setTimeout(() => pollWaveform(songId), 2000);
    }
  } catch (e) {
    if (e.status === 202) {
      placeholder.classList.remove('hidden');
      placeholder.textContent = '波形生成中…';
      waveformPollTimer = setTimeout(() => pollWaveform(songId), 2000);
    } else {
      // For platform songs, generate a mock visual
      waveformPoints = mockWaveform(songId);
      placeholder.classList.add('hidden');
      drawWaveform(canvas, waveformPoints);
    }
  }
}

async function pollWaveform(songId) {
  if (modalSongId !== songId) return;
  try {
    const song = await apiFetch(`/api/song/${songId}`);
    document.getElementById('modal-status-badge').textContent = statusLabel(song.status);
    document.getElementById('modal-status-badge').className = `status-badge status-${song.status}`;
    await loadWaveform(songId, song.status);
  } catch (e) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Waveform drawing
// ---------------------------------------------------------------------------

function mockWaveform(seed) {
  const pts = [];
  for (let i = 0; i < 1000; i++) {
    const t = i / 1000;
    let v = 0.5 * Math.sin(2 * Math.PI * t * 3)
           + 0.3 * Math.sin(2 * Math.PI * t * 7 + 1.2)
           + 0.2 * Math.sin(2 * Math.PI * t * 15 + 0.5);
    pts.push(Math.max(0, Math.abs(v + (Math.random() - 0.5) * 0.1)));
  }
  const mx = Math.max(...pts) || 1;
  return pts.map(v => +(v / mx).toFixed(4));
}

function drawWaveform(canvas, points) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width  = rect.width  * dpr;
  canvas.height = 120 * dpr;
  canvas.style.width  = rect.width + 'px';
  canvas.style.height = '120px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = 120;
  const midY = H / 2;

  ctx.clearRect(0, 0, W, H);

  // Background grid line
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, midY); ctx.lineTo(W, midY); ctx.stroke();

  const barW = W / points.length;

  points.forEach((v, i) => {
    const amp = Math.max(0.01, Math.abs(v));
    const barH = amp * midY;
    const x = i * barW;

    // Gradient colour based on amplitude
    const alpha = 0.5 + amp * 0.5;
    ctx.fillStyle = `rgba(124, 92, 252, ${alpha.toFixed(2)})`;
    ctx.fillRect(x, midY - barH, Math.max(barW - 0.5, 0.5), barH * 2);
  });
}

// Seek on waveform click
document.getElementById('waveform-canvas').addEventListener('click', e => {
  const canvas = e.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const ratio = (e.clientX - rect.left) / rect.width;
  updateSeekBar(ratio);
});

const seekBarBg = document.getElementById('seek-bar-bg') || document.querySelector('.seek-bar-bg');
if (seekBarBg) {
  seekBarBg.addEventListener('click', e => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    updateSeekBar(ratio);
    if (!audio.paused && audio.duration) {
      audio.currentTime = ratio * audio.duration;
    }
  });
}

function updateSeekBar(ratio) {
  document.getElementById('seek-bar-fill').style.width = `${(ratio * 100).toFixed(1)}%`;
  document.getElementById('current-time-display').textContent = fmt(ratio * (audio.duration || 0));
}

// Play/Pause button
document.getElementById('play-pause-btn').addEventListener('click', () => {
  if (audio.paused) { audio.play(); } else { audio.pause(); }
});
audio.addEventListener('play',  () => { document.getElementById('play-pause-btn').textContent = '⏸'; });
audio.addEventListener('pause', () => { document.getElementById('play-pause-btn').textContent = '▶'; });
audio.addEventListener('timeupdate', () => {
  if (!audio.duration) return;
  const ratio = audio.currentTime / audio.duration;
  updateSeekBar(ratio);
  document.getElementById('player-time').textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

loadLibrary();
