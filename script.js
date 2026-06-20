// Initialize Map
var map = L.map('map', {zoomControl: false}).setView([12.9716, 77.5946], 12);
L.control.zoom({position: 'topleft'}).addTo(map);
var baseLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Layers
var heatLayer = null;
var markerLayer = L.layerGroup().addTo(map);
var policeLayer = L.layerGroup().addTo(map);

var currentHeatmapData = [];
var currentMarkerData = [];
var currentRankedZones = [];
var predictionMode = false;

// Init Slider
var hourSlider = document.getElementById('hourSlider');
noUiSlider.create(hourSlider, {
    start: [0, 23],
    connect: true,
    step: 1,
    range: { 'min': 0, 'max': 23 },
    format: {
        to: function (value) { return Math.round(value); },
        from: function (value) { return Number(value); }
    }
});
hourSlider.noUiSlider.on('update', function (values) {
    var min = parseInt(values[0]);
    var max = parseInt(values[1]);
    document.getElementById('hourRangeDisplay').innerText = 
        String(min).padStart(2, '0') + ':00 - ' + String(max).padStart(2, '0') + ':59';
});

// Load Filters
let datasetMinDate = null;
let datasetMaxDate = null;

fetch('/api/filters')
    .then(r => r.json())
    .then(data => {
        const tagSel = document.getElementById('tagSelect');
        data.tags.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t; opt.innerText = t;
            tagSel.appendChild(opt);
        });
        const vehSel = document.getElementById('vehicleSelect');
        data.vehicles.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v; opt.innerText = v;
            vehSel.appendChild(opt);
        });
        if (data.min_date) {
            datasetMinDate = new Date(data.min_date);
        }
        if (data.max_date) {
            datasetMaxDate = new Date(data.max_date);
        }
        // Initial load
        applyFilters();
    });

fetch('/api/police_stations')
    .then(r => r.json())
    .then(data => {
        if(data.stations) {
            data.stations.forEach(station => {
                const policeIcon = L.divIcon({
                    className: 'custom-police-icon',
                    html: '<div style="width:10px; height:10px; background:rgba(103, 58, 183, 0.9); border:2px solid #673AB7; border-radius:50%; box-shadow: 0 0 12px 3px rgba(103, 58, 183, 0.9), 0 0 4px rgba(0,0,0,0.5);"></div>',
                    iconSize: [10, 10],
                    iconAnchor: [5, 20] // Offsets the marker vertically so it doesn't overlap the hotspot center
                });
                const marker = L.marker([station.lat, station.lng], {icon: policeIcon});
                marker.bindTooltip(`<b>${station.name} Police Station</b>`, {direction: 'bottom'});
                marker.on('click', () => openPoliceStationDetails(station.name, station.lat, station.lng));
                marker.addTo(policeLayer);
            });
        }
    });

function resetFilters() {
    document.getElementById('tagSelect').value = 'ALL';
    document.getElementById('vehicleSelect').value = 'ALL';
    document.getElementById('dayOfWeekSelect').value = 'ALL';
    hourSlider.noUiSlider.set([0, 23]);
    applyFilters();
}

function applyFilters() {
    const tag = document.getElementById('tagSelect').value;
    const vehicle = document.getElementById('vehicleSelect').value;
    const dayOfWeek = document.getElementById('dayOfWeekSelect').value;
    
    const hours = hourSlider.noUiSlider.get();
    const min_h = hours[0];
    const max_h = hours[1];

    const endpoint = predictionMode ? '/api/predict_tomorrow' : '/api/scenario';
    let url = `${endpoint}?tag=${encodeURIComponent(tag)}&vehicle=${encodeURIComponent(vehicle)}&min_hour=${min_h}&max_hour=${max_h}&day_of_week=${encodeURIComponent(dayOfWeek)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if(data.status === 'insufficient_history') {
                predictionMode = false;
                updatePredictionToggle();
                alert(data.message);
                applyFilters();
                return;
            }
            currentHeatmapData = data.heatmap || [];
            currentMarkerData = data.zone_markers || [];
            currentRankedZones = predictionMode
                ? (data.ranked_zones || []).map(pz => ({
                    zone: pz.zone,
                    count: pz.count,
                    classification: 'PREDICTED',
                    cause: `Likely ${pz.profile_violation}, led by ${pz.profile_vehicle}`,
                    workforce: `${pz.neighbor_agreement_pct}% weighted neighbor agreement`,
                    patrol_window: `Around ${pz.profile_peak_hour}:00`,
                    vehicular_composition: {[pz.profile_vehicle]: pz.count},
                    peak_day: data.prediction_day_name
                }))
                : (data.ranked_zones || []);
            
            document.getElementById('zoneCountDisplay').innerText = predictionMode
                ? `${currentRankedZones.length} zones predicted`
                : `${currentRankedZones.length} zones detected`;
            
            // Update Reporting Window Display
            let displayStr = "Loading...";
            if (predictionMode) {
                displayStr = `PREDICTION MODE ON: ${data.prediction_date} | ${data.history_days} history days | K=${data.neighbor_count}`;
            } else if (data.window_start && data.window_end) {
                displayStr = `LIVE MODE: Latest ${data.window_days} days (${data.window_start} to ${data.window_end})`;
            }
            document.getElementById('reportingWindowDisplay').innerText = displayStr;

            renderLayers();
            renderRightPanel();
            updateCharts(data);
        });
}

// Chart instances
let timeChartInstance = null;
let vehicleChartInstance = null;
let violationChartInstance = null;

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    event.currentTarget.classList.add('active');
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.style.display = 'none';
    });
    
    const target = document.getElementById('tab-' + tabId);
    if(target) {
        if(tabId === 'map') target.style.display = 'flex';
        else target.style.display = 'block';
    }
    
    if(tabId === 'map') {
        setTimeout(() => map.invalidateSize(), 100);
    }
}

function updateCharts(data) {
    if(!data.time_patterns) return;
    
    const timeLabels = Array.from({length: 24}, (_, i) => i);
    const timeData = timeLabels.map(h => data.time_patterns[h] || 0);
    
    // Update the Total Graph Violations display in the Time Patterns tab
    const totalTimeViolations = timeData.reduce((sum, val) => sum + val, 0);
    const timeTabDisplay = document.getElementById('timeTabTotalDisplay');
    if (timeTabDisplay) {
        timeTabDisplay.innerText = totalTimeViolations.toLocaleString();
    }
    
    if(timeChartInstance) timeChartInstance.destroy();
    timeChartInstance = new Chart(document.getElementById('timeChart'), {
        type: 'bar',
        data: {
            labels: timeLabels,
            datasets: [{
                label: predictionMode ? 'Forecast PCU Impact' : 'Violations',
                data: timeData,
                backgroundColor: '#FFB300'
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
    
    const vehLabels = Object.keys(data.vehicle_breakdown || {});
    const vehData = vehLabels.map(l => data.vehicle_breakdown[l]);
    if(vehicleChartInstance) vehicleChartInstance.destroy();
    vehicleChartInstance = new Chart(document.getElementById('vehicleChart'), {
        type: 'bar',
        data: {
            labels: vehLabels,
            datasets: [{ label: 'Vehicles', data: vehData, backgroundColor: ['#42A5F5','#AB47BC','#EF5350','#66BB6A','#FFA726','#8D6E63'] }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { title: {display: true, text: 'Vehicle Breakdown', color:'#FFF'} } }
    });
    
    const violLabels = Object.keys(data.violation_breakdown || {});
    const violData = violLabels.map(l => data.violation_breakdown[l]);
    if(violationChartInstance) violationChartInstance.destroy();
    violationChartInstance = new Chart(document.getElementById('violationChart'), {
        type: 'bar',
        data: {
            labels: violLabels,
            datasets: [{ label: 'Violations', data: violData, backgroundColor: ['#FF1744','#D50000','#C51162','#AA00FF','#6200EA','#304FFE'] }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { title: {display: true, text: 'Violation Breakdown', color:'#FFF'} } }
    });
}

function toggleLayerUI(layerType) {
    const btnId = layerType === 'heatmap' ? 'btn-heatmap' : (layerType === 'markers' ? 'btn-hotspots' : 'btn-police');
    document.getElementById(btnId).classList.toggle('active');
    renderLayers();
}

function toggleTheme() {
    const isDark = document.getElementById('checkbox').checked;
    if (isDark) {
        document.documentElement.setAttribute('data-theme', 'dark');
        baseLayer.setUrl('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png');
    } else {
        document.documentElement.setAttribute('data-theme', 'light');
        baseLayer.setUrl('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png');
    }
}

function renderLayers() {
    if(heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
    markerLayer.clearLayers();
    
    const showHeatmap = document.getElementById('btn-heatmap').classList.contains('active');
    const showMarkers = document.getElementById('btn-hotspots').classList.contains('active');
    
    const showPolice = document.getElementById('btn-police') ? document.getElementById('btn-police').classList.contains('active') : true;
    if (showPolice) {
        if (!map.hasLayer(policeLayer)) map.addLayer(policeLayer);
    } else {
        if (map.hasLayer(policeLayer)) map.removeLayer(policeLayer);
    }

    if(showHeatmap && currentHeatmapData.length > 0) {
        const points = currentHeatmapData.map(p => [p.lat, p.lng, p.weight]);
        heatLayer = L.heatLayer(points, {
            radius: 15,
            blur: 20,
            maxZoom: 14,
            max: 1.0,
            gradient: {0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red'}
        }).addTo(map);
    } 
    
    if(showMarkers && currentMarkerData.length > 0) {
        let maxCount = 1;
        if(currentMarkerData.length > 0) {
            maxCount = Math.max(...currentMarkerData.map(m => m.count));
        }
        
        currentMarkerData.forEach(m => {
            const r = 5 + (25 * (m.count / maxCount));
            const circle = L.circleMarker([m.lat, m.lng], {
                radius: r,
                fillColor: '#FFB300',
                color: '#FFB300',
                weight: 1,
                opacity: 0.8,
                fillOpacity: 0.4
            });
            circle.bindPopup(`<b>${m.zone}</b><br/>${m.count} violations`);
            circle.on('click', () => openZoneDetails(m.zone));
            circle.addTo(markerLayer);
        });
    }
}

function renderRightPanel() {
    const list = document.getElementById('zoneList');
    list.innerHTML = '';
    
    currentRankedZones.forEach((z, i) => {
        const item = document.createElement('div');
        item.className = 'zone-item';
        item.innerHTML = `
            <div class="zone-rank">${i+1}</div>
            <div class="zone-info">
                <div class="zone-name">${z.zone} <span style="font-size:9px; background:var(--signal-amber); color:#000; padding:2px 4px; border-radius:2px; margin-left:4px;">${z.classification}</span></div>
                <div class="zone-desc">${z.cause}</div>
            </div>
            <div class="zone-score">${z.count.toLocaleString()}</div>
        `;
        item.onclick = () => openZoneDetails(z.zone);
        list.appendChild(item);
    });
}

function openZoneDetails(zoneName) {
    const zoneObj = currentRankedZones.find(z => z.zone === zoneName) || {};
    fetch('/zone_markers.json')
        .then(r => r.json())
        .then(markers => {
            const zone = markers.find(m => m.zone === zoneName);
            document.getElementById('sidebarZoneName').innerText = zoneName;
            
            let vehHtml = '';
            if (zoneObj.vehicular_composition && Object.keys(zoneObj.vehicular_composition).length > 0) {
                const total = Object.values(zoneObj.vehicular_composition).reduce((sum, val) => sum + val, 0);
                vehHtml = Object.entries(zoneObj.vehicular_composition)
                    .sort((a,b) => b[1] - a[1]).slice(0,3)
                    .map(kv => `${kv[0]}: ${((kv[1] / total) * 100).toFixed(1)}%`)
                    .join(', ');
            }
            let html = `
                <div class="strategy-card" style="border-color:var(--accent-blue);">
                    <div class="strategy-name" style="color:var(--accent-blue)">⚡ Hotspot Profile & Patrol Schedule</div>
                    <div class="strategy-action"><b>Classification:</b> ${zoneObj.classification || 'Unknown'}</div>
                    <div class="strategy-action"><b>Primary Cause:</b> ${zoneObj.cause || 'Unknown'}</div>
                    <div class="strategy-action"><b>Top Vehicles:</b> ${vehHtml || 'Unknown'}</div>
                    <div class="strategy-action"><b>Time Range of Max Activity:</b> ${zoneObj.patrol_window || 'Flexible'}</div>
                    <div class="strategy-action"><b>Peak Day:</b> ${zoneObj.peak_day || 'Unknown'}</div>
                </div>
            `;
            
            if(zone && zone.strategies) {
                zone.strategies.forEach(s => {
                    let pbHtml = '';
                    if(s.playbook) {
                        pbHtml = `
                            <div class="playbook-toggle" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'" style="cursor:pointer; color:var(--text-dim); font-size:12px; margin-top:8px;">Implementation Playbook ▼</div>
                            <div class="playbook-details" style="display:none; margin-top:8px; padding-left:8px; border-left:2px solid var(--border-color);">
                                <div class="playbook-item"><div class="playbook-label">Location Context</div><div class="playbook-value">${s.playbook.location}</div></div>
                                <div class="playbook-item"><div class="playbook-label">Scale</div><div class="playbook-value">${s.playbook.scale}</div></div>
                                <div class="playbook-item"><div class="playbook-label">Timing</div><div class="playbook-value">${s.playbook.timing}</div></div>
                            </div>
                        `;
                    }
                    html += `
                        <div class="strategy-card">
                            <div class="strategy-name">${s.name}</div>
                            <div class="strategy-action">${s.action}</div>
                            ${pbHtml}
                        </div>
                    `;
                });
            }
            document.getElementById('sidebarStrategies').innerHTML = html;
            
            // Switch to map tab if not already on it
            if (!document.getElementById('tab-map').classList.contains('active')) {
                switchTab('map');
            }
            
            document.getElementById('map-sidebar').style.display = 'block';
            setTimeout(() => map.invalidateSize(), 100);
        });
}

function closeSidebar() {
    document.getElementById('map-sidebar').style.display = 'none';
    setTimeout(() => map.invalidateSize(), 100);
}

// Haversine distance in km
function getDistance(lat1, lon1, lat2, lon2) {
    const R = 6371; // km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = 0.5 - Math.cos(dLat)/2 + 
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
              (1 - Math.cos(dLon))/2;
    return R * 2 * Math.asin(Math.sqrt(a));
}

function openPoliceStationDetails(stationName, lat, lng) {
    document.getElementById('sidebarZoneName').innerText = `${stationName} Police Station`;
    
    // Find 5 nearest active hotspots
    let distances = currentMarkerData.map(m => {
        return {
            zone: m.zone,
            count: m.count,
            dist: getDistance(lat, lng, m.lat, m.lng)
        };
    });
    distances.sort((a, b) => a.dist - b.dist);
    const top5 = distances.slice(0, 5);
    
    let html = `
        <div class="strategy-card" style="border-color:#B388FF;">
            <div class="strategy-name" style="color:#B388FF">📍 5 Nearest Hotspots</div>
    `;
    
    if(top5.length > 0) {
        top5.forEach((h, i) => {
            html += `
                <div class="strategy-action" style="margin-top:8px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border-color); padding-bottom:8px;">
                    <div>
                        <b>${i+1}. ${h.zone}</b><br>
                        <span style="font-size:12px; color:var(--text-dim);">${h.dist.toFixed(2)} km away</span>
                    </div>
                    <div style="color:var(--signal-red); font-weight:bold;">${h.count.toLocaleString()} viol.</div>
                </div>
            `;
        });
    } else {
        html += `<div class="strategy-action">No active hotspots found.</div>`;
    }
    html += `</div>`;
    
    document.getElementById('sidebarStrategies').innerHTML = html;
    
    if (!document.getElementById('tab-map').classList.contains('active')) {
        switchTab('map');
    }
    
    document.getElementById('map-sidebar').style.display = 'block';
    setTimeout(() => map.invalidateSize(), 100);
}

function submitFeedback(zoneName) {
    fetch(`/api/feedback?zone=${encodeURIComponent(zoneName)}`)
        .then(r => r.json())
        .then(data => {
            alert(data.message);
            applyFilters(); // refresh map and list
        });
}

function updatePredictionToggle() {
    const button = document.getElementById('btn-predict');
    button.classList.toggle('active', predictionMode);
    button.setAttribute('aria-pressed', predictionMode ? 'true' : 'false');
    button.innerText = predictionMode ? 'Prediction: ON' : 'Prediction: OFF';
}

function togglePrediction() {
    predictionMode = !predictionMode;
    updatePredictionToggle();
    applyFilters();
}
