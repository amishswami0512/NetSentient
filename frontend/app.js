const API_BASE = 'http://localhost:5000/api';

// State Tracking
let isCongested = false;
let isQosEnabled = true;

// Elements
const btnCongestion = document.getElementById('btn-congestion');
const btnQos = document.getElementById('btn-qos');

const valEmergency = document.getElementById('val-emergency');
const valSensor = document.getElementById('val-sensor');
const valVideo = document.getElementById('val-video');
const valFile = document.getElementById('val-file');

// Maps backend traffic "type" to this dashboard's tier cards/chart series.
const TYPE_TO_INDEX = { emergency: 0, critical_sensor: 1, video: 2, file: 3 };
const CATEGORY_TO_TIER = { emergency: 1, critical_sensor: 2, video: 3, file: 4, background: 4 };
const CATEGORY_TO_LABEL = {
  emergency: 'Emergency', critical_sensor: 'Sensor', video: 'Video', file: 'File', background: 'Bulk'
};

// Chart Setup
const ctx = document.getElementById('trafficChart').getContext('2d');
const chartData = {
  labels: [],
  datasets: [
    { label: 'Emergency', borderColor: '#ef4444', backgroundColor: '#ef444422', data: [], fill: true, tension: 0.3 },
    { label: 'Sensor', borderColor: '#f59e0b', backgroundColor: '#f59e0b22', data: [], fill: true, tension: 0.3 },
    { label: 'Video', borderColor: '#3b82f6', backgroundColor: '#3b82f622', data: [], fill: true, tension: 0.3 },
    { label: 'File Download', borderColor: '#94a3b8', backgroundColor: '#94a3b822', data: [], fill: true, tension: 0.3 }
  ]
};

const trafficChart = new Chart(ctx, {
  type: 'line',
  data: chartData,
  options: {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
      y: {
        grid: { color: '#334155' }, ticks: { color: '#94a3b8' }, beginAtZero: true, max: 100,
        title: { display: true, text: '% Delivered', color: '#94a3b8' }
      }
    },
    plugins: {
      legend: { labels: { color: '#f8fafc' } }
    }
  }
});

function setToggleButtonState() {
  btnCongestion.textContent = `Simulate Congestion: ${isCongested ? 'ON' : 'OFF'}`;
  btnCongestion.className = isCongested
    ? 'px-5 py-2.5 rounded-lg bg-red-700 font-bold border-2 border-white text-white shadow-lg'
    : 'px-5 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold shadow-lg';

  btnQos.textContent = `AI Priority (QoS): ${isQosEnabled ? 'ON' : 'OFF'}`;
  btnQos.className = isQosEnabled
    ? 'px-5 py-2.5 rounded-lg bg-emerald-700 font-bold border-2 border-white text-white shadow-lg'
    : 'px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-lg';
}

// Toggle Handlers
btnCongestion.addEventListener('click', async () => {
  isCongested = !isCongested;
  setToggleButtonState();
  try {
    await fetch(`${API_BASE}/simulation/congestion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: isCongested })
    });
  } catch (err) {
    console.warn('Backend server not reachable:', err);
  }
});

btnQos.addEventListener('click', async () => {
  isQosEnabled = !isQosEnabled;
  setToggleButtonState();
  try {
    await fetch(`${API_BASE}/simulation/semantic-routing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: isQosEnabled })
    });
  } catch (err) {
    console.warn('Backend server not reachable:', err);
  }
});

// --- AI Box Logic ---
const aiPayloadText = document.getElementById('ai-payload-text');
const aiTierBadge = document.getElementById('ai-tier-badge');
const aiReasoningText = document.getElementById('ai-reasoning-text');
const aiInput = document.getElementById('ai-input');
const aiAnalyzeBtn = document.getElementById('ai-analyze-btn');

function updateAIBox(payload, tier, reasoning) {
  if (!payload) return; // safety check
  aiPayloadText.textContent = `"${payload}"`;
  aiReasoningText.textContent = reasoning;

  if (tier === 1) {
    aiTierBadge.className = 'px-4 py-1 rounded-full bg-red-600 text-white font-bold text-lg shadow-[0_0_15px_rgba(220,38,38,0.6)] animate-pulse';
    aiTierBadge.textContent = 'Tier 1 (Emergency)';
  } else if (tier === 2) {
    aiTierBadge.className = 'px-4 py-1 rounded-full bg-amber-500 text-slate-900 font-bold text-lg';
    aiTierBadge.textContent = 'Tier 2 (Sensor)';
  } else if (tier === 3) {
    aiTierBadge.className = 'px-4 py-1 rounded-full bg-blue-500 text-white font-bold text-lg';
    aiTierBadge.textContent = 'Tier 3 (Video)';
  } else {
    aiTierBadge.className = 'px-4 py-1 rounded-full bg-slate-600 text-white font-bold text-lg';
    aiTierBadge.textContent = 'Tier 4 (Bulk)';
  }
}

async function classifyText(text) {
  aiAnalyzeBtn.disabled = true;
  aiAnalyzeBtn.textContent = 'Analyzing...';
  try {
    const res = await fetch(`${API_BASE}/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: text })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Classification failed');

    const tier = CATEGORY_TO_TIER[data.category] ?? 4;
    const label = CATEGORY_TO_LABEL[data.category] ?? data.category;
    const reasoning = `Classified as ${label} traffic — priority ${data.priority}/10, confidence ${Math.round(data.confidence * 100)}%.`;
    updateAIBox(text, tier, reasoning);
  } catch (err) {
    updateAIBox(text, 4, `Could not reach the classifier: ${err.message}`);
  } finally {
    aiAnalyzeBtn.disabled = false;
    aiAnalyzeBtn.textContent = 'Analyze';
  }
}

aiAnalyzeBtn.addEventListener('click', () => {
  const text = aiInput.value.trim();
  if (text) classifyText(text);
});
aiInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') aiAnalyzeBtn.click();
});
// --------------------

// Live Metrics Fetcher — pulls real traffic + delivery metrics from the backend.
async function fetchMetrics() {
  try {
    const res = await fetch(`${API_BASE}/traffic`);
    const data = await res.json();
    const values = [0, 0, 0, 0];
    for (const item of data.traffic || []) {
      const idx = TYPE_TO_INDEX[item.type];
      if (idx !== undefined) values[idx] = item.delivery_percent;
    }
    updateUI(...values);
  } catch (err) {
    console.warn('Backend server not reachable:', err);
  }
}

function updateUI(emergency, sensor, video, file, timeStamp = new Date().toLocaleTimeString()) {
  // Update Text Cards — showing % of that traffic type getting delivered right now.
  valEmergency.innerHTML = `${emergency} <span class="text-sm font-normal text-slate-400">%</span>`;
  valSensor.innerHTML = `${sensor} <span class="text-sm font-normal text-slate-400">%</span>`;
  valVideo.innerHTML = `${video} <span class="text-sm font-normal text-slate-400">%</span>`;
  valFile.innerHTML = `${file} <span class="text-sm font-normal text-slate-400">%</span>`;

  // Update Chart
  if (chartData.labels.length > 15) {
    chartData.labels.shift();
    chartData.datasets.forEach(ds => ds.data.shift());
  }

  chartData.labels.push(timeStamp);
  chartData.datasets[0].data.push(emergency);
  chartData.datasets[1].data.push(sensor);
  chartData.datasets[2].data.push(video);
  chartData.datasets[3].data.push(file);

  trafficChart.update();
}

async function init() {
  try {
    // Seed the standard demo traffic set (emergency/critical_sensor/video/file).
    await fetch(`${API_BASE}/demo/reset`, { method: 'POST' });

    // Sync toggle buttons to actual backend state.
    const statusRes = await fetch(`${API_BASE}/network/status`);
    const status = await statusRes.json();
    isCongested = status.congestion;
    isQosEnabled = status.semantic_routing_enabled;
    setToggleButtonState();
  } catch (err) {
    console.warn('Could not reach backend at startup:', err);
  }
  fetchMetrics();
}

init();

// Poll every 1 second
setInterval(fetchMetrics, 1000);
