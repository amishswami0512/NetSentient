const API = `${window.location.protocol === 'file:' ? 'http://localhost:5000' : window.location.origin}/api`;
const $ = (id) => document.getElementById(id);
let congestion = false;
let semantic = true;
let events = [];
let trafficChart;
let criticalityChart;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
}
function typeName(type) {
  return ({ emergency: 'Emergency', critical_sensor: 'Critical Sensor', video: 'Video Stream', file: 'Bulk Transfer' })[type] || type;
}
function typeClass(type) {
  return ({ emergency: 'emergency', critical_sensor: 'sensor', video: 'video', file: 'file' })[type] || 'file';
}
function number(value, fallback = 0) { return Number.isFinite(Number(value)) ? Number(value) : fallback; }

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.error?.message || `Request failed (${response.status})`);
  return data;
}

function logEvent(message, kind = 'system') {
  events.unshift({ time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }), message, kind });
  events = events.slice(0, 8);
  $('eventLog').innerHTML = events.map((event) => `<div class="event ${event.kind === 'error' ? 'error' : ''}"><time>${event.time}</time><i></i><span>${escapeHtml(event.message)}</span><b>${escapeHtml(event.kind.toUpperCase())}</b></div>`).join('');
}

function updateToggles() {
  $('congestionToggle').classList.toggle('on', congestion);
  $('congestionToggle').innerHTML = `<span></span> Congestion <b>${congestion ? 'ON' : 'OFF'}</b>`;
  $('semanticToggle').classList.toggle('on', semantic);
  $('semanticToggle').innerHTML = `<span></span> Semantic routing <b>${semantic ? 'ON' : 'OFF'}</b>`;
}

function updateNetwork(status) {
  $('loadValue').textContent = `${number(status.load_percent)}%`;
  $('bandwidthValue').textContent = `${number(status.bandwidth_mbps)} Mbps available`;
  $('loadMeter').style.width = `${Math.min(100, number(status.load_percent))}%`;
  $('flowsValue').textContent = number(status.active_connections);
}

function renderTraffic(items) {
  if (!items.length) {
    $('trafficGrid').innerHTML = '<div class="traffic-card" style="grid-column:1/-1"><div class="traffic-meta">No active flows. Load demo traffic or analyze a payload to populate the network.</div></div>';
    return;
  }
  $('trafficGrid').innerHTML = items.map((flow) => `<article class="traffic-card ${typeClass(flow.type)}"><div class="traffic-top"><span class="traffic-name" title="${escapeHtml(flow.label)}">${escapeHtml(flow.label)}</span><span class="priority">P${escapeHtml(flow.priority)}</span></div><div class="traffic-value">${number(flow.delivery_percent).toFixed(1)}<span style="font-size:11px;color:#647980">%</span></div><div class="traffic-meta">delivery · ${number(flow.latency_ms).toFixed(0)} ms latency · ${number(flow.packet_loss_percent).toFixed(1)}% loss</div><span class="status ${escapeHtml(flow.status || 'fair')}">${escapeHtml(flow.status || 'fair')}</span></article>`).join('');
}

function initCharts() {
  const chartStyle = { color: '#60757c' };
  trafficChart = new Chart($('trafficChart'), {
    type: 'line', data: { labels: [], datasets: [
      { label: 'Emergency', data: [], borderColor: '#ff6672', backgroundColor: '#ff667222', fill: true, tension: .35 },
      { label: 'Sensor', data: [], borderColor: '#e8bc64', backgroundColor: '#e8bc6422', fill: true, tension: .35 },
      { label: 'Video', data: [], borderColor: '#81a8ff', backgroundColor: '#81a8ff22', fill: true, tension: .35 },
      { label: 'Bulk', data: [], borderColor: '#788890', backgroundColor: '#78889022', fill: true, tension: .35 }
    ] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 400 }, scales: { x: { ticks: chartStyle, grid: { color: '#173038' } }, y: { beginAtZero: true, ticks: chartStyle, grid: { color: '#173038' } } }, plugins: { legend: { labels: { color: '#b8cbd0' } } } }
  });
  criticalityChart = new Chart($('criticalityChart'), {
    type: 'bar', data: { labels: [], datasets: [{ label: 'Criticality / 10', data: [], backgroundColor: '#55f2a599', borderColor: '#55f2a5', borderWidth: 1, borderRadius: 5 }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 450 }, scales: { x: { ticks: chartStyle, grid: { display: false } }, y: { min: 0, max: 10, ticks: { ...chartStyle, stepSize: 2 }, grid: { color: '#173038' } } }, plugins: { legend: { display: false } } }
  });
}

function updateCharts(flows, bandwidth) {
  const totals = flows.reduce((result, flow) => { result[flow.type] = (result[flow.type] || 0) + number(flow.throughput_mbps); return result; }, {});
  const values = [totals.emergency || 0, totals.critical_sensor || 0, totals.video || 0, totals.file || 0];
  const labels = trafficChart.data.labels;
  if (labels.length >= 16) { labels.shift(); trafficChart.data.datasets.forEach((set) => set.data.shift()); }
  labels.push(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
  values.forEach((value, index) => trafficChart.data.datasets[index].data.push(value));
  trafficChart.options.scales.y.max = Math.max(10, number(bandwidth, 100));
  trafficChart.update();

  const ranked = [...flows].slice(-12);
  criticalityChart.data.labels = ranked.map((flow) => flow.label.length > 14 ? `${flow.label.slice(0, 14)}…` : flow.label);
  criticalityChart.data.datasets[0].data = ranked.map((flow) => Math.max(1, Math.min(10, number(flow.criticality_score, flow.priority || 1))));
  criticalityChart.update();
}

function showAnalysis(flow) {
  if (!flow) return;
  const score = Math.max(1, Math.min(10, number(flow.criticality_score, flow.priority || 1)));
  $('classCategory').textContent = typeName(flow.category || flow.type);
  $('analysisProvider').textContent = flow.provider === 'gemini' ? 'GEMINI ANALYSIS' : 'LOCAL SAFETY RULE';
  $('classPriority').textContent = `${score.toFixed(1)}/10`;
  $('classReason').textContent = flow.reasoning || flow.classification?.reasoning || `Semantic priority assigned to this ${typeName(flow.type).toLowerCase()} flow.`;
  $('lastPayload').textContent = flow.payload || flow.label;
  $('lastReasoning').textContent = $('classReason').textContent;
}

function renderThroughputComparison(data) {
  const scenarios = data?.scenarios || [];
  if (!scenarios.length) return;
  const tiers = ['emergency', 'critical_sensor', 'video', 'file', 'background'];
  $('throughputComparison').innerHTML = scenarios.map((scenario, index) => `<article class="scenario-card ${index === 2 ? 'highlight' : ''}"><h3>${escapeHtml(scenario.label)}</h3><small>${number(scenario.bandwidth_mbps).toFixed(1)} Mbps link · ${number(scenario.total_mbps).toFixed(2)} Mbps delivered</small>${tiers.map((tier) => `<div class="throughput-row ${typeClass(tier)}"><span>${typeName(tier)}</span><b>${number(scenario.tiers?.[tier]).toFixed(3)} Mbps</b></div>`).join('')}</article>`).join('');
}

async function refresh() {
  try {
    const [health, status, trafficData, comparison] = await Promise.all([request('/health'), request('/network/status'), request('/traffic'), request('/traffic/throughput-comparison')]);
    $('healthDot').classList.add('ok'); $('healthText').textContent = 'API online'; $('apiVersion').textContent = health.version || 'ready';
    congestion = Boolean(status.congestion); semantic = Boolean(status.semantic_routing_enabled); updateToggles(); updateNetwork(status);
    const flows = trafficData.traffic || []; renderTraffic(flows); updateCharts(flows, status.bandwidth_mbps); renderThroughputComparison(comparison);
  } catch (error) {
    $('healthDot').classList.remove('ok'); $('healthText').textContent = 'API offline'; $('apiVersion').textContent = '—';
  }
}

async function setCongestion() {
  try { const response = await request('/simulation/congestion', { method: 'POST', body: JSON.stringify({ enabled: !congestion }) }); congestion = response.congestion; updateToggles(); logEvent(`Congestion switched ${congestion ? 'ON' : 'OFF'}`, 'network'); await refresh(); }
  catch (error) { logEvent(error.message, 'error'); }
}
async function setSemantic() {
  try { const response = await request('/simulation/semantic-routing', { method: 'POST', body: JSON.stringify({ enabled: !semantic }) }); semantic = response.semantic_routing_enabled; updateToggles(); logEvent(`Semantic routing ${semantic ? 'enabled' : 'disabled'}`, 'routing'); await refresh(); }
  catch (error) { logEvent(error.message, 'error'); }
}
async function seedDemo() {
  try { $('seedBtn').disabled = true; const data = await request('/demo/reset', { method: 'POST' }); logEvent(`Loaded ${data.traffic.length} Gemini-classified demo flows`, 'demo'); await refresh(); }
  catch (error) { logEvent(error.message, 'error'); } finally { $('seedBtn').disabled = false; }
}
async function runDemo() {
  try { $('demoBtn').disabled = true; await request('/demo/reset', { method: 'POST' }); await request('/demo/congest', { method: 'POST' }); congestion = true; semantic = true; updateToggles(); const comparison = await request('/demo/compare', { method: 'POST' }); renderComparison(comparison); logEvent('Full congestion demo executed with semantic protection', 'demo'); await refresh(); }
  catch (error) { logEvent(error.message, 'error'); } finally { $('demoBtn').disabled = false; }
}
async function reset() {
  try { await request('/simulation/reset', { method: 'POST' }); logEvent('Simulation state reset', 'system'); await refresh(); }
  catch (error) { logEvent(error.message, 'error'); }
}
async function classify() {
  const input = $('payloadInput').value.trim(); if (!input) { $('classifierStatus').textContent = 'Enter a payload before analyzing it.'; $('classifierStatus').className = 'form-status error'; return; }
  const button = $('classifyBtn'); button.disabled = true; button.textContent = 'Analyzing…';
  try { const data = await request('/traffic/analyze', { method: 'POST', body: JSON.stringify({ input }) }); showAnalysis(data); $('payloadInput').value = ''; const provider = data.provider === 'gemini' ? 'Gemini' : 'local safety rule'; $('classifierStatus').textContent = `Added as ${typeName(data.category)} with ${provider} criticality ${number(data.criticality_score).toFixed(1)}/10.`; $('classifierStatus').className = 'form-status success'; logEvent(`${provider} classified payload as ${typeName(data.category)} (${number(data.criticality_score).toFixed(1)}/10)`, 'ai'); await refresh(); }
  catch (error) { $('classifierStatus').textContent = error.message; $('classifierStatus').className = 'form-status error'; logEvent(error.message, 'error'); }
  finally { button.disabled = false; button.innerHTML = 'Analyze &amp; add flow <span>→</span>'; }
}
function renderComparison(data) {
  const bars = (items) => (items || []).map((item) => `<div class="bar-row"><div class="bar-label"><span>${typeName(item.type)}</span><b>${number(item.delivery_percent).toFixed(1)}%</b></div><div class="bar-bg"><div class="bar-fill" style="width:${Math.min(100, number(item.delivery_percent))}%"></div></div></div>`).join('');
  $('baselineBars').innerHTML = bars(data.baseline); $('semanticBars').innerHTML = bars(data.semantic);
  const improvement = (data.improvement || []).map((item) => number(item.delivery_improvement_percent)); const average = improvement.length ? improvement.reduce((sum, value) => sum + value, 0) / improvement.length : 0;
  $('impactBox').innerHTML = `<span>AVERAGE DELIVERY IMPROVEMENT</span><strong>+${average.toFixed(1)}%</strong><small>Semantic routing protects higher-priority flows during congestion.</small>`;
}
async function compare() { try { renderComparison(await request('/demo/compare', { method: 'POST' })); logEvent('Routing comparison complete', 'analysis'); } catch (error) { logEvent(error.message, 'error'); } }

$('congestionToggle').addEventListener('click', setCongestion); $('semanticToggle').addEventListener('click', setSemantic); $('seedBtn').addEventListener('click', seedDemo); $('demoBtn').addEventListener('click', runDemo); $('resetBtn').addEventListener('click', reset); $('classifyBtn').addEventListener('click', classify); $('compareBtn').addEventListener('click', compare);
document.querySelectorAll('.quick-picks button').forEach((button) => button.addEventListener('click', () => { $('payloadInput').value = button.dataset.payload; $('payloadInput').focus(); }));
$('payloadInput').addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') classify(); });
initCharts(); logEvent('Dashboard initialized; loading demo traffic', 'system'); seedDemo(); setInterval(refresh, 2500);
