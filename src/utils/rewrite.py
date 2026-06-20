import re

with open('script.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Replace variables
js = js.replace('let map, heatLayer, hotspotLayer, stationLayer;', 'let map, heatLayer = null, zoneMarkers = [], allHeatmapData = [], allZoneData = [];\nlet charts = {};\nvar DAY_NAMES = [\'Monday\', \'Tuesday\', \'Wednesday\', \'Thursday\', \'Friday\', \'Saturday\', \'Sunday\'];\nvar HOUR_NAMES = [\'12:00 AM\',\'1:00 AM\',\'2:00 AM\',\'3:00 AM\',\'4:00 AM\',\'5:00 AM\',\'6:00 AM\',\'7:00 AM\',\'8:00 AM\',\'9:00 AM\',\'10:00 AM\',\'11:00 AM\',\'12:00 PM\',\'1:00 PM\',\'2:00 PM\',\'3:00 PM\',\'4:00 PM\',\'5:00 PM\',\'6:00 PM\',\'7:00 PM\',\'8:00 PM\',\'9:00 PM\',\'10:00 PM\',\'11:00 PM\'];\n')

# Replace initDashboard
js = js.replace('[\'map\', () => { initMap(); renderHeatLayer(); buildHotspotLayer(); buildStationLayer(); renderHotspotList(); setLayer(\'heat\'); }],', '[\'map\', () => { initMap(); }],')
js = js.replace('[\'map controls\', bindMapControls],', '')
js = js.replace('[\'filter controls\', bindFilters],', '')

# Remove old map section
old_map_regex = re.compile(r'/\* ===========================================================\n   MAP\n   ===========================================================\ \*/.*?/\* ===========================================================\n   ROSTER GRID', re.DOTALL)

our_map_logic = '''/* ===========================================================
   MAP & SCENARIO ENGINE
   =========================================================== */
function initMap(){
  map = L.map('map', {scrollWheelZoom:true, zoomControl:true}).setView([12.9716, 77.5946], 12);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution:'&copy; OpenStreetMap contributors &copy; CARTO',
    subdomains:'abcd',
    maxZoom:19
  }).addTo(map);
  
  loadMapData();
}

function loadMapData() {
    Promise.all([
        fetch('heatmap_points.json').then(r => r.json()),
        fetch('zone_markers.json').then(r => r.json())
    ]).then(function ([heatmapData, markerData]) {
        allHeatmapData = heatmapData;
        allZoneData = markerData;

        renderHeatmap(heatmapData);
        renderZoneMarkers(markerData);
        updateStats(markerData);

        let el = document.getElementById('loadingOverlay');
        if(el) el.classList.add('hidden');
    }).catch(function (err) {
        console.error('Error loading map data:', err);
        let txt = document.querySelector('.loading-text');
        if(txt) txt.textContent = 'Error loading data. Run: python generate_map_data.py';
    });
}

function renderHeatmap(data) {
    if (heatLayer) {
        map.removeLayer(heatLayer);
    }
    var step = Math.max(1, Math.floor(data.length / 10000));
    var sampledData = [];
    for (var i = 0; i < data.length; i += step) {
        sampledData.push([data[i].lat, data[i].lng, 1]);
    }

    heatLayer = L.heatLayer(sampledData, {
        radius: 15,
        blur: 15,
        maxZoom: 17,
        max: 1.0,
        gradient: {
            0.0: 'rgba(0, 230, 118, 0)',
            0.4: 'rgba(0, 230, 118, 0.8)',
            0.6: 'rgba(255, 234, 0, 0.8)',
            0.8: 'rgba(255, 145, 0, 0.8)',
            1.0: 'rgba(255, 23, 68, 1)'
        }
    }).addTo(map);
}

function renderZoneMarkers(data) {
    zoneMarkers.forEach(function (m) { map.removeLayer(m); });
    zoneMarkers = [];

    data.forEach(function (zone) {
        var size = Math.max(20, Math.min(50, zone.pcu_impact / 10));
        var markerHtml =
            '<div style="' +
                'width:' + size + 'px;' +
                'height:' + size + 'px;' +
                'background:' + zone.color + ';' +
                'border-radius:50%;' +
                'border:2px solid rgba(255,255,255,0.5);' +
                'box-shadow:0 0 ' + (size/2) + 'px ' + zone.color + '60;' +
                'display:flex;align-items:center;justify-content:center;' +
                'font-size:9px;font-weight:700;color:#fff;' +
                'cursor:pointer;' +
                'font-family:Inter,sans-serif;' +
                'transition:transform 0.2s;' +
            '">' + zone.strategy_count + '</div>';

        var customIcon = L.divIcon({ html: markerHtml, className: '', iconSize: [size, size], iconAnchor: [size/2, size/2] });

        var popupContent =
            '<div class="custom-popup">' +
                '<h4 style="color:' + zone.color + ';">' + zone.zone + '</h4>' +
                '<p><strong>PCU Impact:</strong> ' + zone.pcu_impact + ' (' + zone.severity + ')</p>' +
                '<p><strong>Type:</strong> ' + zone.archetype + '</p>' +
                '<p><strong>Strategies:</strong> ' + zone.strategy_count + '</p>' +
                '<p style="font-size:10px;color:#999;margin-top:4px;">Click for full details</p>' +
            '</div>';

        var marker = L.marker([zone.lat, zone.lng], { icon: customIcon }).addTo(map);
        marker.bindPopup(popupContent);

        marker.on('click', function () { showZonePanel(zone); });
        zoneMarkers.push(marker);
    });
}

function showZonePanel(zone) {
    var panel = document.getElementById('zonePanel');
    var title = document.getElementById('zonePanelTitle');
    var body = document.getElementById('zonePanelBody');

    title.textContent = zone.zone;

    var severityColor = zone.color;
    var severityClass = zone.pcu_impact > 50 ? 'critical' : zone.pcu_impact > 25 ? 'high' : 'moderate';

    var twPct = zone.two_wheeler_pct;
    var autoPct = zone.auto_pct;
    var heavyPct = zone.heavy_pct;
    var otherPct = Math.max(0, 100 - twPct - autoPct - heavyPct);

    var strategiesHtml = '';
    zone.strategies.forEach(function (s) {
        var pb = s.playbook;
        var pbHtml = '';
        if (pb) {
            pbHtml = 
                '<div class="playbook-toggle">Implementation Playbook ' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>' +
                '</div>' +
                '<div class="playbook-details">' +
                    '<div class="playbook-item"><div class="playbook-label">Location Context</div><div class="playbook-value">' + pb.location + '</div></div>' +
                    '<div class="playbook-item"><div class="playbook-label">Capacity / Scale</div><div class="playbook-value">' + pb.scale + '</div></div>' +
                    '<div class="playbook-item"><div class="playbook-label">Timing</div><div class="playbook-value">' + pb.timing + '</div></div>' +
                    '<div class="playbook-item"><div class="playbook-label">Personnel</div><div class="playbook-value">' + pb.personnel + '</div></div>' +
                    '<div class="playbook-item"><div class="playbook-label">Materials</div><div class="playbook-value">' + pb.materials + '</div></div>' +
                    '<div class="playbook-item"><div class="playbook-label">Coordination</div><div class="playbook-value">' + pb.coordination + '</div></div>' +
                '</div>';
        }

        strategiesHtml +=
            '<div class="strategy-card ' + (pb ? 'has-playbook' : '') + '" onclick="this.classList.toggle(\'expanded\')">' +
                '<div class="strategy-name">' + s.name + '</div>' +
                '<div class="strategy-source">' + s.source + '</div>' +
                '<div class="strategy-action">' + s.action + '</div>' +
                '<div class="strategy-reason">' + s.reason + '</div>' +
                pbHtml +
            '</div>';
    });

    body.innerHTML =
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">' +
            '<span class="zone-severity-badge" style="background:' + severityColor + '20;color:' + severityColor + ';">' +
                zone.severity +
            '</span>' +
            '<span style="font-size:11px;color:#6b7394;">' + zone.archetype + '</span>' +
        '</div>' +
        '<div class="zone-stats-grid">' +
            '<div class="zone-stat">' +
                '<div class="zone-stat-label">PCU Impact</div>' +
                '<div class="zone-stat-value ' + severityClass + '">' + zone.pcu_impact + '</div>' +
            '</div>' +
            '<div class="zone-stat">' +
                '<div class="zone-stat-label">Strategies</div>' +
                '<div class="zone-stat-value">' + zone.strategy_count + '</div>' +
            '</div>' +
            '<div class="zone-stat">' +
                '<div class="zone-stat-label">Historical</div>' +
                '<div class="zone-stat-value">' + zone.historical_violations.toLocaleString() + '</div>' +
            '</div>' +
            '<div class="zone-stat">' +
                '<div class="zone-stat-label">Neighbor PCU</div>' +
                '<div class="zone-stat-value">' + zone.spatial_lag_pcu + '</div>' +
            '</div>' +
        '</div>' +
        '<div class="vehicle-bar-container">' +
            '<h4>Vehicle Composition</h4>' +
            '<div class="vehicle-bar">' +
                '<div style="width:' + twPct + '%;background:#42A5F5;"></div>' +
                '<div style="width:' + autoPct + '%;background:#AB47BC;"></div>' +
                '<div style="width:' + heavyPct + '%;background:#EF5350;"></div>' +
                '<div style="width:' + otherPct + '%;background:#66BB6A;"></div>' +
            '</div>' +
            '<div class="vehicle-bar-labels">' +
                '<div class="vehicle-bar-label"><div class="dot" style="background:#42A5F5;"></div> 2W ' + twPct + '%</div>' +
                '<div class="vehicle-bar-label"><div class="dot" style="background:#AB47BC;"></div> Auto ' + autoPct + '%</div>' +
                '<div class="vehicle-bar-label"><div class="dot" style="background:#EF5350;"></div> Heavy ' + heavyPct + '%</div>' +
                '<div class="vehicle-bar-label"><div class="dot" style="background:#66BB6A;"></div> Other ' + otherPct.toFixed(1) + '%</div>' +
            '</div>' +
        '</div>' +
        '<div style="margin-top:12px;font-size:11px;color:#6b7394;">' +
            '<span>Validation: ' + zone.validation_ratio_pct + '%</span> &bull; ' +
            '<span>' + zone.distance_to_cbd_km + ' km from CBD</span>' +
        '</div>' +
        '<div class="strategies-section">' +
            '<h4>Recommended Strategies (' + zone.strategy_count + ')</h4>' +
            strategiesHtml +
        '</div>';

    panel.classList.add('active');
}

function closeZonePanel() {
    document.getElementById('zonePanel').classList.remove('active');
}

function updateScenario() {
    var day = parseInt(document.getElementById('daySelect').value);
    var hour = parseInt(document.getElementById('hourSelect').value);

    document.getElementById('scenarioBadge').textContent = DAY_NAMES[day] + ' ' + HOUR_NAMES[hour] + ' IST';

    var btn = document.querySelector('.controls-panel button');
    var originalText = btn.textContent;
    btn.textContent = "Updating...";
    btn.disabled = true;

    fetch('/api/scenario?day=' + day + '&hour=' + hour)
        .then(res => {
            if (!res.ok) throw new Error("Server error");
            return res.json();
        })
        .then(data => {
            renderZoneMarkers(data);
            btn.textContent = originalText;
            btn.disabled = false;
        })
        .catch(err => {
            console.error("Error updating scenario:", err);
            alert("Failed to update scenario. Make sure you are running 'python server.py' instead of http.server.");
            btn.textContent = originalText;
            btn.disabled = false;
        });
}

function toggleLayer(layer) {
    if (layer === 'heatmap') {
        var visible = document.getElementById('toggleHeatmap').checked;
        if (visible) {
            if (!heatLayer) {
                renderHeatmap(allHeatmapData);
            }
        } else {
            if (heatLayer) {
                map.removeLayer(heatLayer);
                heatLayer = null;
            }
        }
    }
    if (layer === 'markers') {
        var visible = document.getElementById('toggleMarkers').checked;
        zoneMarkers.forEach(function (m) {
            if (!visible) {
                map.removeLayer(m);
            }
        });
        if (visible) {
            renderZoneMarkers(allZoneData);
        }
    }
}

function updateStats(markers) {
    document.getElementById('zoneCount').textContent = markers.length;
    document.getElementById('criticalCount').textContent =
        markers.filter(function (m) { return m.severity === 'CRITICAL'; }).length;
}

/* ===========================================================
   ROSTER GRID'''

js = old_map_regex.sub(our_map_logic, js)

getFilteredPoints_regex = re.compile(r'function getFilteredPoints\(\).*?\}\n', re.DOTALL)
js = getFilteredPoints_regex.sub('', js)

with open('script.js', 'w', encoding='utf-8') as f:
    f.write(js)

print('script.js updated successfully.')
