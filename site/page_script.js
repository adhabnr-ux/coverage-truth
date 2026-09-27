(function () {
  const D = JSON.parse(document.getElementById("schools-data").textContent);
  const G = JSON.parse(document.getElementById("geo-data").textContent);
  const C = D.cols.reduce((o, c, i) => (o[c] = i, o), {});
  const S = D.rows.map((r, id) => {
    const o = { id };
    for (const k in C) o[k] = r[C[k]];
    return o;
  });

  const STATUS = {
    unverified: { label: "No one checked", color: "var(--none-ev)", short: "0 tests" },
    thin: { label: "Thin evidence", color: "var(--thin)", short: "1–9 tests" },
    checked: { label: "Checked by tests", color: "var(--ok)", short: "10+ tests" },
    none: { label: "No 4G claimed", color: "var(--noclaim)", short: "not claimed" },
  };
  const ORDER = ["unverified", "thin", "checked", "none"];
  const fmt = n => n.toLocaleString("en-US");
  const pct = (a, b) => (100 * a / b).toFixed(1) + "%";
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- headline numbers, computed from the data
  const tribal = S.filter(s => s.tribal), other = S.filter(s => !s.tribal);
  const count = (arr, st) => arr.filter(s => s.status === st).length;
  const tU = count(tribal, "unverified"), oU = count(other, "unverified");
  document.getElementById("lede").innerHTML =
    `Carriers tell the FCC that almost every public school in Arizona has 4G. For <strong>${tU} of the ${tribal.length} schools on tribal land</strong>, not one speed test was recorded within 2 km in a whole year, so no one outside the carrier can check that claim. Everywhere else in Arizona that happens at <span class="num">${oU}</span> of <span class="num">${fmt(other.length)}</span> schools.`;

  const cmp = document.getElementById("compare");
  [["On tribal land", tribal], ["Everywhere else", other]].forEach(([lab, arr]) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const segs = ORDER.map(st => {
      const n = count(arr, st);
      return n ? `<span title="${STATUS[st].label}: ${n}" style="width:${100 * n / arr.length}%;background:${STATUS[st].color}"></span>` : "";
    }).join("");
    row.innerHTML = `<div class="lab"><b>${lab}</b><br><span class="num">${fmt(arr.length)}</span> schools</div>
      <div><div class="bar" role="img" aria-label="${lab}: ${ORDER.map(st => STATUS[st].label + " " + count(arr, st)).join(", ")}">${segs}</div>
      <div style="font-size:12.5px;color:var(--ink-3);margin-top:4px">${ORDER.filter(st => count(arr, st)).map(st => `${STATUS[st].label} <span class="num">${pct(count(arr, st), arr.length)}</span>`).join(" · ")}</div></div>`;
    cmp.appendChild(row);
  });
  document.getElementById("legend").innerHTML = ORDER.map(st =>
    `<li><span class="dot" style="background:${STATUS[st].color}"></span>${STATUS[st].label} <span style="color:var(--ink-3)">(${STATUS[st].short} within 2 km)</span></li>`).join("");

  // ---- map
  const W = 600, LON0 = -114.9, LON1 = -108.95, LAT0 = 31.25, LAT1 = 37.1;
  const kx = Math.cos(34.2 * Math.PI / 180);
  const sc = W / ((LON1 - LON0) * kx), H = Math.round((LAT1 - LAT0) * sc);
  const px = lon => (lon - LON0) * kx * sc, py = lat => (LAT1 - lat) * sc;
  const ring = r => r.map(([x, y], i) => (i ? "L" : "M") + px(x).toFixed(1) + " " + py(y).toFixed(1)).join("") + "Z";
  const path = g => (g.type === "Polygon" ? [g.coordinates] : g.coordinates).map(p => p.map(ring).join("")).join("");
  const svg = document.getElementById("map");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  svg.appendChild(el("path", { d: path(G.az), fill: "var(--land)", stroke: "var(--ink-3)", "stroke-width": 1 }));
  G.tribal.forEach(t => {
    const p = el("path", { d: path(t.geom), fill: "var(--tribal)", stroke: "var(--tribal-line)", "stroke-width": .6 });
    const tt = el("title", {}); tt.textContent = t.name; p.appendChild(tt);
    svg.appendChild(p);
  });
  const dots = new Map();
  const drawOrder = [...S].sort((a, b) => ORDER.indexOf(b.status) - ORDER.indexOf(a.status));
  drawOrder.forEach(s => {
    const c = el("circle", { cx: px(s.lon).toFixed(1), cy: py(s.lat).toFixed(1), r: s.status === "checked" ? 2.4 : 3.6,
      fill: STATUS[s.status].color, class: "school", tabindex: s.status === "checked" ? -1 : 0 });
    const tt = el("title", {}); tt.textContent = `${s.name}, ${s.city}`; c.appendChild(tt);
    c.addEventListener("click", () => select(s.id));
    c.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(s.id); } });
    svg.appendChild(c);
    dots.set(s.id, c);
  });
  const ring1 = el("circle", { r: 8, class: "sel", cx: -50, cy: -50 });
  svg.appendChild(ring1);

  // ---- filters
  const shown = new Set(ORDER);
  const chips = document.getElementById("chips");
  ORDER.forEach(st => {
    const b = document.createElement("button");
    b.className = "chip"; b.type = "button"; b.id = "chip-" + st; b.setAttribute("aria-pressed", "true");
    b.innerHTML = `<span class="dot" style="background:${STATUS[st].color}"></span>${STATUS[st].label} <span class="num">${count(S, st)}</span>`;
    b.addEventListener("click", () => {
      shown.has(st) ? shown.delete(st) : shown.add(st);
      b.setAttribute("aria-pressed", shown.has(st));
      S.forEach(s => dots.get(s.id).classList.toggle("dim", !shown.has(s.status)));
    });
    chips.appendChild(b);
  });

  // ---- detail card
  const card = document.getElementById("card");
  function verdictText(s) {
    if (s.status === "none") return "No carrier claims 4G LTE at the 5/1 Mbps standard at this school's location on the FCC map.";
    if (s.status === "unverified") return "A carrier claims 4G here, but no public speed test was recorded within 2 km in twelve months. The claim cannot be checked with crowdsourced data.";
    if (s.status === "thin") return `A carrier claims 4G here. Only ${s.tests} speed test${s.tests === 1 ? "" : "s"} within 2 km in twelve months, too few to confirm the claim.`;
    return `A carrier claims 4G here, and ${fmt(s.tests)} speed tests within 2 km averaged ${s.dl} Mbps down, above the 5 Mbps standard.`;
  }
  function physics(s) {
    if (!s.physics) return `<div class="phys"><h4>Physics check</h4><p>Not modelled yet. The terrain physics check currently covers the Black Mesa / Piñon and Whiteriver areas.</p></div>`;
    const rows = s.physics.carriers.map(c => {
      const flag = c.implausible > 0;
      const tail = !c.judged ? "no weak-signal claims to judge" : flag
        ? `<span class="flag">${c.implausible} of ${c.judged}</span> implausible` + (c.implausible_generous === 0 ? " unless an unregistered tower is nearby" : ` (${c.implausible_generous} even allowing unregistered towers)`)
        : `all ${c.judged} consistent`;
      return `<tr><td>${esc(c.carrier)}</td><td class="num">${c.claimed_cells}</td><td>${tail}</td></tr>`;
    }).join("");
    const any = s.physics.carriers.some(c => c.implausible > 0);
    return `<div class="phys"><h4>Physics check, claims within 2 km</h4>
      <table><thead><tr><th>Carrier</th><th>Claimed hexagons</th><th>Weak-signal claims vs. terrain</th></tr></thead><tbody>${rows}</tbody></table>
      <p>${any ? "At least one carrier claims coverage here that our terrain model can reach only if that carrier has a tower nearby that is not in the FCC cellular-site records we used. That is a specific thing to verify on the ground." : "The carriers' claims near this school are physically consistent with the towers we can locate."}</p></div>`;
  }
  function select(id) {
    const s = S[id];
    const c = dots.get(id);
    ring1.setAttribute("cx", c.getAttribute("cx"));
    ring1.setAttribute("cy", c.getAttribute("cy"));
    const env = s.env === 1 ? "outdoors and in vehicles" : s.env === 0 ? "outdoors only (stationary)" : "not claimed";
    card.innerHTML = `
      <h3>${esc(s.name)}</h3>
      <div class="where">${esc(s.city)}, ${esc(s.county)} County${s.tribal ? " · " + esc(s.tribal) : ""}</div>
      <div class="verdict"><span class="dot" style="background:${STATUS[s.status].color}"></span><div><b>${STATUS[s.status].label}</b><span>${verdictText(s)}</span></div></div>
      <dl class="facts">
        <dt>FCC 4G claim at school</dt><dd>${env}</dd>
        <dt>Claimed area within 2 km</dt><dd class="num">${Math.round(100 * s.claim2km)}%</dd>
        <dt>Speed tests within 2 km</dt><dd class="num">${s.tests == null ? 0 : fmt(s.tests)}${s.dl != null ? ` · avg ${s.dl} Mbps down` : ""}</dd>
        <dt>Nearest registered 850 MHz site</dt><dd class="num">${s.towerkm} km</dd>
        <dt>Neighbourhood income</dt><dd>${s.ipr == null ? "n/a" : `<span class="num">${s.ipr}%</span> of the poverty line`}</dd>
      </dl>${physics(s)}`;
  }

  // ---- search
  const q = document.getElementById("q"), res = document.getElementById("results");
  const norm = t => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  S.forEach(s => s.key = norm(`${s.name} ${s.city} ${s.county} ${s.tribal || ""}`));
  q.addEventListener("input", () => {
    const t = norm(q.value.trim());
    if (t.length < 2) { res.hidden = true; return; }
    const parts = t.split(/\s+/);
    const hits = S.filter(s => parts.every(p => s.key.includes(p)))
      .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status)).slice(0, 30);
    res.innerHTML = hits.length ? hits.map(s => `<li><button type="button" data-id="${s.id}"><span class="dot" style="background:${STATUS[s.status].color}"></span><span>${esc(s.name)} <small>${esc(s.city)}</small></span></button></li>`).join("")
      : `<li style="padding:8px 12px;color:var(--ink-3)">No school matches "${esc(q.value)}"</li>`;
    res.hidden = false;
  });
  res.addEventListener("click", e => {
    const b = e.target.closest("button[data-id]");
    if (!b) return;
    select(+b.dataset.id); res.hidden = true; q.value = S[+b.dataset.id].name;
  });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) res.hidden = true; });
  q.addEventListener("keydown", e => {
    if (e.key === "Enter") { const b = res.querySelector("button[data-id]"); if (b) b.click(); }
    if (e.key === "Escape") res.hidden = true;
  });

  // ---- table of unchecked schools
  const no = S.filter(s => s.status === "unverified").sort((a, b) => (b.tribal ? 1 : 0) - (a.tribal ? 1 : 0) || a.city.localeCompare(b.city));
  document.getElementById("nolist").innerHTML = `<thead><tr><th>School</th><th>Town</th><th>Tribal land</th><th class="r">Income vs. poverty line</th><th class="r">Nearest registered site</th></tr></thead><tbody>` +
    no.map(s => `<tr><td><button type="button" data-id="${s.id}">${esc(s.name)}</button></td><td>${esc(s.city)}</td><td>${esc(s.tribal || "—")}</td><td class="r num">${s.ipr == null ? "n/a" : s.ipr + "%"}</td><td class="r num">${s.towerkm} km</td></tr>`).join("") + "</tbody>";
  document.getElementById("nolist").addEventListener("click", e => {
    const b = e.target.closest("button[data-id]");
    if (b) { select(+b.dataset.id); document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "start" }); }
  });

  // ---- open on a real, telling example
  const start = S.find(s => /black mesa community/i.test(s.name)) || S.find(s => s.status === "unverified");
  select(start.id);
})();
