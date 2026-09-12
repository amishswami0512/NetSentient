const API_BASE = `${window.location.protocol === 'file:' ? 'http://localhost:5000' : window.location.origin}/api`;

let isCongested = false;
let isQosEnabled = false;
let analysisCursor = 0;
let criticalityChart;

const btnCongestion = document.getElementById('btn-congestion');
const btnQos = document.getElementById('btn-qos');
const btnLoadDemo = document.getElementById('btn-load-demo');

const valEmergency = document.getElementById('val-emergency');
const valSensor = document.getElementById('val-sensor');
const valVideo = document.getElementById('val-video');
const valFile = document.getElementById('val-file');

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
      y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' }, beginAtZero: true, max: 100 }
    },
    plugins: {
      legend: { labels: { color: '#f8fafc' } }
    }
  }
});

btnCongestion.addEventListener('click', async () => {
  try {
    const data = await request('/simulation/congestion', {
      method: 'POST',
      body: JSON.stringify({ enabled: !isCongested })
    });
    isCongested = data.congestion;
    // Start the live feed with the highest-priority demo traffic when
    // congestion changes, making the QoS effect immediately visible.
    analysisCursor = 0;
    renderToggleState();
    await fetchMetrics();
  } catch (err) {
    showError(err);
  }
});

btnQos.addEventListener('click', async () => {
  try {
    const data = await request('/simulation/semantic-routing', {
      method: 'POST',
      body: JSON.stringify({ enabled: !isQosEnabled })
    });
    isQosEnabled = data.semantic_routing_enabled;
    renderToggleState();
    await fetchMetrics();
  } catch (err) {
    console.warn('Backend server not connected yet. Running in offline UI mode.');
  }
});

const aiPayloadText = document.getElementById('ai-payload-text');
const aiCriticalityBadge = document.getElementById('ai-criticality-badge');
const aiReasoningText = document.getElementById('ai-reasoning-text');
const payloadForm = document.getElementById('payload-form');
const payloadInput = document.getElementById('payload-input');
const analyzePayloadBtn = document.getElementById('analyze-payload-btn');
const payloadFormStatus = document.getElementById('payload-form-status');

const criticalityChartData = {
  labels: [],
  datasets: [{
    label: 'Criticality score / 10',
    data: [],
    backgroundColor: '#34d399aa',
    borderColor: '#34d399',
    borderWidth: 2,
    borderRadius: 4
  }]
};

criticalityChart = new Chart(document.getElementById('criticalityChart').getContext('2d'), {
  type: 'bar',
  data: criticalityChartData,
  options: {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { grid: { color: '#334155' }, ticks: { color: '#cbd5e1', maxRotation: 45, minRotation: 20 } },
      y: { min: 1, max: 10, ticks: { color: '#cbd5e1', stepSize: 1 }, grid: { color: '#334155' } }
    },
    plugins: { legend: { labels: { color: '#f8fafc' } } }
  }
});

function updateAIBox(payload, criticalityScore, reasoning) {
    if (!payload) return;
    aiPayloadText.textContent = `"${payload}"`;
    aiReasoningText.textContent = reasoning;
    const score = Math.max(1, Math.min(10, Number(criticalityScore)));
    aiCriticalityBadge.className = score >= 8
      ? 'px-4 py-1 rounded-full bg-red-600 text-white font-bold text-lg shadow-[0_0_15px_rgba(220,38,38,0.6)] animate-pulse'
      : score >= 5
        ? 'px-4 py-1 rounded-full bg-amber-500 text-slate-900 font-bold text-lg'
        : 'px-4 py-1 rounded-full bg-slate-600 text-white font-bold text-lg';
    aiCriticalityBadge.textContent = `${score.toFixed(1)} / 10`;
}

function updateCriticalityChart(traffic) {
  criticalityChartData.labels = traffic.map(item => item.label.length > 24
    ? `${item.label.slice(0, 24)}...`
    : item.label);
  criticalityChartData.datasets[0].data = traffic.map(item => item.criticality_score ?? item.priority ?? 1);
  criticalityChart.update();
}

payloadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = payloadInput.value.trim();
  if (!payload) {
    payloadFormStatus.textContent = 'Enter a payload before analyzing it.';
    payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-red-400';
    payloadInput.focus();
    return;
  }
  analyzePayloadBtn.disabled = true;
  analyzePayloadBtn.textContent = 'Analyzing...';
  payloadFormStatus.textContent = 'Classifying payload and adding it to the live stream...';
  payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-slate-400';

  try {
    const result = await request('/traffic/analyze', {
      method: 'POST',
      body: JSON.stringify({ input: payload })
    });
    updateAIBox(result.payload, result.criticality_score,
      `${result.reasoning} Gemini assigned ${result.criticality_score}/10 (${Math.round(result.confidence * 100)}% confidence).`);
    payloadFormStatus.textContent = `Added as ${result.category.replace('_', ' ')} (Gemini criticality ${result.criticality_score}/10).`;
    payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-emerald-400';
    payloadInput.value = '';
    await fetchMetrics(false);
  } catch (err) {
    payloadFormStatus.textContent = `Could not analyze payload: ${err.message}`;
    payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-red-400';
  } finally {
    analyzePayloadBtn.disabled = false;
    analyzePayloadBtn.textContent = 'Analyze & set priority';
  }
});

btnLoadDemo.addEventListener('click', async () => {
  try {
    btnLoadDemo.disabled = true;
    btnLoadDemo.textContent = 'Loading...';
    const result = await request('/demo/reset', { method: 'POST' });
    analysisCursor = 0;
    await fetchMetrics();
    payloadFormStatus.textContent = `Loaded ${result.traffic.length} Gemini-classified demo flows.`;
    payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-emerald-400';
  } catch (err) {
    showError(err);
    payloadFormStatus.textContent = `Could not load demo flows: ${err.message}`;
    payloadFormStatus.className = 'mt-2 min-h-5 text-sm text-red-400';
  } finally {
    btnLoadDemo.disabled = false;
    btnLoadDemo.textContent = 'Load 40 Demo Flows';
  }
});

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status})`);
  return data;
}

function renderToggleState() {
  btnCongestion.textContent = `Simulate Congestion: ${isCongested ? 'ON' : 'OFF'}`;
  btnCongestion.className = isCongested
    ? 'px-5 py-2.5 rounded-lg bg-red-700 font-bold border-2 border-white text-white shadow-lg'
    : 'px-5 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold shadow-lg';
  btnQos.textContent = `AI Priority (QoS): ${isQosEnabled ? 'ON' : 'OFF'}`;
  btnQos.className = isQosEnabled
    ? 'px-5 py-2.5 rounded-lg bg-emerald-700 font-bold border-2 border-white text-white shadow-lg'
    : 'px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-lg';
}

function showError(error) {
  aiReasoningText.textContent = `Backend unavailable: ${error.message}`;
}

async function fetchMetrics(updateSemanticAnalysis = true) {
  try {
    const [status, data] = await Promise.all([
      request('/network/status'),
      request('/traffic')
    ]);
    isCongested = status.congestion;
    isQosEnabled = status.semantic_routing_enabled;
    renderToggleState();
    const traffic = data.traffic || [];
    const byType = traffic.reduce((totals, item) => {
      totals[item.type] = (totals[item.type] || 0) + item.throughput_mbps;
      return totals;
    }, {});
    updateUI(
      byType.emergency || 0,
      byType.critical_sensor || 0,
      byType.video || 0,
      byType.file || 0,
      status.bandwidth_mbps
    );
    if (updateSemanticAnalysis && traffic.length) {
      const nextPayload = status.congestion
        ? traffic[analysisCursor++ % traffic.length]
        : traffic[traffic.length - 1];
      const score = nextPayload.criticality_score ?? nextPayload.priority ?? 1;
      updateAIBox(nextPayload.label, score,
        `${nextPayload.reasoning || 'Score stored on the traffic flow.'} Gemini criticality: ${score.toFixed(1)}/10.`);
    } else if (updateSemanticAnalysis && !traffic.length) {
      aiPayloadText.textContent = 'Waiting for submitted traffic...';
      aiReasoningText.textContent = 'Submit a payload to create a live flow.';
      aiCriticalityBadge.className = 'px-4 py-1 rounded-full bg-slate-700 text-slate-300 font-bold text-lg';
      aiCriticalityBadge.textContent = 'No traffic';
    }
    updateCriticalityChart(traffic);
  } catch (err) {
    showError(err);
  }
}

function updateUI(emergency, sensor, video, file, bandwidthMbps, timeStamp = new Date().toLocaleTimeString()) {
  valEmergency.innerHTML = `${emergency.toFixed(2)} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valSensor.innerHTML = `${sensor.toFixed(2)} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valVideo.innerHTML = `${video.toFixed(2)} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valFile.innerHTML = `${file.toFixed(2)} <span class="text-sm font-normal text-slate-400">Mbps</span>`;

  if (chartData.labels.length > 15) {
    chartData.labels.shift();
    chartData.datasets.forEach(ds => ds.data.shift());
  }

  chartData.labels.push(timeStamp);
  chartData.datasets[0].data.push(emergency);
  chartData.datasets[1].data.push(sensor);
  chartData.datasets[2].data.push(video);
  chartData.datasets[3].data.push(file);

  trafficChart.options.scales.y.max = bandwidthMbps;
  trafficChart.update();
}

async function startDashboard() {
  // Do not seed fixed demo traffic: cards reflect only traffic submitted
  // through the payload form (or created via the traffic API).
  await fetchMetrics();
  setInterval(fetchMetrics, 2000);
}

renderToggleState();
startDashboard();
