// ICOS Station Maps: Europe front page, country map panels and station tables.
// Reads manifest.json, tables.json, countries.geojson and stations.geojson written by `icos-maps`.
"use strict";

const COLORS = { atmosphere: "var(--atmosphere)", ecosystem: "var(--ecosystem)", ocean: "var(--ocean)" };
const THEME_NAMES = { atmosphere: "Atmosphere", ecosystem: "Ecosystem", ocean: "Ocean" };
const PANEL_KIND = { home: "Home territory", remote: "Remote stations", ocean: "Ocean" };
// Every map is shown at the width where its station markers are this many pixels across, so markers
// look the same on all panels (the renderer sizes them relative to each map; see manifest hotspots.r).
const MARKER_PX = 14;
// Station table columns. `filter`: text (substring), select (exact, options from the data), number or
// date (>x, <x, a-b, or substring). `allOnly`: only in the all-stations table on the front page.
const COLUMNS = [
  { key: "map_number", label: "Map no.", cls: "num", filter: "number" },
  { key: "name", label: "Station name", filter: "text" },
  { key: "country_name", label: "Country", filter: "select", allOnly: true },
  { key: "id", label: "Abbreviation", cls: "code", filter: "text" },
  { key: "theme", label: "Station type", filter: "select", format: (v) => THEME_NAMES[v] ?? v },
  { key: "site_type", wide: true, label: "Site type", filter: "text" },
  { key: "cls", label: "Class", filter: "select" },
  { key: "pi", wide: true, label: "PI", filter: "text" },
  { key: "host", wide: true, label: "Responsible institute", filter: "text" },
  { key: "lat", label: "Latitude", cls: "coord", filter: "number" },
  { key: "lon", label: "Longitude", cls: "coord", filter: "number" },
  { key: "elevation", label: "Elevation (m)", cls: "coord", filter: "number" },
  { key: "climate", wide: true, label: "Climate zone", filter: "text" },
  { key: "labeled", label: "Labelling date", cls: "date", filter: "date" },
  { key: "status", label: "Status", filter: "select" },
];

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { manifest: null, tables: null, countries: null, world: null, stations: null, view: "europe" };
const EUROPE_BOX = [-32, 27, 46, 82];  // lon/lat window of the Europe view; stations outside it are listed separately

async function load() {
  const get = (f) => fetch(f).then((r) => { if (!r.ok) throw new Error(f); return r.json(); });
  try {
    [state.manifest, state.tables, state.countries, state.world, state.stations] = await Promise.all(
      ["manifest.json", "tables.json", "countries.geojson", "world.geojson", "stations.geojson"].map(get));
  } catch (e) {
    $("#load-error").hidden = false;
    return;
  }
  // Settings for the detailed map (MapTiler key); the site works without them.
  state.config = await fetch("api/config").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  setupChrome();
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", debounce(drawMap, 150));
  route();
}

// Map files keep their names between builds (FR_b_remote.png can show another territory after a
// rebuild), and nginx lets browsers cache them; the build time in the URL makes each build's files new.
function versioned(href) {
  return `${href}?v=${encodeURIComponent(state.manifest.generated)}`;
}

function members() {
  return Object.entries(state.manifest.countries).sort((a, b) => a[1].name.localeCompare(b[1].name));
}

function setupChrome() {
  const m = state.manifest;
  $("#updated").textContent = `${m.n_stations} stations · updated ${m.generated.slice(0, 10)}`;
  const select = $("#country-select");
  for (const [cc, c] of members()) select.add(new Option(c.name, cc));
  select.addEventListener("change", () => { location.hash = select.value ? `#/${select.value}` : "#/"; });

  const totals = { atmosphere: 0, ecosystem: 0, ocean: 0 };
  for (const [, c] of members()) for (const t in totals) totals[t] += c.by_theme?.[t] ?? 0;
  $("#europe-tiles").innerHTML =
    `<div class="tile"><div class="num">${m.n_stations}</div><div class="lbl">Stations in ${members().length} countries</div></div>` +
    Object.entries(totals).map(([t, n]) =>
      `<div class="tile"><div class="num">${n}</div><div class="lbl"><i style="background:${COLORS[t]}"></i>${THEME_NAMES[t]}</div></div>`).join("");

  $("#country-list").innerHTML = members().map(([cc, c]) =>
    `<li><a href="#/${cc}" data-cc="${cc}"><span>${esc(c.name)}</span><span class="n">${c.stations}</span></a></li>`).join("");
  $("#country-list").addEventListener("mouseover", (e) => highlight(e.target.closest("a")?.dataset.cc));
  $("#country-list").addEventListener("mouseout", () => highlight(null));

  renderOutside();

  if (m.overview) {
    $("#overview-dl").innerHTML = "Network overview map:" +
      Object.entries(m.overview).map(([f, href]) => `<a href="${esc(versioned(href))}" download>${f.toUpperCase()}</a>`).join("");
  }

  $("#figures").addEventListener("click", (e) => {
    const spot = e.target.closest(".hotspot");
    if (spot) { e.stopPropagation(); spot === state.popupFor ? closePopup() : openPopup(spot); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".station-popup")) closePopup(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { const b = state.popupFor; closePopup(); b?.focus(); } });
  window.addEventListener("hashchange", closePopup);

  $("#mode-figures").addEventListener("click", () => setMode("figures"));
  $("#mode-detailed").addEventListener("click", () => setMode("detailed"));

  state.countryTable = new StationTable($("#country-stations-table"), { allStations: false });
  state.allTable = new StationTable($("#all-stations-table"), { allStations: true });
  state.allTable.setRows(members().flatMap(([cc, c]) => (state.tables[cc] || []).map((r) => ({ ...r, country_name: c.name, member: cc }))),
    "icos_stations.csv");
}

/* ---------- Routing ---------- */

// Deep links: #/FR (last used map type), #/FR/maps (figures), #/FR/stations, #/FR/detailed, and
// #/FR/detailed@lat,lon,zoomz for a detailed-map view; the view part follows panning and zooming.
const ROUTE = /^#\/([A-Z]{2})?(?:\/(maps|stations|detailed))?(?:@(-?[\d.]+),(-?[\d.]+),([\d.]+)z)?/;

function route() {
  const [, cc, part, lat, lon, zoom] = location.hash.match(ROUTE) || [];
  const country = cc && state.manifest.countries[cc] ? cc : null;
  if (part === "detailed" || part === "maps") rememberMode(part === "detailed" ? "detailed" : "figures");
  state.linkView = lat ? { center: [+lon, +lat], zoom: +zoom } : null;
  const tab = part === "stations" ? "stations" : part ? "maps" : null;
  const allStations = !country && location.hash === "#/stations";
  $("#country-select").value = country || "";
  $("#front-tabs").hidden = !!country;
  $("#view-europe").hidden = !!country || allStations;
  $("#view-stations").hidden = !allStations;
  $("#view-country").hidden = !country;
  $("#front-tab-map").setAttribute("aria-selected", String(!country && !allStations));
  $("#front-tab-stations").setAttribute("aria-selected", String(allStations));
  if (country) {
    showCountry(country, tab || "maps");
  } else if (allStations) {
    destroyDetailed();
    document.title = "All stations · ICOS Station Maps";
  } else {
    destroyDetailed();
    state.view = location.hash === "#/world" ? "world" : "europe";
    $("#front-tab-map").href = state.view === "world" ? "#/world" : "#/";
    document.title = state.view === "world" ? "World · ICOS Station Maps" : "ICOS Station Maps";
    for (const v of ["europe", "world"]) $(`#toggle-${v}`).setAttribute("aria-selected", String(v === state.view));
    drawMap();
  }
  window.scrollTo({ top: 0 });
}

/* ---------- Front-page map (Europe or world) ---------- */

function stationsIn(code) {
  return state.stations.features.filter((f) => f.properties.country === code);
}

function drawMap() {
  if ($("#view-europe").hidden) return;
  const world = state.view === "world";
  const svg = d3.select("#europe-map");
  const width = svg.node().clientWidth || 900;
  const height = Math.round(width * (world ? 0.5 : 0.82));
  svg.attr("viewBox", `0 0 ${width} ${height}`).selectAll("*").remove();
  svg.attr("aria-label", world ? "World map with all ICOS stations" : "Map of Europe with the ICOS member countries highlighted");

  const outlines = world ? state.world : state.countries;
  const projection = world
    ? d3.geoEqualEarth().rotate([-10, 0]).fitExtent([[8, 8], [width - 8, height - 8]], outlines)
    : d3.geoAzimuthalEqualArea().rotate([-10, -52]).fitExtent([[16, 16], [width - 16, height - 16]],
      { type: "FeatureCollection", features: outlines.features.filter((f) => f.properties.member) });
  const path = d3.geoPath(projection);
  const tooltip = $("#tooltip");

  if (world) svg.append("path").attr("class", "sphere").attr("d", path({ type: "Sphere" }));
  // A shape covering more than half the globe has the wrong winding; d3 would paint it over everything.
  const features = outlines.features.filter((f) => d3.geoArea(f) < 2 * Math.PI);
  svg.append("g").selectAll("path").data(features).join("path")
    .attr("d", path)
    .attr("class", (f) => `country${f.properties.member ? " member" : ""}`)
    .attr("data-cc", (f) => f.properties.member || null)
    .attr("tabindex", (f) => (f.properties.member ? 0 : null))
    .attr("role", (f) => (f.properties.member ? "link" : null))
    .attr("aria-label", (f) => (f.properties.member ? `${state.manifest.countries[f.properties.member]?.name ?? f.properties.NAME_ENGL}, show maps` : null))
    .on("click", (e, f) => { if (f.properties.member) location.hash = `#/${f.properties.member}`; })
    .on("keydown", (e, f) => { if (f.properties.member && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); location.hash = `#/${f.properties.member}`; } })
    .on("mousemove", (e, f) => {
      const [x, y] = d3.pointer(e, svg.node().parentNode);
      const c = state.manifest.countries[f.properties.member];
      const hosted = c ? [] : stationsIn(f.properties.CNTR_ID);
      tooltip.innerHTML = c
        ? `<b>${esc(c.name)}</b><br>${c.stations} stations · ${Object.entries(c.by_theme || {}).filter(([, n]) => n).map(([t, n]) => `${n} ${t}`).join(", ")}`
        : `<b>${esc(f.properties.NAME_ENGL)}</b><br><span style="opacity:.7">Not an ICOS member</span>` +
          hosted.map((s) => `<br>${esc(s.properties.name)} (${esc(s.properties.theme)}, ${esc(s.properties.status.toLowerCase())}` +
            (state.manifest.countries[s.properties.member] ? `, run by ${esc(state.manifest.countries[s.properties.member].name)}` : "") + ")").join("");
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
      tooltip.hidden = false;
      highlight(f.properties.member || null);
    })
    .on("mouseleave", () => { tooltip.hidden = true; highlight(null); });

  const lines = state.stations.features.filter((f) => f.geometry.type !== "Point");
  const points = state.stations.features.filter((f) => f.geometry.type === "Point");
  svg.append("g").selectAll("path").data(lines).join("path").attr("class", "soop").attr("d", path);
  svg.append("g").selectAll("circle").data(points).join("circle")
    .attr("class", "station")
    .attr("r", world ? Math.max(2, width / 300) : Math.max(2, width / 380))
    .attr("fill", (f) => COLORS[f.properties.theme])
    .attr("transform", (f) => `translate(${projection(f.geometry.coordinates)})`)
    .attr("display", (f) => (projection(f.geometry.coordinates) ? null : "none"));
}

function outsideEurope(f) {
  const [lon, lat] = f.geometry.coordinates;
  return lon < EUROPE_BOX[0] || lat < EUROPE_BOX[1] || lon > EUROPE_BOX[2] || lat > EUROPE_BOX[3];
}

function renderOutside() {
  const names = Object.fromEntries(state.world.features.map((f) => [f.properties.CNTR_ID, f.properties.NAME_ENGL]));
  const far = state.stations.features.filter((f) => f.geometry.type === "Point" && outsideEurope(f))
    .sort((a, b) => a.properties.name.localeCompare(b.properties.name));
  $("#outside-list").innerHTML = far.map((f) => {
    const p = f.properties;
    const site = names[p.country], operator = state.manifest.countries[p.member]?.name;
    const where = operator && site && site !== operator ? `${site} · ${operator}` : operator ?? site ?? p.country;
    const label = `<span><i style="background:${COLORS[p.theme]}"></i>${esc(p.name)}</span><span class="n">${esc(where)}</span>`;
    return `<li>${p.member ? `<a href="#/${p.member}" data-cc="${p.member}">${label}</a>` : `<span class="row">${label}</span>`}</li>`;
  }).join("");
}

function highlight(cc) {
  document.querySelectorAll("#europe-map .member, #country-list a, #outside-list a").forEach((el) =>
    el.classList.toggle("hover", !!cc && el.dataset.cc === cc));
}

/* ---------- Country view ---------- */

function showCountry(cc, tab) {
  const c = state.manifest.countries[cc];
  document.title = `${c.name} · ICOS Station Maps`;
  $("#crumb-country").textContent = c.name;
  $("#country-name").textContent = c.name;
  $("#country-chips").innerHTML = `<span class="chip">${c.stations} stations</span>` +
    Object.entries(c.by_theme || {}).filter(([, n]) => n).map(([t, n]) =>
      `<span class="chip"><i style="background:${COLORS[t]}"></i>${n} ${THEME_NAMES[t]}</span>`).join("") +
    (c.not_yet_labelled ? `<span class="chip">${c.not_yet_labelled} not yet labelled</span>` : "");

  for (const t of ["maps", "stations"]) {
    const el = $(`#tab-${t}`);
    el.href = t === "maps" ? mapsLink(cc) : `#/${cc}/stations`;
    el.setAttribute("aria-selected", String(t === tab));
    $(`#panel-${t}`).hidden = t !== tab;
  }

  const figs = $("#figures");
  figs.innerHTML = c.panels.map((p) => {
    const img = versioned(p.files.png || p.files.svg);
    const spots = (p.hotspots?.points || []).map((h) => {
      const row = stationRow(cc, h.id);
      return `<button class="hotspot" data-id="${esc(h.id)}" style="left:${h.x * 100}%;top:${h.y * 100}%;width:${p.hotspots.r * 200}%"
        aria-label="${esc(row?.name ?? h.id)}: station details"></button>`;
    }).join("");
    const width = p.hotspots?.r ? Math.round(MARKER_PX / (2 * p.hotspots.r)) : 600;
    return `<figure class="figure" style="width:${width}px">
      <div class="map-frame">
        <img src="${esc(img)}" alt="${esc(`${c.name}: ${p.title}. Map of ${p.stations.length} stations.`)}" loading="lazy">
        ${spots}
      </div>
      <figcaption>
        <span class="title"><b>Figure ${esc(p.key)}</b>${esc(p.kind === "home" ? PANEL_KIND.home : p.title)}</span>
        <span class="dl">${Object.entries(p.files).map(([f, href]) => `<a href="${esc(versioned(href))}" download>${f.toUpperCase()}</a>`).join("")}</span>
      </figcaption>
    </figure>`;
  }).join("");

  state.cc = cc;
  $("#maps-toolbar").hidden = !hasDetailed();
  if (tab === "maps") applyMode();
  else destroyDetailed();
  const unmapped = c.unmapped || [];
  state.countryTable.setRows((state.tables[cc] || []).map((r) => ({ ...r, member: cc })), `${cc}_stations.csv`,
    unmapped.length ? `Not on the maps (no position or route data yet): ${unmapped.join(", ")}.` : "");
}

function stationRow(cc, id) {
  return (state.tables[cc] || []).find((r) => r.id === id);
}

function countryName(code) {
  return state.world.features.find((f) => f.properties.CNTR_ID === code)?.properties.NAME_ENGL;
}

// Stations standing outside the member country that runs them (e.g. Yangambi in DR Congo, run by Belgium).
function located(r) {
  const where = r.country && r.country !== state.cc ? countryName(r.country) : null;
  return where ? `<dt>Located in</dt><dd>${esc(where)}</dd>` : "";
}

function stationPopup(r, closable = true) {
  const field = (label, value) => `<dt>${label}</dt><dd>${value ? esc(value) : '<span class="muted">–</span>'}</dd>`;
  return `${closable ? '<button class="popup-close" aria-label="Close">×</button>' : ""}
    <h3>${esc(r.name)}</h3>
    <p class="popup-sub"><span class="code">${esc(r.id)}</span><span class="type"><i style="background:${COLORS[r.theme]}"></i>${THEME_NAMES[r.theme]}</span></p>
    <dl>
      ${located(r)}
      ${field("Class", r.cls)}
      ${field("Labelled", r.labeled || r.status)}
      ${field("PI", r.pi)}
      ${field("Responsible institute", r.host)}
    </dl>
    ${r.link ? `<a class="popup-link" href="${esc(r.link)}" target="_blank" rel="noopener">Station page ↗</a>`
             : '<p class="muted popup-note">No station page yet: the station is in the labelling process.</p>'}`;
}

function openPopup(button) {
  closePopup();
  const r = stationRow(state.cc, button.dataset.id);
  if (!r) return;
  const frame = button.closest(".map-frame");
  const pop = document.createElement("div");
  pop.className = "station-popup";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", `${r.name} details`);
  pop.innerHTML = stationPopup(r);
  frame.appendChild(pop);
  // Open beside the marker, flipped when it would run off the map.
  const x = parseFloat(button.style.left), y = parseFloat(button.style.top);
  pop.style.left = x > 55 ? "" : `calc(${x}% + 14px)`;
  pop.style.right = x > 55 ? `calc(${100 - x}% + 14px)` : "";
  pop.style.top = `clamp(8px, calc(${y}% - 40px), calc(100% - ${pop.offsetHeight + 8}px))`;
  button.classList.add("active");
  pop.querySelector(".popup-close").addEventListener("click", closePopup);
  state.popupFor = button;
}

function closePopup() {
  document.querySelector(".station-popup")?.remove();
  state.popupFor?.classList.remove("active");
  state.popupFor = null;
}

/* ---------- Detailed map: MapTiler in Web Mercator, insets fixed while the main map pans/zooms ---------- */

const MODE_KEY = "icosmaps.mapMode";

function getMode() {
  try { return localStorage.getItem(MODE_KEY) || "figures"; } catch { return "figures"; }
}

function rememberMode(mode) {
  try { localStorage.setItem(MODE_KEY, mode); } catch { /* per-viewer convenience only */ }
}

function mapsLink(cc) {
  return `#/${cc}/${getMode() === "detailed" && hasDetailed() ? "detailed" : "maps"}`;
}

// Update the address without a history entry or a hashchange (which would redraw the page).
function setLink(hash) {
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

function setMode(mode) {
  rememberMode(mode);
  state.linkView = null;
  setLink(mapsLink(state.cc));
  $("#tab-maps").href = mapsLink(state.cc);
  applyMode();
}

function hasDetailed() {
  return !!(state.config?.maptiler_key && window.maplibregl);
}

function applyMode() {
  const detailed = getMode() === "detailed" && hasDetailed();
  $("#mode-figures").setAttribute("aria-pressed", String(!detailed));
  $("#mode-detailed").setAttribute("aria-pressed", String(detailed));
  $("#figures").hidden = detailed;
  $("#detail-wrap").hidden = !detailed;
  $("#detail-home").hidden = !detailed;
  if (detailed) renderDetailed(state.cc);
  else destroyDetailed();
}

function styleUrl() {
  return `https://api.maptiler.com/maps/${encodeURIComponent(state.config.maptiler_style)}/style.json?key=${encodeURIComponent(state.config.maptiler_key)}`;
}

function destroyDetailed() {
  (state.dmaps || []).forEach((m) => m.remove());
  state.dmaps = [];
  $("#insets").innerHTML = "";
}

const lngLatBounds = (b) => [[b[0], b[1]], [b[2], b[3]]];

// National topographic maps shown on top of MapTiler when zoomed in, per country. The Dutch TOPraster
// WMS (Kadaster/PDOK, CC0) has one layer per scale and draws each only within its scale range. Bands are
// map zoom levels, measured against the service: with 256 px images MapLibre requests tiles one zoom
// level deeper than the map zoom, so map zoom 12 asks for z13 tiles, which TOP50raster draws.
const PDOK_TOPRASTER = "https://service.pdok.nl/brt/topraster/wms/v1_0?service=WMS&request=GetMap&version=1.3.0" +
  "&styles=&crs=EPSG:3857&bbox={bbox-epsg-3857}&width=256&height=256&format=image/png&transparent=true&layers=";
const DETAIL_OVERLAYS = {
  NL: {
    bounds: [3.2, 50.7, 7.3, 53.7],
    attribution: '<a href="https://www.pdok.nl/" target="_blank" rel="noopener">© Kadaster / PDOK TOPraster</a>',
    layers: [["top250raster", 8.5, 10.5], ["top100raster", 10.5, 11.5], ["top50raster", 11.5, 12.5], ["top25raster", 12.5, 20]],
  },
};

function addOverlays(map, cc) {
  const o = DETAIL_OVERLAYS[cc];
  if (!o) return;
  map.on("load", () => {
    const below = map.getLayer("soop") ? "soop" : undefined;  // keep routes (and HTML markers) on top
    for (const [name, minzoom, maxzoom] of o.layers) {
      map.addSource(`overlay-${name}`, { type: "raster", tiles: [PDOK_TOPRASTER + name], tileSize: 256,
        bounds: o.bounds, maxzoom: 16, attribution: o.attribution });  // TOP25raster is empty beyond z16
      map.addLayer({ id: `overlay-${name}`, type: "raster", source: `overlay-${name}`, minzoom, maxzoom }, below);
    }
  });
}

function renderDetailed(cc) {
  destroyDetailed();
  const c = state.manifest.countries[cc];
  const home = c.panels.find((p) => p.kind === "home") || c.panels[0];
  const view = state.linkView;  // a deep-linked view wins over the home territory
  const main = new maplibregl.Map({
    container: "detail-map", style: styleUrl(), attributionControl: { compact: true },
    ...(view ? { center: view.center, zoom: view.zoom } : { bounds: lngLatBounds(home.bounds), fitBoundsOptions: { padding: 30 } }),
  });
  main.on("moveend", () => {
    const c = main.getCenter();
    setLink(`#/${cc}/detailed@${c.lat.toFixed(4)},${c.lng.toFixed(4)},${main.getZoom().toFixed(2)}z`);
  });
  main.addControl(new maplibregl.NavigationControl(), "top-right");
  main.addControl(new maplibregl.FullscreenControl(), "top-right");
  main.addControl(new maplibregl.ScaleControl(), "bottom-right");
  state.dmaps = [main];
  addStations(main, cc, null, false);
  addOverlays(main, cc);
  $("#detail-home").onclick = () => main.fitBounds(lngLatBounds(home.bounds), { padding: 30 });

  // Remote and ocean panels become fixed insets, as on the print figures; a click flies the main map there.
  for (const p of c.panels.filter((p) => p !== home)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "inset";
    btn.setAttribute("aria-label", `Show figure ${p.key}, ${p.title}, on the map`);
    btn.innerHTML = `<div class="inset-map"></div><span class="inset-label"><b>${esc(p.key)}</b>${esc(p.kind === "ocean" ? "Ocean" : p.title.replace("Remote stations: ", ""))}</span>`;
    $("#insets").appendChild(btn);
    const m = new maplibregl.Map({
      container: btn.querySelector(".inset-map"), style: styleUrl(), bounds: lngLatBounds(p.bounds),
      fitBoundsOptions: { padding: 8 }, interactive: false, attributionControl: false,
    });
    addStations(m, cc, p.stations, true);
    btn.addEventListener("click", () => main.fitBounds(lngLatBounds(p.bounds), { padding: 30 }));
    state.dmaps.push(m);
  }
}

function addStations(map, cc, ids, small) {
  const feats = state.stations.features.filter((f) => f.properties.member === cc && (!ids || ids.includes(f.properties.id)));
  const lines = feats.filter((f) => f.geometry.type !== "Point");
  if (lines.length) {
    map.on("load", () => {
      map.addSource("soop", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
      map.addLayer({ id: "soop", type: "line", source: "soop",
        paint: { "line-color": "#0B3B7A", "line-width": small ? 1 : 1.6, "line-opacity": 0.8 } });
    });
  }
  for (const f of feats) {
    const r = stationRow(cc, f.properties.id);
    const el = document.createElement("div");
    el.className = `dm-marker ${f.properties.theme}${small ? " small" : ""}`;
    el.style.background = COLORS[f.properties.theme];
    el.textContent = r?.map_number ?? "";
    const marker = new maplibregl.Marker({ element: el }).setLngLat(anchorOf(f.geometry)).addTo(map);
    if (!small && r) {
      el.title = r.name;
      marker.setPopup(new maplibregl.Popup({ offset: 14, maxWidth: "320px" }).setHTML(stationPopup(r, false)));
    }
  }
}

// Where to put a SOOP line's number marker: the middle of its longest part.
function anchorOf(g) {
  if (g.type === "Point") return g.coordinates;
  const parts = g.type === "LineString" ? [g.coordinates] : g.coordinates;
  const longest = parts.reduce((a, b) => (b.length > a.length ? b : a));
  return longest[Math.floor(longest.length / 2)];
}

/* ---------- Station table (country pages and the front page's Stations tab) ---------- */

const NA = "NA";  // not applicable, e.g. coordinates of a ship line

// Filter expression for number and date columns: ">x", ">=x", "<x", "<=x", "a-b", else a substring.
function matches(value, expr, kind) {
  const v = value ?? "";
  if (kind === "number" || kind === "date") {
    const num = (x) => (kind === "number" ? parseFloat(x) : String(x));
    const cmp = expr.match(/^(>=|<=|>|<)\s*(.+)$/);
    const range = expr.match(kind === "number" ? /^(-?[\d.]+)\s*-\s*(-?[\d.]+)$/ : /^(\d{4}[\d-]*)\s*-\s*(\d{4}[\d-]*)$/);
    if (cmp || range) {
      if (v === "" || v === NA || (kind === "number" && Number.isNaN(parseFloat(v)))) return false;
      const x = num(v);
      if (range) return x >= num(range[1]) && x <= num(range[2]) + (kind === "date" ? "\uffff" : 0);
      const y = num(cmp[2].trim());
      return { ">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y }[cmp[1]];
    }
  }
  return String(v).toLowerCase().includes(expr.toLowerCase());
}

class StationTable {
  constructor(host, { allStations }) {
    this.host = host;
    this.columns = COLUMNS.filter((c) => allStations || !c.allOnly);
    this.sort = { key: allStations ? "country_name" : "map_number", dir: 1 };
    this.filters = {};
    this.rows = [];
    host.innerHTML = `
      <div class="toolbar">
        <input type="search" class="table-search" placeholder="Search all columns…" aria-label="Search all columns">
        <span class="count"></span>
        <button type="button" class="ghost clear-filters">Clear filters</button>
        <span class="downloads" role="group" aria-label="Download the stations shown">
          <span class="dl-label">Download</span>
          <button type="button" class="button" data-format="csv">CSV</button>
          <button type="button" class="button" data-format="xlsx">XLSX</button>
          <button type="button" class="button" data-format="kml">KML</button>
        </span>
      </div>
      <div class="table-wrap"><table class="station-table"><thead></thead><tbody></tbody></table></div>
      <p class="note table-note"></p>
      <p class="note">* Climate zone read from the Köppen-Geiger 1 km map for 1991–2020 (Beck et al. 2023) at the station position;
        the others come from the Carbon Portal. NA: not applicable (ship lines have no single position).</p>`;
    this.$ = (sel) => host.querySelector(sel);
    this.$(".table-search").addEventListener("input", (e) => { this.search = e.target.value.trim(); this.renderBody(); });
    this.$(".clear-filters").addEventListener("click", () => {
      this.filters = {};
      this.search = "";
      this.$(".table-search").value = "";
      this.renderHead();
      this.renderBody();
    });
    this.$("thead").addEventListener("click", (e) => {
      const key = e.target.closest("th[data-key]")?.dataset.key;
      if (!key || e.target.closest(".filter-row")) return;
      this.sort = { key, dir: this.sort.key === key ? -this.sort.dir : 1 };
      this.renderHead();
      this.renderBody();
    });
    this.$("thead").addEventListener("input", (e) => {
      const key = e.target.dataset.filter;
      if (!key) return;
      this.filters[key] = e.target.value.trim();
      this.renderBody();
    });
    this.$(".downloads").addEventListener("click", (e) => {
      const format = e.target.closest("[data-format]")?.dataset.format;
      if (format) this.download(format);
    });
  }

  setRows(rows, csvName, note = "") {
    this.rows = rows;
    this.fileBase = csvName.replace(/\.csv$/, "");
    this.filters = {};
    this.search = "";
    this.$(".table-search").value = "";
    this.$(".table-note").textContent = note;
    this.$(".table-note").hidden = !note;
    this.renderHead();
    this.renderBody();
  }

  renderHead() {
    const { key, dir } = this.sort;
    const head = this.columns.map((c) =>
      `<th scope="col" data-key="${c.key}"${c.wide ? ' class="wide"' : ""}${c.key === key ? ` aria-sort="${dir > 0 ? "ascending" : "descending"}"` : ""}>${c.label}</th>`).join("");
    const filters = this.columns.map((c) => {
      const value = this.filters[c.key] ?? "";
      const label = `Filter ${c.label}`;
      if (c.filter === "select") {
        const options = [...new Set(this.rows.map((r) => r[c.key]).filter((v) => v != null && v !== ""))].sort();
        return `<th><select data-filter="${c.key}" aria-label="${label}"><option value="">All</option>${options.map((o) =>
          `<option value="${esc(o)}"${o === value ? " selected" : ""}>${esc(c.format ? c.format(o) : o)}</option>`).join("")}</select></th>`;
      }
      const hint = c.filter === "number" ? ">500" : c.filter === "date" ? ">2022" : "Filter";
      return `<th><input type="search" data-filter="${c.key}" value="${esc(value)}" placeholder="${hint}" aria-label="${label}"></th>`;
    }).join("");
    this.$("thead").innerHTML = `<tr>${head}</tr><tr class="filter-row">${filters}</tr>`;
  }

  visibleRows() {
    const q = (this.search || "").toLowerCase();
    const shown = this.rows.filter((r) =>
      this.columns.every((c) => {
        const f = this.filters[c.key];
        if (!f) return true;
        return c.filter === "select" ? String(r[c.key]) === f : matches(r[c.key], f, c.filter);
      }) &&
      (!q || this.columns.some((c) => String((c.format ? c.format(r[c.key]) : r[c.key]) ?? "").toLowerCase().includes(q))));
    const { key, dir } = this.sort;
    const blank = (x) => x == null || x === "" || x === NA;
    return shown.sort((a, b) => {
      const x = a[key], y = b[key];
      if (blank(x)) return blank(y) ? 0 : 1;
      if (blank(y)) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
    });
  }

  cell(c, r) {
    const v = r[c.key];
    const empty = '<span class="muted">–</span>';
    switch (c.key) {
      case "map_number":
        return `<td class="num">${v == null ? empty : `<span class="badge ${r.theme}" style="background:${COLORS[r.theme]}">${v}</span>`}</td>`;
      case "name":
        return r.link ? `<td><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(v)}</a></td>` : `<td>${esc(v)}</td>`;
      case "country_name":
        return `<td><a href="#/${esc(r.member)}/stations">${esc(v)}</a></td>`;
      case "status":
        return `<td><span class="status ${v === "Labelled" ? "ok" : "pending"}">${esc(v)}</span></td>`;
      case "theme":
        return `<td class="type"><i style="background:${COLORS[v]}"></i>${THEME_NAMES[v]}</td>`;
      case "climate":
        if (v === NA) return `<td class="muted">${NA}</td>`;
        return `<td>${v ? esc(v) + (r.climate_source === "map" ? '<span class="derived" title="From the Köppen-Geiger 1 km map (Beck et al. 2023)">*</span>' : "") : empty}</td>`;
      default:
        if (v === NA) return `<td class="${c.cls || ""} muted">${NA}</td>`;
        return `<td class="${c.cls || ""}">${v != null && v !== "" ? esc(c.format ? c.format(v) : v) : empty}</td>`;
    }
  }

  renderBody() {
    const shown = this.visibleRows();
    this.$("tbody").innerHTML = shown.map((r) => `<tr>${this.columns.map((c) => this.cell(c, r)).join("")}</tr>`).join("") ||
      `<tr><td colspan="${this.columns.length}" class="muted empty">No stations match these filters.</td></tr>`;
    this.$(".count").textContent = `${shown.length} of ${this.rows.length} stations`;
    this.shown = shown;
  }

  // Downloads contain the rows currently shown (filters and sort applied).
  download(format) {
    const values = (r) => this.columns.map((c) => (c.format ? c.format(r[c.key]) : r[c.key]));
    const header = this.columns.map((c) => c.label);
    let blob;
    if (format === "csv") {
      const quote = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      const lines = [header, ...this.shown.map(values)].map((row) => row.map(quote).join(","));
      blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    } else if (format === "xlsx") {
      blob = xlsxBlob(header, this.shown.map(values), "Stations");
    } else {
      blob = kmlBlob(this.shown, this.columns, this.fileBase);
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${this.fileBase}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
}

/* ---------- XLSX and KML export (no libraries) ---------- */

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// A zip archive with stored (uncompressed) entries: enough for a valid .xlsx.
function zipBlob(files, type) {
  const enc = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;
  const u16 = (v) => [v & 0xff, (v >>> 8) & 0xff];
  const u32 = (v) => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
  for (const [name, text] of Object.entries(files)) {
    const nameBytes = enc.encode(name), data = enc.encode(text), crc = crc32(data);
    const common = [...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21), ...u32(crc), ...u32(data.length), ...u32(data.length), ...u16(nameBytes.length)];
    const local = new Uint8Array([...u32(0x04034b50), ...common, ...u16(0), ...nameBytes]);
    central.push(new Uint8Array([...u32(0x02014b50), ...u16(20), ...common, ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(offset), ...nameBytes]));
    parts.push(local, data);
    offset += local.length + data.length;
  }
  const size = central.reduce((n, c) => n + c.length, 0);
  const end = new Uint8Array([...u32(0x06054b50), ...u16(0), ...u16(0), ...u16(central.length), ...u16(central.length), ...u32(size), ...u32(offset), ...u16(0)]);
  return new Blob([...parts, ...central, end], { type });
}

const xmlEsc = (v) => String(v ?? "").replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" }[c]))
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");

function xlsxBlob(header, rows, sheetName) {
  const col = (i) => (i >= 26 ? String.fromCharCode(64 + Math.floor(i / 26)) : "") + String.fromCharCode(65 + (i % 26));
  const cell = (v, r, c) => {
    const ref = `${col(c)}${r}`;
    if (typeof v === "number" && Number.isFinite(v)) return `<c r="${ref}"><v>${v}</v></c>`;
    if (v == null || v === "") return "";
    return `<c r="${ref}" t="inlineStr"${r === 1 ? ' s="1"' : ""}><is><t xml:space="preserve">${xmlEsc(v)}</t></is></c>`;
  };
  const sheetRows = [header, ...rows].map((row, i) => `<row r="${i + 1}">${row.map((v, c) => cell(v, i + 1, c)).join("")}</row>`).join("");
  const last = `${col(header.length - 1)}${rows.length + 1}`;
  const widths = header.map((h, c) => Math.min(48, Math.max(h.length, ...rows.map((r) => String(r[c] ?? "").length)) + 2));
  return zipBlob({
    "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
    "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
    "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${xmlEsc(sheetName)}" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
    "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf xfId="0" fontId="1" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    "xl/worksheets/sheet1.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("")}</cols><sheetData>${sheetRows}</sheetData><autoFilter ref="A1:${last}"/></worksheet>`,
  }, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
}

// KML colours are aabbggrr.
const KML_COLORS = { atmosphere: "ff7d00e5", ecosystem: "ff0bcaaf", ocean: "ffc8a600" };

function kmlBlob(rows, columns, title) {
  const geometry = Object.fromEntries(state.stations.features.map((f) => [`${f.properties.member}|${f.properties.id}`, f.geometry]));
  const coords = (pts) => pts.map(([x, y]) => `${x},${y}`).join(" ");
  const styles = Object.entries(KML_COLORS).map(([t, c]) => `<Style id="${t}"><IconStyle><color>${c}</color><scale>0.9</scale>` +
    `<Icon><href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>` +
    `<LineStyle><color>ff7a3b0b</color><width>2</width></LineStyle></Style>`).join("");
  const placemarks = rows.map((r) => {
    const g = geometry[`${r.member}|${r.id}`];
    if (!g) return "";
    const shape = g.type === "Point" ? `<Point><coordinates>${coords([g.coordinates])}</coordinates></Point>`
      : g.type === "LineString" ? `<LineString><tessellate>1</tessellate><coordinates>${coords(g.coordinates)}</coordinates></LineString>`
      : `<MultiGeometry>${g.coordinates.map((l) => `<LineString><tessellate>1</tessellate><coordinates>${coords(l)}</coordinates></LineString>`).join("")}</MultiGeometry>`;
    const data = columns.map((c) => `<Data name="${xmlEsc(c.label)}"><value>${xmlEsc(c.format ? c.format(r[c.key]) : r[c.key])}</value></Data>`).join("");
    const link = r.link ? `<atom:link href="${xmlEsc(r.link)}"/>` : "";
    return `<Placemark><name>${xmlEsc(r.name)}</name>${link}<styleUrl>#${r.theme}</styleUrl><ExtendedData>${data}</ExtendedData>${shape}</Placemark>`;
  }).join("");
  const kml = `<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">` +
    `<Document><name>${xmlEsc(title)}</name><description>ICOS stations, ${xmlEsc(state.manifest.generated)}</description>${styles}${placemarks}</Document></kml>`;
  return new Blob([kml], { type: "application/vnd.google-earth.kml+xml" });
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

load();
