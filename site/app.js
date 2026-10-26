"use strict";
const SPOTS = window.SPOTS || [];
const TZ = "America/Chicago";
const KIND = {dinner:"Dinner", show:"Show", bar:"Drinks", late:"Late bite"};
const FOOD = [["date","Date night"],["cheap","Cheap eats"],["dive","Dive bars"],["classic","Wisconsin classic"]];
const FUN = [["music","Live music"],["comedy","Comedy"],["theater","Theater"],["games","Games & trivia"],["bowling","Bowling & pool"],["movies","Movies"],["karaoke","Karaoke"],["dancing","Dancing"],["sports","Sports"]];
const FUN_OF_CAT = {music:"music", open_mic:"music", comedy:"comedy", theater:"theater", film:"movies", trivia:"games", bingo:"games", karaoke:"karaoke", dance:"dancing", sports:"sports"};
const FUN_OF_ACT = {bowling:"bowling", billiards:"bowling", darts:"bowling", cinema:"movies", arcade:"games", minigolf:"games", escape:"games", axe:"games", trampoline:"games", karaoke:"karaoke"};
// Parts of town: a place belongs to the closest-fitting area (smaller areas win ties).
const AREAS = [
  ["downtown","Downtown",43.0745,-89.3895,1.8], ["willy","Willy St",43.0835,-89.3655,1.0], ["east","East side",43.0960,-89.3420,4.5],
  ["west","West side",43.0660,-89.4550,5.0], ["north","North side",43.1350,-89.3600,4.0], ["south","South side",43.0300,-89.3950,4.0],
  ["middleton","Middleton",43.1000,-89.5050,4.0], ["sunprairie","Sun Prairie",43.1836,-89.2350,5.0]];
const CATS = [["all","All"],["music","Live music"],["trivia","Trivia & games"],["karaoke","Karaoke"],["bingo","Bingo & raffles"],["food","Food & specials"],["comedy","Comedy"],["theater","Theater"],["film","Movies"],["open_mic","Open mic"],["dance","Dancing"],["sports","Sports"],["other","Other"]];
const PLACES = [["all","Any place"],["bar","Bars"],["brewery","Breweries"],["veterans","VFW & Legion"],["lodge","Lodges & clubs"],["cafe","Coffee shops"],["venue","Venues"],["library","Libraries"],["community","Community"]];
const CAT_LABEL = Object.fromEntries(CATS), PLACE_LABEL = Object.fromEntries(PLACES);
const CAT_VIBES = {music:["music"],trivia:["chill"],karaoke:["dive"],bingo:["dive","classic"],food:["classic","cheap"],comedy:["date"],open_mic:["music","chill"],dance:["date"],sports:["classic","dive"],other:[]};
const PLACE_VIBES = {veterans:["classic","dive","cheap"],lodge:["classic"],cafe:["chill"],brewery:["chill","classic"],bar:["dive"]};
const DRINKY = new Set(["bar","brewery","veterans","lodge"]);
const BARLIKE = new Set(["bar","brewery"]);  // skipped entirely when nobody is drinking
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const $ = id => document.getElementById(id);

const state = {budget:60, people:2, food:[], fun:[], areas:[], drinks:"cocktails", dinner:true, show:true, from:18*60, to:23*60, rank:0, swap:{}, removed:[], day:null, cat:"all", place:"all", allDays:false};
try { const s = JSON.parse(localStorage.getItem("mp-answers2") || "null"); if (s) Object.assign(state, s, {rank:0, swap:{}, removed:[], day:null, allDays:false}); } catch (e) {}
function save(){ try { const {budget,people,food,fun,areas,drinks,dinner,show,from,to,cat,place} = state; localStorage.setItem("mp-answers2", JSON.stringify({budget,people,food,fun,areas,drinks,dinner,show,from,to,cat,place})); } catch (e) {} }

// ---------- dates in Madison time ----------
const dayKey = d => new Intl.DateTimeFormat("en-CA", {timeZone:TZ, year:"numeric", month:"2-digit", day:"2-digit"}).format(d);
const todayKey = () => dayKey(new Date());
function addDays(key, n){ const d = new Date(key + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0,10); }
function dayParts(key){ const d = new Date(key + "T12:00:00Z"); return {w:d.toLocaleString("en-US",{weekday:"short",timeZone:"UTC"}), n:d.getUTCDate(), m:d.toLocaleString("en-US",{month:"short",timeZone:"UTC"}), long:d.toLocaleString("en-US",{weekday:"long",month:"long",day:"numeric",timeZone:"UTC"})}; }
function dayName(key){ const t = todayKey(); return key === t ? "Tonight" : key === addDays(t,1) ? "Tomorrow" : dayParts(key).long; }
const hhmm = iso => iso.slice(11,16);
function fmt12(h, m){ const ap = h >= 12 && h < 24 ? "pm" : "am"; return ((h % 12) || 12) + ":" + String(m).padStart(2,"0") + " " + ap; }
function fmtTime(iso){ const [h,m] = hhmm(iso).split(":").map(Number); return fmt12(h,m); }

// ---------- events ----------
let EVENTS = [], META = null;
function evDay(e){ return e.start.slice(0,10); }
function eventsOn(key){ return EVENTS.filter(e => evDay(e) === key); }

// ---------- the form ----------
function seg(id, items, isOn, multi){
  return '<div class="seg" id="'+id+'" role="group">'+items.map(([v,l]) =>
    '<button type="button" id="'+id+'-'+v+'" data-v="'+v+'" aria-pressed="'+isOn(v)+'">'+l+'</button>').join("")+'</div>';
}
function timeSelect(id, val, fromH, toH, label){
  let o = "";
  for (let h = fromH; h <= toH; h++) for (const m of [0, 30]){
    if (h === toH && m) break;
    const v = h*60 + m; o += '<option value="'+v+'"'+(v === val ? " selected" : "")+'>'+fmt12(h % 24, m)+'</option>';
  }
  return '<select id="'+id+'" class="sel" aria-label="'+label+'">'+o+'</select>';
}
function chipRow(id, items, on){
  return '<div class="chips" id="'+id+'">'+items.map(([v,l]) => '<button type="button" class="chip" id="'+id+'-'+v+'" data-v="'+v+'" aria-pressed="'+on.includes(v)+'">'+l+'</button>').join("")+'</div>';
}
function renderForm(){
  const bad = !state.dinner && !state.show && state.drinks === "none";
  $("form").innerHTML =
    '<div class="row"><div class="lbl"><span>Budget</span><span class="val" id="budgetOut">$'+state.budget+' <small>per person</small></span></div>'+
      '<input id="budget" type="range" min="10" max="200" step="5" value="'+state.budget+'" aria-label="Budget per person"></div>'+
    '<div class="row inline"><div class="lbl"><span>Group</span></div>'+
      '<div class="stepper"><button type="button" class="round" id="minus" aria-label="Fewer people"'+(state.people<=1?" disabled":"")+'>−</button>'+
      '<span class="count" id="peopleOut">'+state.people+' <small>'+(state.people===1?"person":"people")+'</small></span>'+
      '<button type="button" class="round" id="plus" aria-label="More people"'+(state.people>=12?" disabled":"")+'>+</button></div></div>'+
    '<div class="row inline"><div class="lbl"><span>Time</span></div>'+
      '<div class="times">'+timeSelect("fromSel", state.from, 10, 22, "Start time")+'<span class="to">to</span>'+timeSelect("toSel", state.to, 12, 26, "End time")+'</div></div>'+
    '<div class="row"><div class="lbl"><span>Area</span><span class="aside">'+(state.areas.length ? "pick any" : "anywhere")+'</span></div>'+chipRow("areaChips", AREAS.map(a => [a[0], a[1]]), state.areas)+'</div>'+
    '<div class="row"><div class="lbl"><span>Food & drink</span><span class="aside">pick any</span></div>'+chipRow("foodChips", FOOD, state.food)+'</div>'+
    '<div class="row"><div class="lbl"><span>Fun</span><span class="aside">'+(state.fun.length ? "pick any" : "anything")+'</span></div>'+chipRow("funChips", FUN, state.fun)+'</div>'+
    '<div class="row"><div class="lbl"><span>Drinks</span></div>'+
      seg("drinkSeg", [["cocktails","Cocktails"],["beer","Beer"],["none","No drinks"]], v => state.drinks === v)+'</div>'+
    '<div class="row"><div class="lbl"><span>Plans</span><span class="aside">pick any</span></div>'+
      seg("planSeg", [["dinner","Dinner"],["show","Show or event"]], v => state[v])+
      (bad ? '<p class="warn">Pick dinner or a show so there\'s a night to plan.</p>' : '')+'</div>'+
    '<button type="button" class="btn go" id="go">Plan my night</button>';
}
function changed(){ state.rank = 0; state.swap = {}; state.removed = []; save(); renderPlan(); }

$("form").addEventListener("change", e => {
  if (e.target.id !== "fromSel" && e.target.id !== "toSel") return;
  state.from = +$("fromSel").value; state.to = +$("toSel").value;
  if (state.to < state.from + 120){  // keep at least two hours
    if (e.target.id === "fromSel") state.to = Math.min(26*60, state.from + 120); else state.from = Math.max(10*60, state.to - 120);
    renderForm();
  }
  changed();
});
$("form").addEventListener("input", e => {
  if (e.target.id !== "budget") return;
  state.budget = +e.target.value;
  $("budgetOut").innerHTML = "$"+state.budget+" <small>per person</small>";
  changed();
});
$("form").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.id === "go"){ state.rank = 0; renderPlan(); $("planSec").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"start"}); return; }
  if (b.id === "minus") state.people = Math.max(1, state.people-1);
  else if (b.id === "plus") state.people = Math.min(12, state.people+1);
  else if (b.closest("#areaChips, #foodChips, #funChips")){
    const list = state[{areaChips:"areas", foodChips:"food", funChips:"fun"}[b.parentElement.id]], v = b.dataset.v, i = list.indexOf(v);
    if (i >= 0) list.splice(i, 1); else list.push(v);
    if (b.parentElement.id === "areaChips") renderDays(), renderEvents();
  }
  else if (b.closest("#drinkSeg")) state.drinks = b.dataset.v;
  else if (b.closest("#planSeg")) state[b.dataset.v] = !state[b.dataset.v];
  else return;
  const id = b.id; changed(); renderForm();
  const again = document.getElementById(id); if (again && !again.disabled) again.focus();
});

// ---------- turning events into plan stops ----------
// ---------- places ----------
let RESTAURANTS = [], BARS = [], ACTS = [];  // from OpenStreetMap, loaded with the events
const CAPITOL = {lat:43.0747, lon:-89.3841};
function areaOf(p){
  if (!p || p.lat == null) return null;
  let best = null, bestR = 1e9;
  for (const [id,, la, lo, rKm] of AREAS){
    const d = miles(p, {lat:la, lon:lo}) * 1.609;
    if (d <= rKm && rKm < bestR){ best = id; bestR = rKm; }
  }
  return best || "outside";
}
const inAreas = p => !state.areas.length || (p && p.lat != null && state.areas.includes(areaOf(p)));
const outOfTown = p => p && p.lat != null && miles(p, CAPITOL) > 20;
const funOk = f => !state.fun.length || state.fun.includes(f);
// Rough price when a listing doesn't give one, by kind of event.
const EST = {music:15, comedy:25, theater:35, film:12, sports:30, dance:12, trivia:0, bingo:5, karaoke:0, open_mic:0, food:0, other:10};
// Links never go to a third-party calendar; without a venue or event site, search for the event.
function eventUrl(e){
  const u = e.url || "";
  if (u && !/isthmus\.com/i.test(u)) return u;
  return "https://www.google.com/search?q=" + encodeURIComponent(e.title + " " + e.venue + " Madison");
}
const FOODKINDS = /pizza|burger|taco|mexican|burrito|sushi|japanese|thai|chinese|indian|bbq|barbecue|diner|breakfast|pancake|wings?|chicken|sandwich|deli|ramen|noodle|pho|vietnamese|italian|pasta|donut|dessert|ice cream|steak|seafood|fish|kebab|mediterranean|korean|cuban|bakery/;
const foodKind = s => { const m = (s.d + " " + s.n).toLowerCase().match(FOODKINDS); return m ? m[0].replace(/s$/, "").replace(/^(burrito|taco)$/, "mexican") : null; };
function activityStop(a){
  return {n:a.name, k:"show", act:true, lat:a.lat, lon:a.lon, p:a.price, dur:a.minutes, hrs:a.hours, osm:true, tav:a.bar,
    v:[], fun:FUN_OF_ACT[a.type], d:a.label + (a.type === "cinema" ? " (check showtimes)" : ""), w:a.address || "", url:a.website || "", mapId:a.id, label:a.label};
}
const FAMILY = /\bfamil(?:y|ies)\b|\bkids?\b|children|toddler|all ages matinee/i;  // left out of night plans unless picked
const pinned = () => state.pin ? EVENTS.find(e => e.id === state.pin) || null : null;
const norm = n => String(n).toLowerCase().replace(/&/g," and ").replace(/[^a-z0-9 ]+/g," ").replace(/\b(the|and|bar|pub|tavern|restaurant|grill|lounge|cocktail|company|co)\b/g," ").replace(/\s+/g," ").trim();
function miles(a, b){
  if (!a || !b || a.lat == null || b.lat == null) return null;
  const R = 3959, r = x => x * Math.PI / 180, dLa = r(b.lat - a.lat), dLo = r(b.lon - a.lon);
  const h = Math.sin(dLa/2)**2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dLo/2)**2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
const fmtMi = m => m.toFixed(m < 10 ? 1 : 0) + " mi";
// hand-picked spots borrow coordinates and websites from the map data when the names match
function enrichSpots(){
  const byName = {};
  for (const r of RESTAURANTS) byName[norm(r.name)] = byName[norm(r.name)] || r;
  for (const v of BARS) byName[norm(v.name)] = byName[norm(v.name)] || v;
  for (const s of SPOTS){
    const m = byName[norm(s.n.replace(/ (late-night menu|slice)$/i, ""))];
    if (m){ if (s.lat == null){ s.lat = m.lat; s.lon = m.lon; } if (!s.url && m.website) s.url = m.website; s.mapId = m.id; }
  }
}
function restaurantStop(r, role){
  return {n:r.name, k:role, lat:r.lat, lon:r.lon, p:r.price, v:r.vibes || [], tav:r.bar, hrs:r.hours, osm:true,
    w:r.address || "", d:(r.cuisine ? r.cuisine.replace(/\b\w/g, c => c.toUpperCase()) : (r.fast ? "Quick bite" : "Restaurant")), url:r.website || "", mapId:r.id};
}
function barStop(v){
  return {n:v.name, k:"bar", lat:v.lat, lon:v.lon, p:v.kind === "brewery" ? 14 : 13, v:v.kind === "brewery" ? ["chill"] : [], osm:true,
    w:v.address || "", d:v.kind === "brewery" ? "Brewery taproom" : "Neighborhood bar", url:v.website || "", mapId:v.id};
}
// Drop-in events (karaoke, trivia, watch parties...) don't need you there at the first minute.
const DROPIN_CATS = new Set(["karaoke","trivia","bingo","open_mic","sports","dance"]);
const DROPIN_TITLE = /\bdj\b|open (?:mic|jam)|happy hour|watch party|karaoke|trivia|bingo|game night/i;
// What you'd pay walking in: the door / day-of-show price when the listing gives one.
function evPrice(e){
  const d = [...String(e.description || "").matchAll(/\$\s?(\d{1,3}(?:\.\d{2})?)\s*(?:DOS\b|day of(?: the)? show|at the door|door)/gi)].map(m => +m[1]).filter(v => v > 0);
  return d.length ? Math.min(...d) : e.price;
}
function eventStop(e){
  // Events are never the meal: when dinner is on, every plan gets a real dinner stop.
  const role = (!state.show && DRINKY.has(e.venue_kind) && e.category !== "food") ? "bar" : (!state.dinner && e.category === "food") ? "dinner" : "show";
  const drinks = DRINKY.has(e.venue_kind) ? (state.drinks === "cocktails" ? 14 : state.drinks === "beer" ? 10 : 0) : 0;
  const known = evPrice(e);
  const food = role === "dinner" ? (known ?? 15) : (known ?? EST[e.category] ?? 10);
  return {id:e.id, n:e.title, k:role, lat:e.lat, lon:e.lon, venue:e.venue, p:Math.round(food + drinks),
    v:[...(CAT_VIBES[e.category]||[]), ...(PLACE_VIBES[e.venue_kind]||[])],
    w:e.venue + (e.address ? " · " + e.address : ""), d:e.description || (CAT_LABEL[e.category] || "Event") + " at " + e.venue + (e.via ? " (listed by " + e.via + ")" : ""),
    at:e.all_day ? null : hhmm(e.start), live:true, cat:e.category, fun:FUN_OF_CAT[e.category], est:known == null, dropin: DROPIN_CATS.has(e.category) || DROPIN_TITLE.test(e.title), weekly:e.source === "weekly", url:eventUrl(e), urlSearch:eventUrl(e).startsWith("https://www.google.com/search"),
    g:e.venue_kind === "veterans" || e.venue_kind === "lodge" ? 1 : 0};
}
function cost(s){
  if (s.live) return s.p;
  let p = s.p;
  if (s.k === "bar" && state.drinks === "cocktails" && !s.c) p += 6;
  if (s.k === "dinner" && state.drinks === "cocktails") p += 6;
  if (s.k === "dinner" && state.drinks === "none") p = Math.max(6, p-6);
  return p;
}
function stopScore(s){
  let x = 0;
  if (!s.live && !s.act) s.v.forEach(v => { if (state.food.includes(v)) x += 2; });
  if (state.drinks === "cocktails" && s.c) x += s.k === "bar" ? 5 : 2;
  if (state.drinks === "cocktails" && s.k === "bar" && s.v.includes("dive") && !state.food.includes("dive")) x -= 2;
  if (state.drinks === "beer" && s.k === "bar"){ if (s.v.includes("dive")) x += 1; if (s.c) x -= 1; }
  const n = state.people;
  if (n >= 5){ if (s.t === 1) x -= 6; if (s.g) x += 2; } else if (n >= 3){ if (s.t === 1) x -= 2; if (s.g) x += 1; }
  if (s.live || s.act) x += state.fun.length && state.fun.includes(s.fun) ? 4 : 2;
  if (!s.osm && !s.live) x += 1;   // hand-picked favorites get a small nudge
  if (s.osm && s.url) x += 0.5;    // a place with a website is easier to check
  return x;
}
const toMin = t => { if (!t) return null; let [h,m] = t.split(":").map(Number); if (h < 6) h += 24; return h*60 + m; };
const DUR = {dinner:90, show:120, bar:75, late:30};
const durOf = s => s.dur || (s.dropin ? 90 : (DUR[s.k] || 60));
const ORDER = {dinner:0, show:1, bar:2, late:3};
const toMinX = t => { const [h,m] = t.split(":").map(Number); return h*60 + m; };  // no wrap: "26:30" = 2:30 am
function weekday(key){ return (new Date(key + "T12:00:00Z").getUTCDay() + 6) % 7; }  // 0 = Monday
// Opening window for a place on a given night. undefined = hours unknown (assume open); null = closed.
function openWindow(s, key){
  if (!("hrs" in s) || s.hrs === undefined) return undefined;
  if (!s.hrs) return s.k === "late" ? null : undefined;   // late-night stops need confirmed hours
  const w = s.hrs.find(([days]) => days.includes(weekday(key)));
  return w ? [toMinX(w[1]), toMinX(w[2])] : null;
}
const lateWindow = (s, key) => { const w = openWindow(s, key); return w === undefined ? [0, 30*60] : w; };
// Put the stops in order with times. ok=false when a stop can't fit (closed, overlapping, too late).
// Dinner goes before the show when there's room, otherwise after it.
function schedule(stops, key){
  const first = timeline(stops, key, false);
  if (first.ok || !stops.some(s => s.at) || !stops.some(s => s.k === "dinner" && !s.at)) return first;
  const second = timeline(stops, key, true);
  return second.ok ? second : first;
}
function timeline(stops, key, dinnerAfter){
  const fixedEnd = Math.max(...stops.filter(s => s.at).map(s => toMin(s.at) + durOf(s)));
  const sortKey = s => s.at ? toMin(s.at) : (dinnerAfter && s.k === "dinner") ? fixedEnd - 1 : ORDER[s.k]*120 + 19*60;
  const list = [...stops].sort((a,b) => sortKey(a) - sortKey(b) || ORDER[a.k]-ORDER[b.k]);
  let t = state.from;
  const firstFixed = list.findIndex(s => s.at);
  if (firstFixed > 0){
    const lead = list.slice(0, firstFixed).reduce((n, s) => n + (DUR[s.k] || 60), 0);
    t = Math.max(t, Math.min(t + 60, toMin(list[firstFixed].at) - lead));  // dinner ends as the show starts
  }
  const items = []; let ok = true;
  for (const s of list){
    if (s.at){
      const at = toMin(s.at), grace = s.dropin ? 60 : 15;  // drop-ins: arrive up to an hour late
      if (at < t - grace) ok = false;
      t = Math.max(t, at);
    }
    if (!s.live){
      const w = openWindow(s, key);
      if (w === null) ok = false;
      else if (w){ t = Math.max(t, w[0]); if (t > w[1] - (s.k === "late" ? 30 : 45)) ok = false; }
    }
    items.push({s, t});
    t += durOf(s);
  }
  if (t > state.to + 15) ok = false;  // runs past the end time
  return {items, ok};
}
function nearest(list, anchor, n, maxMi){
  if (!anchor || anchor.lat == null) return list.slice(0, n);
  const withD = list.map(s => [s, miles(anchor, s)]).filter(([, d]) => d != null && d <= maxMi).sort((a,b) => a[1]-b[1]);
  return withD.slice(0, n).map(([s]) => s);
}
// Candidate places for one plan: near the anchor (the event), else the best-scoring spread across town.
function candidates(anchor){
  const dry = state.drinks === "none";
  const fits = s => !(dry && s.tav) && cost(s) <= state.budget;
  const dinnerAll = [...SPOTS.filter(s => s.k === "dinner"),
    ...RESTAURANTS.filter(r => !SPOTS.some(s => s.mapId === r.id)).map(r => restaurantStop(r, "dinner"))].filter(fits);
  const barAll = dry ? [] : [...SPOTS.filter(s => s.k === "bar"),
    ...BARS.filter(v => !SPOTS.some(s => s.mapId === v.id)).map(barStop)];
  const lateAll = [...SPOTS.filter(s => s.k === "late"),
    ...RESTAURANTS.filter(r => r.price <= 16 && r.hours && r.hours.some(w => toMinX(w[2]) >= 23*60+30) && !SPOTS.some(s => s.mapId === r.id))
      .map(r => restaurantStop(r, "late"))].filter(s => !(dry && s.tav) && lateWindow(s, state.day));
  const byScore = arr => [...arr].sort((a,b) => stopScore(b) - stopScore(a));
  const pick = (arr, n) => {
    if (state.areas.length){ const inside = arr.filter(inAreas); if (inside.length >= 3) arr = inside; }
    if (anchor && anchor.lat != null){
      for (const r of [0.8, 1.5, 3]){ const near = nearest(byScore(arr), anchor, 40, r); if (near.length >= Math.min(n, 4)) return byScore(near).slice(0, n); }
      return nearest(arr, anchor, n, 99);
    }
    return byScore(arr).slice(0, n);
  };
  return {dinners: pick(dinnerAll, 8), bars: pick(barAll, 7), lates: pick(lateAll, 4)};
}
let PLAN_NOTE = "";
const MAX_PLANS = 20;
function plans(opts = {}){
  if (!opts.probe) PLAN_NOTE = "";
  const pinEv = pinned(), pin = pinEv ? eventStop(pinEv) : null;
  if (!pin && !state.dinner && !state.show && state.drinks === "none") return [];
  const dry = state.drinks === "none";
  const inWindow = e => { const m = toMin(hhmm(e.start)); return m >= state.from - 30 && m <= state.to - 60; };
  const evening = eventsOn(state.day).filter(e => !e.all_day && inWindow(e) && !(dry && BARLIKE.has(e.venue_kind)) && !(pin && e.id === pin.id)
      && e.lat != null && !FAMILY.test(e.title) && inAreas(e) && !outOfTown(e) && funOk(FUN_OF_CAT[e.category])).map(eventStop)
    .sort((a,b) => stopScore(b) - stopScore(a));
  // anytime activities (bowling, a movie...) when those are picked under Fun
  const wantActs = state.show && state.fun.some(f => Object.values(FUN_OF_ACT).includes(f));
  const acts = wantActs ? ACTS.map(activityStop).filter(s => state.fun.includes(s.fun) && inAreas(s) && !outOfTown(s) && !(dry && s.tav)
      && openWindow(s, state.day) !== null && cost(s) <= state.budget).sort((a,b) => stopScore(b) - stopScore(a) || (miles(a, CAPITOL) - miles(b, CAPITOL))).slice(0, 8) : [];
  const role = pin ? pin.k : null;
  // each plan is built around one anchor: the pinned event, a show, or (no show) a dinner spot
  let anchors;
  if (pin) anchors = [pin];
  else if (state.show && (evening.some(s => s.k === "show") || acts.length)) anchors = [...evening.filter(s => s.k === "show").slice(0, 16), ...acts];
  else anchors = [null];
  let out = [];
  for (const anchor of anchors){
    const c = candidates(anchor);
    const evDinners = evening.filter(s => s.k === "dinner");
    const dinners = (anchor && anchor.k === "dinner") ? [anchor] : state.dinner ? [...c.dinners, ...(anchor ? [] : evDinners)] : [null];
    const shows = (anchor && anchor.k === "show") ? [anchor] : [null];
    const lates = [null, ...c.lates];
    const barSets = [];
    if (anchor && anchor.k === "bar"){ barSets.push([anchor]); c.bars.forEach(b => barSets.push([anchor, b])); }
    else {
      if (dry || state.dinner || anchor) barSets.push([]);  // drinks can happen at dinner or the show
      for (let i = 0; i < c.bars.length; i++){ barSets.push([c.bars[i]]); for (let k = i+1; k < c.bars.length; k++) barSets.push([c.bars[i], c.bars[k]]); }
    }
    out = out.concat(build(state.budget, anchor, c, dinners, shows, barSets, lates));
  }
  if (!out.length && !pin && anchors[0] && !opts.probe){
    // no event fits this window with dinner: plan the night without one, and say so
    if (!opts.probe) PLAN_NOTE = "noshow";
    const c = candidates(null);
    const barSets = [[]];
    if (!dry) for (let i = 0; i < c.bars.length; i++){ barSets.push([c.bars[i]]); for (let k = i+1; k < c.bars.length; k++) barSets.push([c.bars[i], c.bars[k]]); }
    out = build(state.budget, null, c, state.dinner ? c.dinners : [null], [null], barSets, [null, ...c.lates]);
  }
  if (!out.length && pin){  // the event alone is over budget: still show the best night around it
    const c = candidates(pin);
    out = build(Infinity, pin, c, pin.k === "dinner" ? [pin] : state.dinner ? c.dinners : [null], pin.k === "show" ? [pin] : [null], [[]], [null]);
  }
  // Variety: take the best plan for each event in turn, then the second best, and so on,
  // so the list rotates through the night's events instead of repeating one.
  const groups = new Map();
  for (const p of out){ const k = p.anchor ? p.anchor.n : ""; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
  const order = [...groups.values()].map(g => g.sort((a,b) => b.score - a.score)).sort((a,b) => b[0].score - a[0].score);
  const seen = new Set(), used = {}, uniq = [];
  for (let round = 0; uniq.length < MAX_PLANS && order.some(g => g.length > round); round++){
    for (const g of order){
      const p = g[round]; if (!p) continue;
      const rest = p.stops.filter(s => s !== pin && !s.live && !s.act);  // places should vary
      const key = p.stops.map(s => s.n).join("|");
      if (seen.has(key) || rest.some(s => (used[s.n] || 0) >= 2)) continue;
      seen.add(key); rest.forEach(s => used[s.n] = (used[s.n] || 0) + 1);
      uniq.push(p); if (uniq.length >= MAX_PLANS) break;
    }
    if (round > 40) break;
  }
  return uniq;

  function build(limit, anchor, c, dinners, shows, barSets, lates){
    const out = [];
    for (const d of dinners) for (const sh of shows) for (const bs of barSets) for (const l of lates){
      if (state.dinner && !d) continue;  // dinner was asked for: every plan has one
      const stops = [d, sh, ...bs, l].filter(Boolean);
      if (!stops.length) continue;
      const cst = stops.reduce((t,s) => t + cost(s), 0);
      if (cst > limit) continue;
      const sc = schedule(stops, state.day);
      if (!sc.ok) continue;  // closed, or two things at once
      let score = stops.reduce((t,s) => t + stopScore(s), 0);
      // walking between stops: free within half a mile, then it costs
      for (let i = 1; i < sc.items.length; i++){ const m = miles(sc.items[i-1].s, sc.items[i].s); if (m != null) score -= Math.max(0, m - 0.5) * 2.5; }
      const use = cst / Math.min(limit, state.budget);
      score += state.food.includes("cheap") ? (1 - use)*4 : use*8;  // use the money unless they asked for cheap
      if (state.budget >= 90) stops.forEach(s => { if (s.c || s.v.includes("date")) score += 1.5; });  // a bigger budget leans nicer
      if (d && l && (norm(d.n).split(" ")[0] === norm(l.n).split(" ")[0] || (foodKind(d) && foodKind(d) === foodKind(l)))) continue;  // no pizza after pizza
      if (!d && !sh && bs.length < 2) score -= 3;
      if (state.drinks !== "none" && !bs.length) score -= 2;  // drinking, but no bar stop
      const di = sc.items.findIndex(x => x.s.k === "dinner"), si = sc.items.findIndex(x => x.s.at);
      if (di > si && si >= 0 && di >= 0) score -= 1.5;  // prefer dinner before the show
      out.push({stops, cost:cst, score, anchor, c});
    }
    return out;
  }
}

// ---------- the plan on screen ----------
let PLAN_COUNT = 1, CURRENT = null;
const SWAP_ROLES = ["dinner", "late"];
function renderPin(){
  const e = pinned();
  $("pinNote").hidden = !e;
  if (e) $("pinName").textContent = e.title + " at " + e.venue + ", " + fmtTime(e.start);
}
// Other places that could take this stop's slot without breaking the plan, nearest the anchor first.
function alternatives(p, role){
  const cur = p.stops.find(s => s.k === role && !s.live);
  if (!cur) return [];
  const pool = role === "dinner" ? p.c.dinners : p.c.lates;
  const ref = p.anchor && p.anchor.lat != null ? p.anchor : cur;
  const other = p.stops.find(s => s.k === (role === "dinner" ? "late" : "dinner") && !s.live);
  const others = pool.filter(s => s !== cur && s.n !== cur.n).filter(s => !(other && foodKind(other) && foodKind(other) === foodKind(s))).filter(s => {
    const stops = p.stops.map(x => x === cur ? s : x);
    const cst = stops.reduce((t,x) => t + cost(x), 0);
    return cst <= Math.max(state.budget, p.cost) && schedule(stops, state.day).ok;
  }).sort((a,b) => (miles(ref, a) ?? 9) - (miles(ref, b) ?? 9));
  return [cur, ...others];
}
function applySwaps(p){
  let stops = p.stops;
  for (const role of SWAP_ROLES){
    const alts = alternatives({...p, stops}, role);
    const i = (state.swap[role] || 0) % Math.max(1, alts.length);
    if (alts.length > 1 && i){ const cur = alts[0]; stops = stops.map(x => x === cur ? alts[i] : x); }
  }
  return stops;
}
// Find a nearby time window where an event does fit, to offer as a one-click change.
function showSuggestion(){
  const keep = {from: state.from, to: state.to};
  const tries = [{to: keep.to + 60}, {to: keep.to + 120}, {from: keep.from - 60}, {from: keep.from - 60, to: keep.to + 60}]
    .map(t => ({from: Math.max(10*60, t.from ?? keep.from), to: Math.min(26*60, t.to ?? keep.to)}))
    .filter(t => t.from !== keep.from || t.to !== keep.to);
  for (const t of tries){
    Object.assign(state, t);
    const L = plans({probe: true});
    const ev = L.length && L[0].stops.find(s => s.live);
    Object.assign(state, keep);
    if (ev) return {...t, title: ev.n, at: ev.at};
  }
  return null;
}
const fmtM = m => fmt12(Math.floor(m/60) % 24, m % 60);
function renderPlan(){
  renderPin();
  const list = plans(), route = $("route");
  PLAN_COUNT = Math.max(1, list.length);
  route.innerHTML = "";
  if (!list.length){
    CURRENT = null; $("goBtn").hidden = true; $("restore").hidden = true;
    $("totalPP").textContent = ""; $("totalGrp").textContent = "";
    $("planTitle").textContent = dayName(state.day); $("pager").hidden = true;
    const why = (!state.dinner && !state.show && state.drinks === "none") ? "Pick dinner or a show so there's something to plan." : "Nothing fits $"+state.budget+" a person between "+fmt12(Math.floor(state.from/60)%24, state.from%60)+" and "+fmt12(Math.floor(state.to/60)%24, state.to%60)+". Try a longer evening, a bigger budget, or fewer stops.";
    route.innerHTML = '<li class="empty">'+why+'</li>'; return;
  }
  const base = list[state.rank % list.length];
  const all = applySwaps(base);
  const stops = all.filter(s => !state.removed.includes(s.n));
  const p = {...base, stops, cost: stops.reduce((t,s) => t + cost(s), 0)};
  CURRENT = base;
  const pinS = pinned(), anchor = base.anchor;
  schedule(p.stops, state.day).items.forEach(({s, t}, idx) => {
    const li = document.createElement("li"); li.className = "stop"; li.style.animationDelay = (idx*60)+"ms";
    const meal = s.k === "dinner" ? (t < 11*60 ? "Brunch" : t < 15*60 ? "Lunch" : "Dinner") : KIND[s.k];
    const label = s.act ? s.label + " · Anytime" : s.live ? (s.id === state.pin ? "Your pick · " : "") + (CAT_LABEL[s.cat] || "Event") + (s.weekly ? " · Weekly" : "")
      : meal + (s.c && state.drinks === "cocktails" ? " · Cocktails" : "");
    const dist = !s.live && !s.act && anchor && anchor !== s && anchor.lat != null ? miles(anchor, s) : null;
    const near = dist != null ? '<span class="dist">'+(dist < 0.1 ? "Next door to " : fmtMi(dist)+" from ")+esc(anchor.venue || anchor.n)+'</span>' : "";
    const site = s.url ? ' · <a href="'+esc(s.url)+'" target="_blank" rel="noopener">'+(s.live ? (s.urlSearch ? "Find tickets & info" : "Event page") : "Website")+' ↗</a>' : "";
    const alts = SWAP_ROLES.includes(s.k) && !s.live ? alternatives({...base, stops: p.stops}, s.k) : [];
    const removable = !s.live && (s.k === "bar" || s.k === "late");  // dinner and the event stay
    const rm = removable ? '<button type="button" class="link sm rm" data-n="'+esc(s.n)+'">Remove this stop</button>' : "";
    const swap = alts.length > 1 ? '<div class="swap" data-role="'+s.k+'"><button type="button" class="arrow sm" data-dir="-1" aria-label="Previous '+meal.toLowerCase()+' option">‹</button><span>'+(((state.swap[s.k]||0) % alts.length)+1)+' of '+alts.length+' nearby</span><button type="button" class="arrow sm" data-dir="1" aria-label="Next '+meal.toLowerCase()+' option">›</button></div>' : "";
    li.innerHTML = '<div class="time">'+fmt12(Math.floor(t/60)%24, t%60)+'</div><div class="rail"><span class="dot'+(s.live?" live":"")+'"></span></div>'+
      '<div class="stop-body"><div class="kind">'+esc(label)+'</div><div class="name">'+(s.live && s.url ? '<a href="'+esc(s.url)+'" target="_blank" rel="noopener">'+esc(s.n)+'</a>' : esc(s.n))+'</div>'+
      '<p class="why">'+esc(s.d)+'</p><div class="where">'+esc(s.w)+site+near+'</div>'+swap+rm+'</div>'+
      '<div class="cost">~$'+cost(s)+(s.est ? '<small>est.</small>' : '')+'</div>';
    route.appendChild(li);
  });
  if (PLAN_NOTE === "noshow"){
    const sug = showSuggestion();
    route.insertAdjacentHTML("afterbegin", '<li class="note-box">No listed event fits between '+fmtM(state.from)+' and '+fmtM(state.to)+' with dinner, so this plan skips the show.'+
      (sug ? ' <button type="button" class="link sm" id="applySug" data-from="'+sug.from+'" data-to="'+sug.to+'">Change to '+fmtM(sug.from)+'–'+fmtM(sug.to)+' to fit '+esc(sug.title)+' ('+fmtM(toMin(sug.at))+')</button>' : '')+'</li>');
  }
  const gone = all.filter(s => state.removed.includes(s.n));
  $("restore").hidden = !gone.length;
  if (gone.length) $("restore").textContent = "Put back " + gone.map(s => s.n).join(" and ");
  const dir = directionsUrl(schedule(p.stops, state.day).items.map(x => x.s));
  $("goBtn").hidden = !dir; if (dir) $("goBtn").href = dir;
  $("totalPP").textContent = "~$"+p.cost+" of $"+state.budget+" each";
  $("totalPP").classList.toggle("over", p.cost > state.budget);
  $("totalGrp").textContent = state.people > 1 ? "About $"+p.cost*state.people+" for "+state.people : "";
  $("planTitle").textContent = dayName(state.day);
  $("pager").hidden = list.length < 2;
  $("pageOf").textContent = ((state.rank % list.length)+1) + " of " + list.length;
}
$("route").addEventListener("click", e => {
  const rmb = e.target.closest(".rm");
  if (rmb){ state.removed.push(rmb.dataset.n); renderPlan(); $("goBtn").focus(); return; }
  const sug = e.target.closest("#applySug");
  if (sug){ state.from = +sug.dataset.from; state.to = +sug.dataset.to; state.rank = 0; state.swap = {}; save(); renderForm(); renderPlan(); return; }
  const b = e.target.closest(".swap .arrow"); if (!b || !CURRENT) return;
  const role = b.closest(".swap").dataset.role;
  const n = alternatives({...CURRENT, stops: applySwaps(CURRENT)}, role).length || 1;
  state.swap[role] = (((state.swap[role] || 0) + +b.dataset.dir) % n + n) % n;
  renderPlan();
  const again = document.querySelector('.swap[data-role="'+role+'"] .arrow[data-dir="'+b.dataset.dir+'"]'); if (again) again.focus();
});
$("nextPlan").onclick = () => { state.rank++; state.swap = {}; state.removed = []; renderPlan(); };
$("prevPlan").onclick = () => { state.rank = state.rank > 0 ? state.rank - 1 : PLAN_COUNT - 1; state.swap = {}; state.removed = []; renderPlan(); };
$("restore").onclick = () => { state.removed = []; renderPlan(); };
// Google Maps directions through every stop, in order, starting from wherever the person is.
function placeText(s){
  const where = s.live ? [s.venue, (s.w.split(" · ")[1] || "")] : [s.n, s.w];
  const text = where.filter(Boolean).join(", ");
  if (text) return text + ", Madison, WI";  // names find the right place in Maps better than coordinates
  return s.lat != null ? s.lat.toFixed(6) + "," + s.lon.toFixed(6) : null;
}
function directionsUrl(stops){
  const pts = stops.map(placeText).filter(Boolean);
  if (!pts.length) return "";
  const u = new URL("https://www.google.com/maps/dir/");
  u.searchParams.set("api", "1");
  u.searchParams.set("destination", pts[pts.length - 1]);
  if (pts.length > 1) u.searchParams.set("waypoints", pts.slice(0, -1).join("|"));
  return u.toString();
}

// ---------- day strip ----------
function renderDays(){
  const t = todayKey();
  if (!state.day || state.day < t) state.day = t;
  let h = "";
  for (let i = 0; i < 14; i++){
    const k = addDays(t, i), p = dayParts(k), n = eventsOn(k).filter(inAreas).length;
    h += '<button type="button" class="day" id="day-'+k+'" data-k="'+k+'" aria-pressed="'+(k===state.day)+'" aria-label="'+esc(dayName(k))+', '+n+' events"><span class="w">'+(i===0?"Today":p.w)+'</span><span class="n">'+p.n+'</span><span class="c">'+(META ? n+" on" : "")+'</span></button>';
  }
  $("days").innerHTML = h;
}
$("days").addEventListener("click", e => {
  const b = e.target.closest(".day"); if (!b) return;
  state.day = b.dataset.k; state.rank = 0; state.swap = {}; state.removed = []; state.allDays = false;
  const pe = pinned(); if (pe && evDay(pe) !== state.day) state.pin = null;
  renderDays(); renderPlan(); renderEvents();
});

// ---------- event list ----------
function renderFilters(){
  const present = new Set(EVENTS.map(e => e.category)), places = new Set(EVENTS.map(e => e.venue_kind));
  $("catChips").innerHTML = CATS.filter(([id]) => id === "all" || present.has(id)).map(([id,l]) => '<button type="button" class="chip sm" data-v="'+id+'" aria-pressed="'+(state.cat===id)+'">'+l+'</button>').join("");
  $("placeChips").innerHTML = PLACES.filter(([id]) => id === "all" || places.has(id)).map(([id,l]) => '<button type="button" class="chip sm" data-v="'+id+'" aria-pressed="'+(state.place===id)+'">'+l+'</button>').join("");
}
$("catChips").addEventListener("click", e => { const b = e.target.closest(".chip"); if (!b) return; state.cat = b.dataset.v; save(); renderFilters(); renderEvents(); });
$("placeChips").addEventListener("click", e => { const b = e.target.closest(".chip"); if (!b) return; state.place = b.dataset.v; save(); renderFilters(); renderEvents(); });

function evRow(e){
  const tags = [CAT_LABEL[e.category] || "Event", PLACE_LABEL[e.venue_kind] ? PLACE_LABEL[e.venue_kind].replace(/s$/,"") : ""].filter(Boolean)
    .map(t => '<span class="tag">'+esc(t)+'</span>').join("") +
    (e.source === "weekly" ? '<span class="tag weekly">Weekly</span>' : "") +
    '<a class="tag" href="'+esc(eventUrl(e))+'" target="_blank" rel="noopener">'+(eventUrl(e).startsWith("https://www.google.com/search") ? "Find tickets & info" : "Details")+' ↗</a>' +
    (e.via ? '<span class="tag">Listed by '+esc(e.via)+'</span>' : "") +
    (outOfTown(e) ? '<span class="tag">Out of town'+(e.city ? ": "+esc(e.city) : "")+'</span>' : "") +
    (e.confirm ? '<a class="tag" href="'+esc(e.confirm)+'" target="_blank" rel="noopener">Confirm</a>' : "");
  const pr = evPrice(e);
  const price = pr == null ? '<span class="est">~$'+(EST[e.category] ?? 10)+' est.</span>' : +pr ? "$" + (+pr).toFixed(+pr % 1 ? 2 : 0) : "Free";
  const on = e.id === state.pin;
  const btn = (e.all_day || hhmm(e.start) < "10:00") ? "" : on  // the planner's day starts at 10 am
    ? '<button type="button" class="incl on" data-id="'+esc(e.id)+'" aria-pressed="true">✓ In your night</button>'
    : '<button type="button" class="incl" data-id="'+esc(e.id)+'" aria-pressed="false">Include in my night</button>';
  return '<div class="ev'+(on ? " picked" : "")+'"><div class="tm">'+(e.all_day ? "All day" : fmtTime(e.start))+'</div><div><div class="t">'+esc(e.title)+'</div><div class="m">'+esc(e.venue)+(e.address ? " · "+esc(e.address) : "")+'</div><div class="tags">'+tags+'</div>'+btn+'</div><div class="c">'+price+'</div></div>';
}
function renderEvents(){
  const el = $("events");
  if (!META){ return; }
  let list = eventsOn(state.day).filter(inAreas);
  if (state.cat !== "all") list = list.filter(e => e.category === state.cat);
  if (state.place !== "all") list = list.filter(e => e.venue_kind === state.place);
  $("evTitle").textContent = "What's on " + (["Tonight","Tomorrow"].includes(dayName(state.day)) ? dayName(state.day).toLowerCase() : dayName(state.day));
  $("evCount").textContent = list.length + (list.length === 1 ? " event" : " events");
  if (!list.length){ el.innerHTML = '<p class="empty">Nothing listed'+(state.cat!=="all"||state.place!=="all"||state.areas.length ? " with these filters" : "")+' yet. Small spots often post late, so check back.</p>'; return; }
  let h = "", last = "";
  for (const e of list){
    const k = evDay(e);
    h += evRow(e);
  }
  el.innerHTML = h;
}
function pinEvent(id){
  const e = EVENTS.find(x => x.id === id);
  if (!e || state.pin === id){ state.pin = null; }
  else {
    state.pin = id; state.day = evDay(e); state.allDays = false;
    // stretch the evening so the event fits, with room for dinner before it
    const at = toMin(hhmm(e.start)), role = eventStop(e).k;
    const need = role === "dinner" ? 0 : state.dinner ? 120 : 30;
    const snap = m => Math.round(m / 30) * 30;
    if (at - need < state.from) state.from = Math.max(10*60, snap(at - need - 15));
    if (at + (DUR[role] || 60) + 15 > state.to) state.to = Math.min(26*60, snap(at + (DUR[role] || 60) + 45));
  }
  state.rank = 0; state.swap = {}; state.removed = []; save(); renderForm(); renderDays(); renderPlan(); renderEvents();
  if (state.pin) $("planSec").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"start"});
}
$("events").addEventListener("click", ev => { const b = ev.target.closest(".incl"); if (b) pinEvent(b.dataset.id); });
$("pinClear").onclick = () => { state.pin = null; state.rank = 0; state.swap = {}; renderPlan(); renderEvents(); };
function ago(iso){ const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 60 ? m + " minutes ago" : m < 1440 ? Math.round(m/60) + " hours ago" : Math.round(m/1440) + " days ago"; }

// ---------- start ----------
renderForm(); renderDays(); renderPlan();
const getJSON = url => fetch(url, {cache:"no-cache"}).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
// places load alongside the events; the plan works (with fewer options) if they're missing
Promise.all([getJSON("data/restaurants.json").catch(() => null), getJSON("data/venues.json").catch(() => null), getJSON("data/activities.json").catch(() => null)]).then(([rest, ven, act]) => {
  ACTS = (act && act.activities || []).filter(a => a.lat != null);
  RESTAURANTS = (rest && rest.restaurants || []).filter(r => r.lat != null);
  BARS = (ven && ven.venues || []).filter(v => (v.kind === "bar" || v.kind === "brewery") && v.lat != null);
  enrichSpots(); renderPlan();
});
getJSON("data/events.json").then(data => {
  META = data; EVENTS = (data.events || []).filter(e => evDay(e) >= todayKey());
  $("updated").textContent = "Events updated " + ago(data.generated_at) + ". Listings refresh twice a day.";
  renderDays(); renderFilters(); renderEvents(); renderPlan();
}).catch(() => {
  $("events").innerHTML = '<p class="empty">Event listings aren\'t available right now. The plan above uses our regular spots; try again in a bit for events.</p>';
});
