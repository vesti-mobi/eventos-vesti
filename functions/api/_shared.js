// Núcleo compartilhado das Cloudflare Functions.
// Porta a mesma lógica do servidor.py (Python) para o runtime da Cloudflare (JavaScript):
// - HubSpot: fases do pipeline, proprietários (responsáveis) e negócios (convidados)
// - Google Sheets: autenticação por conta de serviço (JWT RS256) + leitura de abas
// - Parsers de custos e do formulário de satisfação
// - Cache de borda para não abusar do HubSpot quando muita gente clica em "Atualizar"

const DEAL_PROPS = ["dealname", "dealstage", "nome_da_marca", "recusou_motivo", "hubspot_owner_id", "nome_evento", "acompanhante_de"];

// De-para de fallback (usado só se a leitura das fases do pipeline no HubSpot falhar)
const FASES_FALLBACK = {
  "161599650": "Recusou",
  "161599651": "Compareceu",
  "161599653": "Confirmou mas não compareceu",
  "1412577689": "Aguardando confirmação",
};

/* ------------------------- helpers de data (aprox. horário de Brasília, UTC-3) ------------------------- */
function nowBRT() { return new Date(Date.now() - 3 * 3600 * 1000); }
function isoDateBRT() { return nowBRT().toISOString().slice(0, 10); }
function geradoEmBRT() {
  const d = nowBRT();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
const round2 = (x) => Math.round(x * 100) / 100;

/* ------------------------- HubSpot ------------------------- */
function hsHeaders(token) {
  return { Authorization: "Bearer " + token, "Content-Type": "application/json" };
}
async function hsJson(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    const e = new Error(`HubSpot respondeu ${r.status}`);
    e.status = r.status;
    e.body = body;
    throw e;
  }
  return r.json();
}

async function fetchStageMap(token, pipelineId) {
  try {
    const d = await hsJson(`https://api.hubapi.com/crm/v3/pipelines/deals/${pipelineId}`, { headers: hsHeaders(token) });
    const m = {};
    for (const s of d.stages || []) m[s.id] = s.label;
    return Object.keys(m).length ? m : { ...FASES_FALLBACK };
  } catch {
    return { ...FASES_FALLBACK };
  }
}

async function fetchOwners(token) {
  const owners = {};
  let after = null;
  do {
    let url = "https://api.hubapi.com/crm/v3/owners/?limit=100";
    if (after) url += "&after=" + after;
    const d = await hsJson(url, { headers: hsHeaders(token) });
    for (const o of d.results || []) {
      const nome = `${o.firstName || ""} ${o.lastName || ""}`.trim() || o.email || `Owner ${o.id}`;
      owners[String(o.id)] = nome;
    }
    after = d.paging && d.paging.next ? d.paging.next.after : null;
  } while (after);
  return owners;
}

async function fetchDeals(token, pipelineId) {
  const url = "https://api.hubapi.com/crm/v3/objects/deals/search";
  const results = [];
  let after = null;
  do {
    const body = {
      filterGroups: [{ filters: [{ propertyName: "pipeline", operator: "EQ", value: String(pipelineId) }] }],
      properties: DEAL_PROPS,
      limit: 100,
    };
    if (after) body.after = after;
    const d = await hsJson(url, { method: "POST", headers: hsHeaders(token), body: JSON.stringify(body) });
    results.push(...(d.results || []));
    after = d.paging && d.paging.next ? d.paging.next.after : null;
  } while (after);
  return results;
}

/* ------------------------- Google (conta de serviço -> access token) ------------------------- */
function b64urlFromBytes(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlFromString(str) {
  return b64urlFromBytes(new TextEncoder().encode(str));
}
function pemToArrayBuffer(pem) {
  const b64 = pem.replace(/-----BEGIN [^-]+-----/, "").replace(/-----END [^-]+-----/, "").replace(/\s+/g, "");
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

// Aceita a conta de serviço como JSON puro ou como base64 (facilita colar o secret na Cloudflare).
function parseServiceAccount(v) {
  if (typeof v !== "string") return v;
  const s = v.trim();
  return JSON.parse(s.startsWith("{") ? s : atob(s));
}

async function getGoogleToken(saJson) {
  const sa = parseServiceAccount(saJson);
  const now = Math.floor(Date.now() / 1000);
  const aud = sa.token_uri || "https://oauth2.googleapis.com/token";
  const header = { alg: "RS256", typ: "JWT" };
  const claims = {
    iss: sa.client_email,
    scope: "https://www.googleapis.com/auth/spreadsheets.readonly",
    aud,
    iat: now,
    exp: now + 3600,
  };
  const signingInput = `${b64urlFromString(JSON.stringify(header))}.${b64urlFromString(JSON.stringify(claims))}`;
  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToArrayBuffer(sa.private_key),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(signingInput));
  const jwt = `${signingInput}.${b64urlFromBytes(new Uint8Array(sig))}`;
  const resp = await fetch(aud, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: jwt }),
  });
  const data = await resp.json();
  if (!data.access_token) throw new Error("Falha ao autenticar no Google: " + JSON.stringify(data).slice(0, 300));
  return data.access_token;
}

async function sheetTitles(token, sheetId) {
  const r = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}?fields=sheets.properties.title`, {
    headers: { Authorization: "Bearer " + token },
  });
  const d = await r.json();
  if (d.error) throw new Error(d.error.message || "erro na API do Google Sheets");
  return (d.sheets || []).map((s) => s.properties.title);
}
async function sheetValues(token, sheetId, title) {
  const r = await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${encodeURIComponent(title)}`,
    { headers: { Authorization: "Bearer " + token } },
  );
  const d = await r.json();
  if (d.error) throw new Error(d.error.message || "erro ao ler a aba");
  return d.values || [];
}

/* ------------------------- parsers ------------------------- */
function parseMoney(s) {
  s = String(s == null ? "" : s).trim().replace(/R\$/g, "").replace(/ /g, " ").trim();
  if (!s || s === "-" || s === "—") return 0;
  s = s.replace(/\./g, "").replace(/,/g, ".").replace(/[^0-9.\-]/g, "");
  if (s === "" || s === "." || s === "-") return 0;
  const n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}
function parseIntBR(s) {
  const cleaned = String(s == null ? "" : s).replace(/[^0-9\-]/g, "");
  const n = parseInt(cleaned || "0", 10);
  return isNaN(n) ? 0 : n;
}

function parseCostRows(rows) {
  rows = rows.map((row) => row.map((c) => String(c == null ? "" : c)));
  const headerIdx = rows.findIndex((row) => row.some((c) => c.trim().toLowerCase() === "categoria gasto"));
  if (headerIdx < 0) return {};
  const header = rows[headerIdx].map((c) => c.trim());
  const col = (...names) => {
    for (const name of names) {
      const j = header.findIndex((h) => h.toLowerCase() === name.toLowerCase());
      if (j >= 0) return j;
    }
    return null;
  };
  const idx = {
    item: col("Item"),
    obs: col("Observação / Fornecedor", "Observação", "Observações"),
    qtd: col("Qtd"),
    unit: col("Custo unit.", "Custo unit"),
    total: col("Total"),
    status: col("Status"),
    nome: col("Nome evento"),
    local: col("Local evento"),
    data: col("Data evento"),
    categoria: col("Categoria gasto"),
  };
  const val = (row, key) => {
    const j = idx[key];
    return j != null && j < row.length ? row[j].trim() : "";
  };
  const eventos = {};
  for (const row of rows.slice(headerIdx + 1)) {
    if (!row.some((c) => c.trim())) continue;
    const item = val(row, "item");
    const nomeEv = val(row, "nome");
    if (!item || !nomeEv) continue;
    const ev = (eventos[nomeEv] = eventos[nomeEv] || { local: "", data: "", itens: [] });
    ev.local = ev.local || val(row, "local");
    ev.data = ev.data || val(row, "data");
    ev.itens.push({
      item,
      obs: val(row, "obs"),
      qtd: parseIntBR(val(row, "qtd")),
      unit: parseMoney(val(row, "unit")),
      total: parseMoney(val(row, "total")),
      status: val(row, "status"),
      categoria: val(row, "categoria") || "Outros",
    });
  }
  for (const ev of Object.values(eventos)) ev.total = round2(ev.itens.reduce((s, i) => s + i.total, 0));
  return eventos;
}

function parseSatisfacaoRows(rows) {
  rows = rows.map((row) => row.map((c) => String(c == null ? "" : c)));
  if (!rows.length) return [];
  const header = rows[0].map((c) => c.trim());
  const idx = {};
  header.forEach((h, i) => { if (!(h in idx)) idx[h] = i; });
  const g = (row, key) => {
    const j = idx[key];
    return j != null && j < row.length ? row[j].trim() : "";
  };
  const toInt = (s) => {
    const n = parseInt(String(s).replace(/[^0-9\-]/g, ""), 10);
    return isNaN(n) ? null : n;
  };
  const ANON = ["", "anônimo", "anonimo"];
  const out = [];
  for (const row of rows.slice(1)) {
    if (!row.some((c) => c.trim())) continue;
    const marca = g(row, "brand_name");
    const nome = g(row, "name_people");
    const autor = !ANON.includes(marca.toLowerCase()) ? marca : (!ANON.includes(nome.toLowerCase()) ? nome : "Anônimo");
    out.push({
      event_name: g(row, "event_name"),
      score: toInt(g(row, "score")),
      score_reason: g(row, "score_reason"),
      talk_rating: toInt(g(row, "talk_rating")),
      talk_relevance: g(row, "talk_relevance"),
      restaurant_rating: toInt(g(row, "restaurant_rating")),
      schedule_ok: g(row, "schedule_ok"),
      favorite_part: g(row, "favorite_part"),
      improvements: g(row, "improvements"),
      next_event: g(row, "next_event"),
      autor,
      created_at: g(row, "created_at"),
    });
  }
  return out;
}

async function fetchSheetCosts(token, sheetId) {
  for (const title of await sheetTitles(token, sheetId)) {
    const eventos = parseCostRows(await sheetValues(token, sheetId, title));
    if (Object.keys(eventos).length) return eventos;
  }
  return {};
}

// Aba "Funcionários participantes" (colunas Name + event_name): funcionários da Vesti por evento.
async function fetchSheetFuncionarios(token, sheetId) {
  const title = (await sheetTitles(token, sheetId)).find((t) => /funcion/i.test(t));
  if (!title) return {};
  const rows = (await sheetValues(token, sheetId, title)).map((r) => r.map((c) => String(c == null ? "" : c)));
  if (rows.length < 2) return {};
  const header = rows[0].map((c) => c.trim().toLowerCase());
  let ni = header.findIndex((h) => h === "name" || h === "nome");
  let ei = header.findIndex((h) => h === "event_name" || h.includes("evento"));
  if (ni < 0) ni = 0;
  if (ei < 0) ei = 1;
  const out = {};
  for (const row of rows.slice(1)) {
    const nome = (row[ni] || "").trim();
    const ev = (row[ei] || "").trim();
    if (!nome || !ev) continue;
    (out[ev] = out[ev] || []).push(nome);
  }
  return out;
}

/* ------------------------- montagem final ------------------------- */
export async function buildDados(env) {
  const token = env.HUBSPOT_TOKEN;
  if (!token) throw new Error("HUBSPOT_TOKEN não configurado.");
  const pipelineId = String(env.PIPELINE_ID || "86720772");

  const [stageMap, owners, deals] = [await fetchStageMap(token, pipelineId), await fetchOwners(token), await fetchDeals(token, pipelineId)];

  let costs = {};
  let funcs = {};
  if (env.GOOGLE_SERVICE_ACCOUNT && env.SHEET_ID) {
    try {
      const gtoken = await getGoogleToken(env.GOOGLE_SERVICE_ACCOUNT);
      costs = await fetchSheetCosts(gtoken, env.SHEET_ID);
      funcs = await fetchSheetFuncionarios(gtoken, env.SHEET_ID);
    } catch (e) {
      // se a planilha falhar, segue sem custos/funcionários (não derruba a presença)
      console.log("aviso: falha ao ler a planilha:", e.message);
    }
  }

  const porEvento = {};
  for (const d of deals) {
    const p = d.properties || {};
    const nomeEv = (p.nome_evento || "").trim();
    if (!nomeEv) continue;
    const item = {
      n: p.dealname || "(sem nome)",
      m: p.nome_da_marca || "",
      f: stageMap[String(p.dealstage || "")] || "Outros",
      r: owners[String(p.hubspot_owner_id || "")] || "Sem responsável",
    };
    const mot = (p.recusou_motivo || "").trim();
    if (mot) item.mot = mot;
    const ac = (p.acompanhante_de || "").trim();
    if (ac) item.ac = ac;   // preenchido só quando o deal é um acompanhante
    (porEvento[nomeEv] = porEvento[nomeEv] || []).push(item);
  }

  const hoje = isoDateBRT();
  const nomes = new Set([...Object.keys(porEvento), ...Object.keys(costs), ...Object.keys(funcs)]);
  const eventos = [];
  for (const nome of nomes) {
    const c = costs[nome] || {};
    const itens = c.itens || [];
    const total = c.total != null ? c.total : round2(itens.reduce((s, i) => s + (i.total || 0), 0));
    eventos.push({
      nome,
      local: c.local || "",
      data_evento: c.data || "",
      atualizado_em: hoje,
      custos: { total, itens },
      deals: porEvento[nome] || [],
      funcionarios: funcs[nome] || [],
    });
  }
  eventos.sort((a, b) => b.deals.length - a.deals.length);
  return { eventos, gerado_em: geradoEmBRT() };
}

export async function fetchSatisfacao(env) {
  if (!env.GOOGLE_SERVICE_ACCOUNT || !env.SHEET_ID) {
    throw new Error("Configure GOOGLE_SERVICE_ACCOUNT e SHEET_ID.");
  }
  const token = await getGoogleToken(env.GOOGLE_SERVICE_ACCOUNT);
  const title = (await sheetTitles(token, env.SHEET_ID)).find((t) => t.toLowerCase().includes("satisfa"));
  if (!title) throw new Error("Aba 'Formulário de satisfação' não encontrada na planilha.");
  const respostas = parseSatisfacaoRows(await sheetValues(token, env.SHEET_ID, title));
  return { evento: respostas.length ? respostas[0].event_name : "", gerado_em: geradoEmBRT(), respostas };
}

/* ------------------------- resposta + cache de borda ------------------------- */
export async function withCache(context, maxAgeSeconds, compute) {
  const { request } = context;
  const url = new URL(request.url);
  const bypass = url.searchParams.has("fresh"); // o botão "Atualizar" pede sempre dados novos (ignora o cache)
  const cache = caches.default;
  // chave sem query: um clique "fresh" também aquece o cache para os acessos normais seguintes
  const cacheKey = new Request(url.origin + url.pathname, { method: "GET" });

  if (!bypass) {
    const hit = await cache.match(cacheKey);
    if (hit) return hit;
  }

  const cors = { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" };
  try {
    const data = await compute();
    const resp = new Response(JSON.stringify(data), {
      headers: { ...cors, "Cache-Control": `public, max-age=${maxAgeSeconds}` },
    });
    context.waitUntil(cache.put(cacheKey, resp.clone()));
    return resp;
  } catch (e) {
    const status = e.status === 401 || e.status === 403 ? 502 : 503;
    return new Response(JSON.stringify({ erro: String(e.message || e) }), {
      status,
      headers: { ...cors, "Cache-Control": "no-store" },
    });
  }
}
