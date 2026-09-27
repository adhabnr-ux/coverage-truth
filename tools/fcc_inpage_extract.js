// In-browser extractor for FCC BDC mobile-broadband H3 shapefile zips.
//
// Why: broadbandmap.fcc.gov blocks non-browser clients (Akamai), and Chrome throttles repeated
// downloads. This runs inside a normal broadbandmap.fcc.gov tab, fetches a provider/state zip,
// inflates only the .dbf, and keeps only H3 res-9 cells whose res-7 parent is in a target list.
//
// Output (per environment): a string of length K*49, one slot per res-9 child of each res-7 parent
// (slot = k*49 + d8*7 + d9); '.' = not claimed, otherwise chr(65 + (-minsignal - 50)).
// Run-length encoded as tokens "<count?><char>" (count omitted when 1). Decoder: ct/inpage.py.
//
// Usage in page:  await fccExtract(fileId, res7List)  ->  {n, hits, E0, E1, providers}

async function fccZipEntries(buf) {
  const dv = new DataView(buf);
  let eocd = buf.byteLength - 22;
  while (dv.getUint32(eocd, true) !== 0x06054b50) eocd--;
  const n = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const out = [];
  for (let i = 0; i < n; i++) {
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true);
    const usize = dv.getUint32(p + 24, true), nlen = dv.getUint16(p + 28, true);
    const xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const loff = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(new Uint8Array(buf, p + 46, nlen));
    out.push({ name, method, csize, usize, loff });
    p += 46 + nlen + xlen + clen;
  }
  return out;
}

async function fccInflate(buf, e) {
  const dv = new DataView(buf);
  const start = e.loff + 30 + dv.getUint16(e.loff + 26, true) + dv.getUint16(e.loff + 28, true);
  const data = new Uint8Array(buf, start, e.csize);
  if (e.method === 0) return data;
  const ds = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(ds).arrayBuffer());
}

function fccDbf(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset);
  const nrec = dv.getUint32(4, true), hlen = dv.getUint16(8, true), rlen = dv.getUint16(10, true);
  const fields = []; let off = 1;
  for (let p = 32; u8[p] !== 0x0d; p += 32) {
    const nm = String.fromCharCode(...u8.subarray(p, p + 11)).replace(/\0.*$/, '');
    fields.push({ nm, off, len: u8[p + 16] }); off += u8[p + 16];
  }
  return { u8, nrec, hlen, rlen, fields };
}

function fccRle(s) {
  let out = '', i = 0;
  while (i < s.length) {
    let j = i; while (j < s.length && s[j] === s[i]) j++;
    out += (j - i > 1 ? (j - i) : '') + s[i]; i = j;
  }
  return out;
}

async function fccExtract(fileId, res7List) {
  const r = await fetch(`/nbm/map/api/getNBMDataDownloadFile/${fileId}/1`);
  const buf = await r.arrayBuffer();
  const ent = (await fccZipEntries(buf)).find(e => e.name.endsWith('.dbf'));
  const D = fccDbf(await fccInflate(buf, ent));
  const F = Object.fromEntries(D.fields.map(f => [f.nm, f]));
  const key = new Map(res7List.map((id, k) => [id.slice(2, 9), k]));
  const K = res7List.length;
  const slots = { 0: new Array(K * 49).fill('.'), 1: new Array(K * 49).fill('.') };
  const txt = (rec, f) => String.fromCharCode(...D.u8.subarray(rec + f.off, rec + f.off + f.len)).trim();
  const providers = {}; let hits = 0;
  for (let i = 0; i < D.nrec; i++) {
    const rec = D.hlen + i * D.rlen;
    const h = txt(rec, F.h3_res9_id);
    const k = key.get(h.slice(2, 9));
    if (k === undefined) continue;
    const v = parseInt(h.slice(9, 11), 16), d8 = (v >> 5) & 7, d9 = (v >> 2) & 7;
    const env = F.environmnt ? parseInt(txt(rec, F.environmnt)) : 0;
    const sig = F.minsignal ? parseInt(txt(rec, F.minsignal)) : -50;
    const c = String.fromCharCode(65 + (-sig - 50));
    const slot = k * 49 + d8 * 7 + d9;
    const cur = slots[env][slot];   // keep the weakest (most generous) claimed threshold
    if (cur === '.' || c > cur) slots[env][slot] = c;
    if (F.providerid) { const p = txt(rec, F.providerid); providers[p] = (providers[p] || 0) + 1; }
    hits++;
  }
  return { n: D.nrec, hits, providers, E0: fccRle(slots[0].join('')), E1: fccRle(slots[1].join('')) };
}
