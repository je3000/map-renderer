const form = document.querySelector("#map-form");
const API_BASE_URL = (window.TOPO_API_URL || "").replace(/\/$/, "");
const apiUrl = (path) => `${API_BASE_URL}${path}`;
const currStatus = document.querySelector("#status");
const download = document.querySelector("#download");
const tryAgain = document.querySelector("#retry");
const button = document.querySelector("#render");
const drawToggle = document.querySelector("#draw-toggle");
const searchForm = document.querySelector("#search-form");
const searchInput = document.querySelector("#search-input");
const searchStatus = document.querySelector("#search-status");
const mapContainer = document.querySelector("#map-container");
const resultContainer = document.querySelector("#result-container");
const workspaceMain = document.querySelector("#workspace-main");
const settingsToggle = document.querySelector("#settings-toggle");
const settingsMenu = document.querySelector("#settings-menu");
const transparentBackgroundBox = document.querySelector("#transparentBackground");
const modeInput = document.querySelector('input[name="mode"]');
const loadingOverlay = document.querySelector("#loading-overlay");
const resultLoading = document.querySelector("#result-loading");
const formatSelect = document.querySelector('select[name="format"]');
const longSideSetting = document.querySelector(".long-side");
const transparentSetting = document.querySelector("#transparentSetting");
document.querySelector(".fill-water").style.display = "none";

function updateFormatSettings() {
  longSideSetting.style.display = formatSelect.value === "svg" ? "none" : "grid";
  transparentSetting.style.display = "flex";
}

formatSelect.addEventListener("change", updateFormatSettings);
updateFormatSettings();

function setInterfaceBusy(busy) {
  document.body.classList.toggle("ui-busy", busy);
  loadingOverlay.classList.toggle("hidden", !(busy && selectedMode === "water"));
  document.querySelectorAll("button, input, select").forEach((control) => {
    control.disabled = busy;
  });
}
const visualContainer = document.querySelector("#visual-container");
const waterSetting = document.querySelector(".water");
const visualHeight = visualContainer.getBoundingClientRect().height;
visualContainer.style.height = `${visualHeight}px`;
visualContainer.style.flex = `0 0 ${visualHeight}px`;
let selectedMode = "topo";
const preferencesKey = "topo-renderer-preferences";

try {
  const preferences = JSON.parse(localStorage.getItem(preferencesKey) || "{}");
  document.querySelectorAll("#map-form [name]").forEach((control) => {
    if (!(control.name in preferences)) return;
    if (control.type === "checkbox") control.checked = preferences[control.name];
    else control.value = preferences[control.name];
  });
  selectedMode = preferences.mode || selectedMode;
  modeInput.value = selectedMode;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.mode === selectedMode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
} catch (error) {
  console.warn("Could not restore saved preferences:", error);
}
document.querySelector(".fill-water").style.display = selectedMode === "water" ? "flex" : "none";
document.querySelector(".interval").style.display = selectedMode === "water" ? "none" : "grid";

function savePreferences() {
  const preferences = { mode: selectedMode };
  document.querySelectorAll("#map-form [name]").forEach((control) => {
    preferences[control.name] = control.type === "checkbox" ? control.checked : control.value;
  });
  localStorage.setItem(preferencesKey, JSON.stringify(preferences));
}

document.querySelectorAll("#map-form [name]").forEach((control) => {
  control.addEventListener("change", savePreferences);
});

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((item) => {
    const active = item === tab;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  selectedMode = tab.dataset.mode;
  modeInput.value = selectedMode;
  document.querySelector(".interval").style.display = tab.dataset.mode === "water" ? "none" : "grid";
  document.querySelector(".fill-water").style.display = tab.dataset.mode === "water" ? "flex" : "none";
  if (waterSetting) waterSetting.style.display = tab.dataset.mode === "water" ? "none" : "grid";
  savePreferences();
}));

settingsToggle.addEventListener("click", () => {
  const open = settingsToggle.getAttribute("aria-expanded") === "true";
  settingsToggle.setAttribute("aria-expanded", String(!open));
  settingsMenu.setAttribute("aria-hidden", String(open));
  settingsMenu.classList.toggle("open", !open);
});

document.addEventListener("pointerdown", (event) => {
  const menuIsOpen = settingsMenu.classList.contains("open");
  if (!menuIsOpen || settingsMenu.contains(event.target) || settingsToggle.contains(event.target)) return;
  settingsToggle.setAttribute("aria-expanded", "false");
  settingsMenu.setAttribute("aria-hidden", "true");
  settingsMenu.classList.remove("open");
});

document.querySelectorAll('input[type="color"]').forEach((picker) => {
  picker.addEventListener("change", () => {
    settingsToggle.setAttribute("aria-expanded", "false");
    settingsMenu.setAttribute("aria-hidden", "true");
    settingsMenu.classList.remove("open");
  });
});

transparentBackgroundBox.addEventListener("change", () => {
  document.getElementById("paperSetting").style.display = transparentBackgroundBox.checked ? "none" : "block";
});

const map = L.map("map").setView([46.0, 7.7], 9);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);
// map.getContainer().style.width = workspaceMain.offsetWidth + "px";
let searchMarker;
searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;
  if (searchStatus) searchStatus.textContent = "Searching...";
  try {
    const params = new URLSearchParams({ q: query, format: "jsonv2", limit: "5" });
    const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`);
    if (!response.ok) throw new Error("Search failed.");
    const results = await response.json();
    if (!results.length) throw new Error("No places found.");
    const result = results[0];
    const point = [Number(result.lat), Number(result.lon)];
    map.setView(point, Math.max(map.getZoom(), 12));
    if (searchMarker) searchMarker.remove();
    searchMarker = L.marker(point).addTo(map).bindPopup(result.display_name).openPopup();
    if (searchStatus) searchStatus.textContent = result.display_name;
  } catch (error) {
    console.error("Place search failed:", error);
  }
});

tryAgain.addEventListener("click", () => {
  download.classList.add("hidden");
  tryAgain.classList.add("hidden");
  resultLoading.classList.add("hidden");
  drawToggle.classList.remove("hidden");
  button.classList.remove("hidden");
  currStatus.className = "status";
  resultContainer.style.display = "none";
  resultContainer.style.removeProperty("aspect-ratio");
  resultContainer.style.removeProperty("width");
  mapContainer.style.removeProperty("display");
  form.style.display = "block";
  requestAnimationFrame(() => {
    map.invalidateSize();
    requestAnimationFrame(() => map.invalidateSize());
  });
});

let selection;
let start;
let drawing = false;
drawToggle.addEventListener("click", () => {
  drawing = !drawing;
  map.dragging[drawing ? "disable" : "enable"]();
  drawToggle.textContent = drawing ? "Cancel drawing" : "Draw bounding box";
  map.getContainer().classList.toggle("drawing", drawing);
});
map.getContainer().addEventListener("pointerdown", (event) => {
  if (!drawing) return;
  event.preventDefault();
  start = map.mouseEventToLatLng(event);
  if (selection) map.removeLayer(selection);
  selection = L.rectangle([start, start], { color: "#000", weight: 1, fill: false }).addTo(map);
  map.getContainer().setPointerCapture(event.pointerId);
}, { passive: false });
map.getContainer().addEventListener("pointermove", (event) => {
  if (!drawing || !start || !selection) return;
  event.preventDefault();
  selection.setBounds(L.latLngBounds(start, map.mouseEventToLatLng(event)));
}, { passive: false });
map.getContainer().addEventListener("pointerup", (event) => {
  if (!drawing || !start || !selection) return;
  const bounds = selection.getBounds();
  start = null;
  if (bounds.getWest() === bounds.getEast() || bounds.getSouth() === bounds.getNorth()) return;
  const coordinateInputs = ["west", "south", "east", "north"].map((name) =>
    document.querySelector(`#map-form input[name="${name}"]`),
  );
  if (coordinateInputs.some((input) => !input)) {
    console.error("Map coordinate inputs are missing from #map-form.");
    return;
  }
  [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].forEach(
    (value, index) => {
      coordinateInputs[index].value = value.toFixed(5);
    },
  );
  drawing = false;
  map.dragging.enable();
  drawToggle.textContent = "Draw bounding box";
  map.getContainer().classList.remove("drawing");
});
map.getContainer().addEventListener("pointercancel", () => {
  start = null;
  if (selection) {
    map.removeLayer(selection);
    selection = null;
  }
});



form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  data.mode = selectedMode;
  if (data.transparentBackground) data.background = "none";
  delete data.transparentBackground;
  for (const key of ["west", "south", "east", "north", "interval", "lineWidth", "longSide"]) data[key] = Number(data[key]);
  data.showWater = Boolean(data.showWater);
  setInterfaceBusy(true);
  button.disabled = true;
  button.innerHTML = '<span class="globe-loader" role="status" aria-label="Loading"></span>';
  currStatus.className = "status busy";
  download.classList.add("hidden");
  try {
    const response = await fetch(apiUrl("/api/render"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Rendering failed.");
    const image = new Image();
    image.alt = "Generated topographic contour map";
    const resultUrl = result.url.startsWith("http") ? result.url : apiUrl(result.url);
    image.src = `${resultUrl}?t=${Date.now()}`;
    resultLoading.classList.remove("hidden");
    image.onload = () => resultLoading.classList.add("hidden");
    image.onerror = () => {
      resultLoading.classList.add("hidden");
      currStatus.textContent = "Render failed: the generated image could not be displayed.";
      currStatus.className = "status error";
    };

    // clear map container before adding the new image
    mapContainer.style.display = "none";
    drawToggle.classList.add("hidden");
    button.classList.add("hidden");
    tryAgain.classList.remove("hidden");
    resultContainer.innerHTML = "";
    resultContainer.style.display = "flex";
    resultContainer.style.aspectRatio = `${result.shape[1]} / ${result.shape[0]}`;
    resultContainer.style.width = "100%";
    resultContainer.appendChild(image);
    download.href = resultUrl;
    download.download = `topographic-contours.${data.format}`;
    download.textContent = `Download ${data.format.toUpperCase()}`;
    currStatus.textContent = "";
    currStatus.className = "status success";
    download.classList.remove("hidden");
    form.style.display = "none";
  } catch (error) {
    console.error("Map rendering failed:", error);
    currStatus.textContent = `Render failed: ${error.message}`;
    currStatus.className = "status error";
    mapContainer.style.display = "flex";
    resultContainer.style.display = "none";
    form.style.display = "block";
    drawToggle.classList.remove("hidden");
    button.classList.remove("hidden");
    tryAgain.classList.remove("hidden");
    download.classList.add("hidden");
  } finally {
    setInterfaceBusy(false);
    button.disabled = false;
    button.textContent = "Render";
  }
});
