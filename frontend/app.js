const API_BASE = 'http://localhost:5000/api';

// State Tracking
let isCongested = false;
let isQosEnabled = false;

// Elements
const btnCongestion = document.getElementById('btn-congestion');
const btnQos = document.getElementById('btn-qos');

const valEmergency = document.getElementById('val-emergency');
const valSensor = document.getElementById('val-sensor');
const valVideo = document.getElementById('val-video');
const valFile = document.getElementById('val-file');

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
      y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' }, beginAtZero: true, max: 100 }
    },
    plugins: {
      legend: { labels: { color: '#f8fafc' } }
    }
  }
});

// Toggle Handlers
btnCongestion.addEventListener('click', async () => {
  isCongested = !isCongested;
  btnCongestion.textContent = `Simulate Congestion: ${isCongested ? 'ON' : 'OFF'}`;
  btnCongestion.className = isCongested 
    ? 'px-5 py-2.5 rounded-lg bg-red-700 font-bold border-2 border-white text-white shadow-lg' 
    : 'px-5 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold shadow-lg';
  
  try {
    await fetch(`${API_BASE}/toggle_congestion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ congestion: isCongested })
    });
  } catch (err) {
    console.warn('Backend server not connected yet. Running in offline UI mode.');
  }
});

btnQos.addEventListener('click', async () => {
  isQosEnabled = !isQosEnabled;
  btnQos.textContent = `AI Priority (QoS): ${isQosEnabled ? 'ON' : 'OFF'}`;
  btnQos.className = isQosEnabled 
    ? 'px-5 py-2.5 rounded-lg bg-emerald-700 font-bold border-2 border-white text-white shadow-lg' 
    : 'px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-lg';

  try {
    await fetch(`${API_BASE}/toggle_qos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qos_enabled: isQosEnabled })
    });
  } catch (err) {
    console.warn('Backend server not connected yet. Running in offline UI mode.');
  }
});

// Live Metrics Fetcher
async function fetchMetrics() {
  try {
    const res = await fetch(`${API_BASE}/metrics`);
    const data = await res.json();
    
    updateUI(data.emergency || 0, data.sensor || 0, data.video || 0, data.file || 0);
  } catch (err) {
    // Fallback dummy data generation if backend isn't running yet
    const timeNow = new Date().toLocaleTimeString();
    updateUI(20, 30, 40, 50, timeNow);
  }
}

function updateUI(emergency, sensor, video, file, timeStamp = new Date().toLocaleTimeString()) {
  // Update Text Cards
  valEmergency.innerHTML = `${emergency} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valSensor.innerHTML = `${sensor} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valVideo.innerHTML = `${video} <span class="text-sm font-normal text-slate-400">Mbps</span>`;
  valFile.innerHTML = `${file} <span class="text-sm font-normal text-slate-400">Mbps</span>`;

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

// Poll every 1 second
setInterval(fetchMetrics, 1000);