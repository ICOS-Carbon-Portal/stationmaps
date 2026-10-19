// ICOS Station Maps: Europe front page, country map panels and station tables.
// Reads manifest.json, tables.json, countries.geojson and stations.geojson written by `icos-maps`.
"use strict";

const COLORS = { atmosphere: "var(--atmosphere)", ecosystem: "var(--ecosystem)", ocean: "var(--ocean)" };
const THEME_NAMES = { atmosphere: "Atmosphere", ecosystem: "Ecosystem", ocean: "Ocean" };
const PANEL_KIND = { home: "Home territory", remote: "Remote stations", ocean: "Ocean" };
const COLUMNS = [
  { key: "map_number", label: "Map no.", cls: "num" },
  { key: "name", label: "Station name" },
  { key: "id", label: "Abbreviation", cls: "code" },
  { key: "theme", label: "Station type" },
  { key: "site_type", label: "Site type" },
  { key: "cls", label: "Class" },
  { key: "host", label: "Host institute" },
  { key: "labeled", label: "Labelling date", cls: "date" },
  { key: "status", label: "Status" },
];

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { manifest: null, tables: null, countries: null, world: null, stations: null, view: "europe", sort: { key: "map_number", dir: 1 } };
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
  setupChrome();
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", debounce(drawMap, 150));
  route();
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
      Object.entries(m.overview).map(([f, href]) => `<a href="${esc(href)}" download>${f.toUpperCase()}</a>`).join("");
  }

  $("#station-filter").addEventListener("input", renderTable);
  $("#domain-filter").addEventListener("change", renderTable);
  $("#status-filter").addEventListener("change", renderTable);
  $("#station-table thead").addEventListener("click", (e) => {
    const key = e.target.closest("th")?.dataset.key;
    if (!key) return;
    state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : 1 };
    renderTable();
  });
}

/* ---------- Routing ---------- */

function route() {
  const [, cc, tab] = location.hash.match(/^#\/([A-Z]{2})?\/?(maps|stations)?/) || [];
  const country = cc && state.manifest.countries[cc] ? cc : null;
  $("#country-select").value = country || "";
  $("#view-europe").hidden = !!country;
  $("#view-country").hidden = !country;
  if (country) {
    showCountry(country, tab || "maps");
  } else {
    state.view = location.hash === "#/world" ? "world" : "europe";
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
          hosted.map((s) => `<br>${esc(s.properties.name)} (${esc(s.properties.theme)}, ${esc(s.properties.status.toLowerCase())})`).join("");
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
    const where = state.manifest.countries[p.member]?.name ?? names[p.country] ?? p.country;
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
    el.href = `#/${cc}/${t}`;
    el.setAttribute("aria-selected", String(t === tab));
    $(`#panel-${t}`).hidden = t !== tab;
  }

  const figs = $("#figures");
  figs.classList.toggle("single", c.panels.length === 1);
  figs.innerHTML = c.panels.map((p, i) => {
    const img = p.files.png || p.files.svg;
    const open = p.files.svg || img;
    return `<figure class="figure${i === 0 && c.panels.length > 1 ? " lead" : ""}">
      <a class="img" href="${esc(open)}" target="_blank" rel="noopener" title="Open full-size map">
        <img src="${esc(img)}" alt="${esc(`${c.name}: ${p.title}. Map of ${p.stations.length} stations.`)}" loading="lazy">
      </a>
      <figcaption>
        <span class="title"><b>Figure ${esc(p.key)}</b>${esc(p.kind === "home" ? PANEL_KIND.home : p.title)}</span>
        <span class="dl">${Object.entries(p.files).map(([f, href]) => `<a href="${esc(href)}" download>${f.toUpperCase()}</a>`).join("")}</span>
      </figcaption>
    </figure>`;
  }).join("");

  state.cc = cc;
  $("#csv-link").href = `maps/${cc}/${cc}_stations.csv`;
  const unmapped = c.unmapped || [];
  $("#unmapped-note").hidden = !unmapped.length;
  $("#unmapped-note").textContent = unmapped.length
    ? `Not on the maps (no position or route data yet): ${unmapped.join(", ")}.` : "";
  renderTable();
}

function renderTable() {
  const rows = (state.tables[state.cc] || []).slice();
  const q = $("#station-filter").value.trim().toLowerCase();
  const domain = $("#domain-filter").value;
  const status = $("#status-filter").value;
  const shown = rows.filter((r) => (!domain || r.theme === domain) && (!status || r.status === status) &&
    (!q || COLUMNS.some((col) => String(r[col.key] ?? "").toLowerCase().includes(q))));

  const { key, dir } = state.sort;
  shown.sort((a, b) => {
    const x = a[key], y = b[key];
    if (x == null || x === "") return 1;
    if (y == null || y === "") return -1;
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });

  $("#station-table thead").innerHTML = "<tr>" + COLUMNS.map((col) =>
    `<th scope="col" data-key="${col.key}"${col.key === key ? ` aria-sort="${dir > 0 ? "ascending" : "descending"}"` : ""}>${col.label}</th>`).join("") + "</tr>";
  $("#station-table tbody").innerHTML = shown.map((r) => "<tr>" + COLUMNS.map((col) => {
    const v = r[col.key];
    if (col.key === "map_number") {
      return `<td class="num">${v == null ? '<span class="muted">–</span>' : `<span class="badge ${r.theme}" style="background:${COLORS[r.theme]}">${v}</span>`}</td>`;
    }
    if (col.key === "name") return r.link ? `<td><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(v)}</a></td>` : `<td>${esc(v)}</td>`;
    if (col.key === "status") return `<td><span class="status ${v === "Labelled" ? "ok" : "pending"}">${esc(v)}</span></td>`;
    if (col.key === "theme") return `<td class="type"><i style="background:${COLORS[v]}"></i>${THEME_NAMES[v]}</td>`;
    return `<td class="${col.cls || ""}">${v ? esc(v) : '<span class="muted">–</span>'}</td>`;
  }).join("") + "</tr>").join("");
  $("#station-count").textContent = `${shown.length} of ${rows.length} stations`;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

load();
