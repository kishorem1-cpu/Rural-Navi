/**
 * Rural Navi — Frontend Engine
 * -----------------------------
 * Powers the interactive Leaflet map, multi-factor search,
 * stakeholder mode switching, compass bearing, arrival radar,
 * privacy-preserving QR generation, and bilingual Tamil/English UI.
 */

// Global State
let currentLanguage = 'en'; // 'en' or 'ta'
let currentMode = 'delivery'; // 'delivery', 'resident', 'field'
let currentTarget = null;
let leafletMap = null;
let markersLayer = null;
let deviceHeading = null;
let compassSensorActive = false;
let watchPositionId = null;

// Bilingual Translations Dictionary
const translations = {
  en: {
    brandSub: "Civic Address Identification & Navigation Platform",
    tabDelivery: "Delivery Personnel",
    tabResident: "Resident Self-Check",
    tabField: "Healthcare & Emergency",
    tabKiosk: "Public Kiosk",
    searchTitle: "Search Panchayat House",
    lblVillage: "Select Village / Panchayat:",
    lblDoor: "Panchayat Door / House Number:",
    btnFind: "Find",
    searchHint: "Supports door formats: 3-82, 3/82, 03-82. Resolves directly to verified GPS coordinates.",
    offlineMsg: "Offline Mode Active — Using cached village address directory",
    headingNavReady: "Active Waypoint Guidance",
    btnCompass: "Enable Compass",
    btnArrival: "Verify Arrival (GPS)",
    qrModalTitle: "Panchayat Smart Door QR Plate",
    qrNotice: "This QR code uses an opaque navigation token. It allows instant phone navigation without revealing personal resident identities or phone numbers.",
    reportModalTitle: "Report Address Issue or Correction",
    lblIssueType: "Issue Type:",
    lblDescription: "Description / Observations:",
    btnSubmitReport: "Submit for Review",
    exactMatch: "Verified Record Found",
    multipleMatches: "Ambiguity Detected — Multiple Houses Match",
    noMatch: "No Verified Record Found",
    confidenceHigh: "High Confidence (Panchayat Verified)",
    confidenceMed: "Medium Confidence",
    confidenceLow: "Low Confidence / Approximate",
    btnNavigate: "Start Navigation",
    btnReport: "Report Issue",
    btnViewQR: "Show QR Plate"
  },
  ta: {
    brandSub: "ஊரக உள்ளாட்சி முகவரி தேடல் மற்றும் வழிகாட்டு தளம்",
    tabDelivery: "டெலிவரி பணியாளர்",
    tabResident: "குடிமக்கள் முகவரி சரிபார்ப்பு",
    tabField: "சுகாதாரம் & அவசர உதவி",
    tabKiosk: "பொது உதவி மையம் (Kiosk)",
    searchTitle: "பஞ்சாயத்து கதவு எண் தேடுக",
    lblVillage: "கிராமம் / பஞ்சாயத்து தேர்வு செய்க:",
    lblDoor: "பஞ்சாயத்து கதவு எண்:",
    btnFind: "தேடு",
    searchHint: "எ.கா: 3-82, 3/82, 03-82. பஞ்சாயத்து ஆவணப்படி சரிபார்க்கப்பட்ட GPS இருப்பிடத்தை காட்டும்.",
    offlineMsg: "ஆஃப்லைன் பயன்முறை — தற்காலிக சேமிப்பில் உள்ள முகவரிகள் பயன்படுகின்றன",
    headingNavReady: "நேரடி வழிகாட்டுதல்",
    btnCompass: "திசைகாட்டி இயக்கு",
    btnArrival: "வந்தடைந்ததை உறுதிசெய்",
    qrModalTitle: "பஞ்சாயத்து கதவு QR பலகை",
    qrNotice: "இந்த QR குறியீடு தனிநபர் விவரங்களை வெளிப்படுத்தாமல், இருப்பிடத்தை மட்டும் துல்லியமாக திறக்கும்.",
    reportModalTitle: "இருப்பிட பிழை / புகார் பதிவு",
    lblIssueType: "பிரச்சனை வகை:",
    lblDescription: "விவரம் / அடையாளங்கள்:",
    btnSubmitReport: "புகார் சமர்ப்பி",
    exactMatch: "சரிபார்க்கப்பட்ட முகவரி கிடைத்தது",
    multipleMatches: "ஒரே எண்ணில் பல வீடுகள் உள்ளன — வார்டை தேர்வு செய்க",
    noMatch: "சரிபார்க்கப்பட்ட முகவரி ஆவணத்தில் இல்லை",
    confidenceHigh: "உயர் நம்பகத்தன்மை (பஞ்சாயத்து சான்றளிக்கப்பட்டது)",
    confidenceMed: "நடுத்தர நம்பகத்தன்மை",
    confidenceLow: "தோராயமான இருப்பிடம்",
    btnNavigate: "வழிகாட்டுதலை தொடங்கு",
    btnReport: "பிழை புகார்",
    btnViewQR: "QR பலகை காண்க"
  }
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadVillages();
  setupNetworkMonitoring();

  // Check URL parameters for mode
  const urlParams = new URLSearchParams(window.location.search);
  const modeParam = urlParams.get('mode');
  if (modeParam && ['delivery', 'resident', 'field'].includes(modeParam)) {
    switchMode(modeParam);
  }
});

// 1. LEAFLET INTERACTIVE MAP INITIALIZATION
function initMap() {
  // Default centered at Madurai district rural cluster (approx 9.925, 78.119)
  leafletMap = L.map('map', { zoomControl: true }).setView([9.55, 77.85], 10);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors | Rural Navi Civic Data'
  }).addTo(leafletMap);

  markersLayer = L.layerGroup().addTo(leafletMap);
}

// 2. VILLAGE DIRECTORY LOADING
async function loadVillages() {
  try {
    const res = await fetch('/api/villages');
    const data = await res.json();
    if (data.success && data.villages) {
      const select = document.getElementById('villageSelect');
      data.villages.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = `${v.name} (${v.name_ta || ''}) - ${v.block}`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Could not load dynamic villages, using cached fallback", err);
  }
}

// 3. STAKEHOLDER MODE SWITCHER
function switchMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach(t => {
    t.classList.toggle('active', t.getAttribute('data-mode') === mode);
  });

  const badge = document.getElementById('currentRoleBadge');
  const sub = document.getElementById('modeSubheading');

  if (mode === 'delivery') {
    badge.textContent = "Delivery Mode";
    sub.textContent = "Fast Turn-by-Turn Delivery Workflow";
  } else if (mode === 'resident') {
    badge.textContent = "Resident Portal";
    sub.textContent = "Panchayat Door Verification & QR Generator";
  } else if (mode === 'field') {
    badge.textContent = "Healthcare / ASHA";
    sub.textContent = "Emergency Wayfinding & Rapid Access";
  }
}

// 4. BILINGUAL LANGUAGE TOGGLE
function toggleLanguage() {
  currentLanguage = (currentLanguage === 'en') ? 'ta' : 'en';
  applyLanguage();
}

function applyLanguage() {
  const dict = translations[currentLanguage];
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) {
      el.textContent = dict[key];
    }
  });
  document.getElementById('langToggleBtn').textContent = (currentLanguage === 'en') ? "தமிழ்" : "English";
}

// 5. ADDRESS SEARCH EXECUTION (Ambiguity-Aware)
async function executeSearch() {
  const rawQuery = document.getElementById('houseInput').value.trim();
  const villageId = document.getElementById('villageSelect').value;
  const resultsContainer = document.getElementById('resultsContainer');

  if (!rawQuery) return;

  resultsContainer.style.display = 'block';
  resultsContainer.innerHTML = '<div style="padding:16px; text-align:center; color:var(--muted);">Searching rural address database...</div>';

  try {
    let url = `/api/search?q=${encodeURIComponent(rawQuery)}`;
    if (villageId) url += `&village_id=${encodeURIComponent(villageId)}`;

    const res = await fetch(url);
    const data = await res.json();

    if (!data.success || data.count === 0) {
      renderNoMatch(rawQuery);
      return;
    }

    renderSearchResults(data);

  } catch (err) {
    resultsContainer.innerHTML = `
      <div class="card" style="border-left: 4px solid var(--red);">
        <p style="color:var(--red); font-weight:700;">Connection failed.</p>
        <p style="font-size:0.85rem; color:var(--muted);">Check if backend app.py server is running.</p>
      </div>`;
    console.error(err);
  }
}

// RENDER: SEARCH RESULTS
function renderSearchResults(data) {
  const container = document.getElementById('resultsContainer');
  const dict = translations[currentLanguage];
  container.innerHTML = '';
  markersLayer.clearLayers();

  const bounds = [];

  // Ambiguity notification banner if multiple matches
  if (data.match_type === 'MULTIPLE_MATCHES') {
    const banner = document.createElement('div');
    banner.className = 'ambiguity-notice';
    banner.innerHTML = `
      <strong>⚠ ${dict.multipleMatches} (${data.count})</strong><br>
      Please check the landmark and ward number to select the correct property.
    `;
    container.appendChild(banner);
  }

  data.results.forEach((item, index) => {
    const card = document.createElement('div');
    card.className = 'match-card';

    // Confidence badge styling
    let confClass = 'high';
    if (item.confidence_tier === 'MEDIUM') confClass = 'medium';
    else if (item.confidence_tier === 'LOW') confClass = 'low';
    else if (item.confidence_tier === 'DISPUTED') confClass = 'disputed';

    card.innerHTML = `
      <div class="match-header">
        <div>
          <span class="house-number-badge">Door ${item.house_no}</span>
          <div class="match-sub">${item.village_name} (Ward ${item.ward_no})</div>
        </div>
        <span class="confidence-pill ${confClass}" title="Calculated from source authority and GPS precision">
          ★ ${item.confidence_tier} (${item.confidence_score}%)
        </span>
      </div>

      <div class="landmark-box">
        <strong>Landmark:</strong> ${item.landmark || 'No specific landmark recorded'}
      </div>

      <div class="action-row">
        <button class="btn-action btn-navigate" onclick="selectDestination(${item.lat}, ${item.lng}, '${item.house_no}', '${item.landmark}')">
          <span>📍</span> ${dict.btnNavigate}
        </button>
        <button class="btn-action btn-qr" onclick="showQRCode('${item.house_no}', ${item.lat}, ${item.lng})">
          <span>📲</span> ${dict.btnViewQR}
        </button>
        <button class="btn-action btn-report" onclick="openReportModal(${item.id})">
          <span>⚠</span> ${dict.btnReport}
        </button>
      </div>
    `;

    container.appendChild(card);

    // Add marker to Leaflet map
    const marker = L.marker([item.lat, item.lng]).addTo(markersLayer);
    marker.bindPopup(`
      <strong>Door ${item.house_no}</strong><br>
      ${item.village_name} (Ward ${item.ward_no})<br>
      <em>${item.landmark}</em><br>
      <small>Confidence: ${item.confidence_tier} (${item.confidence_score}%)</small>
    `);
    bounds.push([item.lat, item.lng]);

    // If exact single match, automatically select it
    if (data.count === 1) {
      selectDestination(item.lat, item.lng, item.house_no, item.landmark);
    }
  });

  if (bounds.length > 0) {
    leafletMap.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
  }
}

// RENDER: NO MATCH FOUND
function renderNoMatch(rawQuery) {
  const container = document.getElementById('resultsContainer');
  const dict = translations[currentLanguage];
  container.innerHTML = `
    <div class="card" style="border-left: 4px solid var(--amber);">
      <h3 style="color:var(--amber); margin-bottom:6px;">${dict.noMatch}</h3>
      <p style="font-size:0.9rem; color:var(--ink);">No verified GPS record found for house number <strong>"${rawQuery}"</strong> in this village directory.</p>
      <p style="font-size:0.82rem; color:var(--muted); margin-top:8px;">
        Please check with the Panchayat office or submit a request to survey and add this door number.
      </p>
      <button class="btn-action btn-report" style="margin-top:10px;" onclick="openReportModal(null)">
        Submit New House Addition Request
      </button>
    </div>
  `;
}

// 6. SELECT ACTIVE DESTINATION & TURN-BY-TURN
function selectDestination(lat, lng, houseNo, landmark) {
  currentTarget = { lat, lng, houseNo };

  const navCard = document.getElementById('activeTargetCard');
  navCard.style.display = 'block';
  document.getElementById('activeHouseTitle').textContent = `Door ${houseNo} — ${landmark}`;

  leafletMap.setView([lat, lng], 17);

  // Start live direction tracking
  startLiveTracking();
}

// 7. COMPASS & BEARING CALCULATIONS
function toRad(deg) { return deg * Math.PI / 180; }

function calculateBearing(lat1, lng1, lat2, lng2) {
  const y = Math.sin(toRad(lng2 - lng1)) * Math.cos(toRad(lat2));
  const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
            Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lng2 - lng1));
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function startLiveTracking() {
  if (watchPositionId !== null) {
    navigator.geolocation.clearWatch(watchPositionId);
  }
  if (!navigator.geolocation || !currentTarget) return;

  watchPositionId = navigator.geolocation.watchPosition(pos => {
    window.userCoords = pos.coords;
    updateBearingUI();
  }, err => {
    console.log("GPS tracking not available or denied", err);
  }, { enableHighAccuracy: true, maximumAge: 3000 });
}

function updateBearingUI() {
  if (!currentTarget || !window.userCoords) return;

  const bearing = calculateBearing(
    window.userCoords.latitude, window.userCoords.longitude,
    currentTarget.lat, currentTarget.lng
  );

  document.getElementById('compassBearingText').textContent = `Bearing: ${Math.round(bearing)}° toward door`;

  const needle = document.getElementById('compassNeedle');
  const turnText = document.getElementById('compassTurnText');

  if (compassSensorActive && deviceHeading !== null) {
    const rel = (bearing - deviceHeading + 360) % 360;
    needle.style.transform = `rotate(${rel}deg)`;

    if (rel >= 335 || rel < 25) turnText.textContent = "Head Straight Ahead";
    else if (rel >= 25 && rel < 160) turnText.textContent = "Bear Right";
    else if (rel >= 160 && rel < 200) turnText.textContent = "Turn Around";
    else turnText.textContent = "Bear Left";
  } else {
    needle.style.transform = `rotate(${bearing}deg)`;
    turnText.textContent = `Head in bearing ${Math.round(bearing)}°`;
  }
}

function toggleCompassSensor() {
  const btn = document.getElementById('enableCompassBtn');
  if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
    DeviceOrientationEvent.requestPermission().then(res => {
      if (res === 'granted') {
        window.addEventListener('deviceorientation', onOrientationChange);
        compassSensorActive = true;
        btn.textContent = "🧭 Compass Active";
      }
    });
  } else if ('DeviceOrientationEvent' in window) {
    window.addEventListener('deviceorientation', onOrientationChange, true);
    compassSensorActive = true;
    btn.textContent = "🧭 Compass Active";
  } else {
    alert("Device orientation sensing not supported by this browser.");
  }
}

function onOrientationChange(e) {
  if (typeof e.webkitCompassHeading === 'number') {
    deviceHeading = e.webkitCompassHeading;
  } else if (e.alpha !== null) {
    deviceHeading = 360 - e.alpha;
  }
  updateBearingUI();
}

// 8. GPS ARRIVAL VERIFICATION & RADAR GAUGE
function haversineMeters(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
            Math.sin(dLng / 2) ** 2;
  return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

function triggerArrivalVerification() {
  if (!currentTarget) return;

  const box = document.getElementById('arrivalBox');
  const title = document.getElementById('arrivalStatusTitle');
  const distText = document.getElementById('arrivalDistanceText');
  const bar = document.getElementById('radarGaugeBar');
  const sub = document.getElementById('arrivalSubText');

  box.style.display = 'block';
  title.textContent = "Acquiring precision GPS fix...";
  bar.style.width = "10%";

  if (!navigator.geolocation) {
    title.textContent = "Geolocation unavailable";
    return;
  }

  navigator.geolocation.getCurrentPosition(pos => {
    const dist = haversineMeters(
      pos.coords.latitude, pos.coords.longitude,
      currentTarget.lat, currentTarget.lng
    );

    const roundedDist = Math.round(dist);
    distText.textContent = `${roundedDist} m away`;

    // Calculate gauge % (0m = 100% green arrive, 100m = 0%)
    const pct = Math.max(5, Math.min(100, 100 - (roundedDist / 100) * 100));
    bar.style.width = `${pct}%`;

    if (dist <= 25) {
      title.textContent = "✓ Doorway Arrival Verified!";
      title.style.color = "var(--green)";
      sub.textContent = `You are within ${roundedDist}m of the verified Panchayat doorway coordinate.`;
    } else if (dist <= 80) {
      title.textContent = "Almost There (~Nearby)";
      title.style.color = "var(--amber)";
      sub.textContent = `You are approximately ${roundedDist}m away. Look for nearby landmarks.`;
    } else {
      title.textContent = "Not at Destination Yet";
      title.style.color = "var(--red)";
      sub.textContent = `You are ${roundedDist}m away from the verified location.`;
    }
  }, err => {
    title.textContent = "Location Access Denied";
    sub.textContent = "Please enable GPS permission to verify arrival.";
  }, { enableHighAccuracy: true });
}

// 9. QR GENERATION ENCODING DIRECT GOOGLE MAPS DESTINATION URL
function showQRCode(houseNo, lat, lng) {
  document.getElementById('qrHouseDisplay').textContent = `Panchayat Door ${houseNo}`;
  const qrDiv = document.getElementById('qrCanvas');
  qrDiv.innerHTML = '';

  // Direct universal Google Maps destination URL
  const destinationUrl = `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;

  new QRCode(qrDiv, {
    text: destinationUrl,
    width: 180,
    height: 180,
    colorDark: "#1A3D2C",
    colorLight: "#FFFFFF",
    correctLevel: QRCode.CorrectLevel.M
  });

  openModal('qrModal');
}

// 10. CORRECTION & REPORTING WORKFLOW
function openReportModal(houseId) {
  document.getElementById('reportHouseId').value = houseId || '';
  document.getElementById('reportDescription').value = '';
  openModal('reportModal');
}

async function submitIssueReport() {
  const houseId = document.getElementById('reportHouseId').value;
  const reportType = document.getElementById('reportTypeSelect').value;
  const desc = document.getElementById('reportDescription').value.trim();

  try {
    const res = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        house_id: houseId ? parseInt(houseId) : null,
        report_type: reportType,
        reporter_role: currentMode,
        description: desc
      })
    });
    const data = await res.json();
    if (data.success) {
      alert("Thank you. Your address report has been securely registered for Panchayat administrative review.");
      closeModal('reportModal');
    }
  } catch (err) {
    alert("Could not submit report. Please try again.");
  }
}

// 11. MODAL HELPERS
function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// 12. OFFLINE DETECTION & RESILIENCE
function setupNetworkMonitoring() {
  const banner = document.getElementById('offlineBanner');
  window.addEventListener('offline', () => {
    banner.classList.add('active');
  });
  window.addEventListener('online', () => {
    banner.classList.remove('active');
  });
  if (!navigator.onLine) {
    banner.classList.add('active');
  }
}