/**
 * TestPro — Vercel Edge Proxy (Supabase versiyasi)
 * ==================================================
 * Eski versiyada BARCHA so'rovlar Telegram Storage Channel
 * orqali o'tirdi (getIndex → pin → forward → readFileId).
 * Bu versiyada esa to'g'ridan-to'g'ri Supabase PostgREST
 * API ga murojaat qilinadi — tezroq, ishonchli, limitsiz.
 *
 * Frontend (web_test.html, edit.html, dashboard.html) uchun
 * endpoint nomlar O'ZGARMADI — faqat ichki implementatsiya
 * Telegram'dan Supabase'ga ko'chirildi.
 *
 * Vercel env vars:
 *   SUPABASE_URL       = "https://xxxx.supabase.co"
 *   SUPABASE_KEY       = "sb_secret_..."   ← service_role
 *   BOT_TOKEN          = "123:ABC..."
 *   STREAMLIT_URL      = "https://..."
 *   ADMIN_IDS          = "123456789,987654321"
 *   ADMIN_PASSWORD     = "parol"
 */

export const config = { runtime: 'edge' };

const SUPABASE_URL  = process.env.SUPABASE_URL  || '';
const SUPABASE_KEY  = process.env.SUPABASE_KEY  || '';
const BOT_TOKEN     = process.env.BOT_TOKEN      || '';
const STREAMLIT_URL = process.env.STREAMLIT_URL  || '';
const ADMIN_IDS     = (process.env.ADMIN_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
const ADMIN_PASS    = process.env.ADMIN_PASSWORD || 'admin123';
const TG            = `https://api.telegram.org/bot${BOT_TOKEN}`;

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-TG-ID',
};

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

// ════════════════════════════════════════════════════════════════
// SUPABASE REST YORDAMCHILARI
// ════════════════════════════════════════════════════════════════

const SB_HEADERS = {
  'apikey':        SUPABASE_KEY,
  'Authorization': `Bearer ${SUPABASE_KEY}`,
  'Content-Type':  'application/json',
  'Prefer':        'return=representation',
};

async function sbSelect(table, params = {}) {
  /** Supabase PostgREST GET so'rovi */
  const url = new URL(`${SUPABASE_URL}/rest/v1/${table}`);
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }
  const res = await fetch(url.toString(), { headers: SB_HEADERS });
  if (!res.ok) throw new Error(`sbSelect ${table}: ${res.status}`);
  return res.json();
}

async function sbSelectOne(table, col, val, columns = '*') {
  const rows = await sbSelect(table, { select: columns, [col]: `eq.${val}`, limit: 1 });
  return (rows && rows.length) ? rows[0] : null;
}

async function sbUpsert(table, row) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${table}`, {
    method: 'POST',
    headers: { ...SB_HEADERS, 'Prefer': 'resolution=merge-duplicates,return=representation' },
    body: JSON.stringify(row),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`sbUpsert ${table}: ${res.status} ${err}`);
  }
  return res.json();
}

async function sbUpdate(table, col, val, patch) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${col}=eq.${encodeURIComponent(val)}`, {
    method: 'PATCH',
    headers: SB_HEADERS,
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`sbUpdate ${table}: ${res.status} ${err}`);
  }
  return res.json();
}

async function sbDelete(table, col, val) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${col}=eq.${encodeURIComponent(val)}`, {
    method: 'DELETE',
    headers: SB_HEADERS,
  });
  if (!res.ok) throw new Error(`sbDelete ${table}: ${res.status}`);
  return true;
}

// ════════════════════════════════════════════════════════════════
// FORMAT KONVERTATSIYA (o'zgarmadi — frontend bilan moslik)
// ════════════════════════════════════════════════════════════════

function botToWeb(q, idx) {
  const opts = (q.options || []).map(String);
  const typeMap = { multiple_choice: 'multiple', true_false: 'truefalse', truefalse: 'truefalse', multiple: 'multiple' };
  let correctIdx = 0;
  if (typeof q.correct === 'number') {
    correctIdx = q.correct;
  } else if (typeof q.correct === 'string') {
    const m = q.correct.match(/^([A-H])\s*[).]/i);
    if (m) {
      correctIdx = m[1].toUpperCase().charCodeAt(0) - 65;
    } else {
      const ci = opts.findIndex(o =>
        o === q.correct ||
        o.includes(q.correct) ||
        q.correct.includes(o.replace(/^[A-H][).] */, ''))
      );
      correctIdx = ci >= 0 ? ci : 0;
    }
  }
  return {
    type:        typeMap[q.type] || q.type || 'multiple',
    text:        q.text || q.question || '',
    question:    q.text || q.question || '',
    options:     opts,
    correct:     correctIdx,
    explanation: q.explanation || '',
    points:      q.points || 1,
    poll_time:   q.poll_time || 30,
    photo:       q.photo || null,
    image:       q.image || null,
  };
}

function webToBot(q) {
  const opts   = (q.options || []).map(String);
  const labels = ['A','B','C','D','E','F','G','H'];
  const fmtOpts = opts.map((o, i) => {
    const lbl = labels[i] || String.fromCharCode(65 + i);
    return /^[A-H]\s*[).]/.test(o) ? o : `${lbl}) ${o}`;
  });
  let correctStr = '';
  if (typeof q.correct === 'number') {
    correctStr = fmtOpts[q.correct] || fmtOpts[0] || '';
  } else if (typeof q.correct === 'string') {
    correctStr = q.correct;
  }
  const typeMap = { multiple: 'multiple_choice', truefalse: 'true_false', 'true_false': 'true_false', multiple_choice: 'multiple_choice' };
  const photoId = q.photo || q.image || null;
  const result = {
    type:        typeMap[q.type] || q.type || 'multiple_choice',
    question:    q.question || q.text || '',
    options:     fmtOpts,
    correct:     correctStr,
    explanation: q.explanation || '',
    points:      q.points || 1,
    poll_time:   q.poll_time || 30,
  };
  if (photoId && !photoId.startsWith('data:')) result.photo = photoId;
  return result;
}

function normMeta(t) {
  const out = { ...t };
  delete out.questions;
  out.id             = out.id            || out.test_id;
  out.test_id        = out.test_id       || out.id;
  out.authorId       = out.authorId      || String(out.creator_id || '');
  out.subject        = out.subject       || out.category  || 'other';
  out.category       = out.category      || out.subject   || 'other';
  out.creator_name   = out.creator_name  || out.authorName || '';
  out.is_active      = out.is_active     !== false;
  out.is_paused      = out.is_paused     || false;
  out.question_count = out.question_count || out.questionCount || 0;
  out.passing_score  = parseInt(out.passing_score || out.passScore || 60);
  out.time_limit     = parseInt(out.time_limit    || out.timeLimit  || 0);
  out.max_attempts   = parseInt(out.max_attempts  || 0);
  out.ref_required   = !!(out.ref_required || false);
  out.ref_count      = parseInt(out.ref_count || 0);
  out.shuffle_questions = !!(out.shuffle_questions || out.shuffleQuestions || false);
  return out;
}

// ════════════════════════════════════════════════════════════════
// TELEGRAM (faqat rasmlar va foydalanuvchi ma'lumoti uchun)
// ════════════════════════════════════════════════════════════════

async function tgPost(method, body) {
  const res = await fetch(`${TG}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function getPhotoUrl(fileId) {
  if (!fileId || typeof fileId !== 'string') return null;
  try {
    const f = await tgPost('getFile', { file_id: fileId });
    const p = f?.result?.file_path;
    return p ? `https://api.telegram.org/file/bot${BOT_TOKEN}/${p}` : null;
  } catch { return null; }
}

// ════════════════════════════════════════════════════════════════
// UNIQUE ID GENERATOR
// ════════════════════════════════════════════════════════════════

function genTid() {
  return Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase();
}

// ════════════════════════════════════════════════════════════════
// HANDLER
// ════════════════════════════════════════════════════════════════

export default async function handler(request) {
  if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });

  const url = new URL(request.url);
  const ep  = url.searchParams.get('endpoint') || '';

  let body = null;
  if (request.method === 'POST') {
    try { body = await request.json(); } catch {}
  }

  // ── config ────────────────────────────────────────────────────
  if (ep === 'config') {
    return jsonResp({
      streamlit_url: STREAMLIT_URL || '',
      backend:       'supabase',
    });
  }

  // ── debug ─────────────────────────────────────────────────────
  if (ep === 'debug') {
    let dbOk = false;
    let testCount = 0;
    try {
      const rows = await sbSelect('tests', { select: 'test_id', limit: 1 });
      dbOk = true;
      const cnt = await sbSelect('tests', { select: 'test_id' });
      testCount = cnt.length;
    } catch {}
    return jsonResp({
      backend:         'supabase',
      supabase_url:    SUPABASE_URL ? SUPABASE_URL.slice(0, 30) + '...' : 'NOT SET',
      supabase_key:    SUPABASE_KEY ? 'SET (' + SUPABASE_KEY.slice(0, 12) + '...)' : 'NOT SET',
      db_ok:           dbOk,
      test_count:      testCount,
      streamlit_url:   STREAMLIT_URL || 'not_set',
      bot_token_set:   !!BOT_TOKEN,
    });
  }

  // ── tests/public ──────────────────────────────────────────────
  if (ep === 'tests/public') {
    try {
      const rows = await sbSelect('tests', {
        select: 'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score',
        is_active: 'eq.true',
        is_paused: 'eq.false',
        order:     'created_at.desc',
      });
      const result = rows
        .filter(r => {
          const m = r.meta || {};
          return m.visibility === 'public' || m.visibility == null;
        })
        .map(r => normMeta({ ...(r.meta || {}), test_id: r.test_id, title: r.title,
          question_count: r.question_count, solve_count: r.solve_count,
          avg_score: r.avg_score, is_active: r.is_active, is_paused: r.is_paused }));
      return jsonResp(result);
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── tests/my ──────────────────────────────────────────────────
  if (ep === 'tests/my') {
    const uid = url.searchParams.get('uid') || '';
    if (!uid) return jsonResp([]);
    try {
      const rows = await sbSelect('tests', {
        select:    'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score',
        is_active: 'eq.true',
        order:     'created_at.desc',
      });
      const mine = rows
        .filter(r => String((r.meta || {}).creator_id || '') === uid)
        .map(r => normMeta({ ...(r.meta || {}), test_id: r.test_id, title: r.title,
          question_count: r.question_count, solve_count: r.solve_count,
          avg_score: r.avg_score, is_active: r.is_active, is_paused: r.is_paused }));
      return jsonResp(mine);
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/full ────────────────────────────────────────────
  if (ep.startsWith('test/') && ep.endsWith('/full')) {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid);
      if (!row) return jsonResp({ error: `Test topilmadi: ${tid}` }, 404);

      const meta = normMeta({ ...(row.meta || {}), test_id: row.test_id,
        title: row.title, question_count: row.question_count,
        solve_count: row.solve_count, avg_score: row.avg_score,
        is_active: row.is_active, is_paused: row.is_paused });

      const webQs = (row.questions || []).map((q, i) => botToWeb(q, i));
      return jsonResp({ testData: meta, questions: webQs, total: webQs.length });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/meta ────────────────────────────────────────────
  if (ep.startsWith('test/') && ep.endsWith('/meta')) {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid,
        'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score');
      if (!row) return jsonResp({ error: 'Topilmadi' }, 404);
      return jsonResp(normMeta({ ...(row.meta || {}), test_id: row.test_id,
        title: row.title, question_count: row.question_count }));
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id} bare GET ────────────────────────────────────────
  if (ep.match(/^test\/[^/]+$/) && request.method === 'GET') {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid,
        'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score');
      if (!row) return jsonResp({ error: 'Topilmadi' }, 404);
      return jsonResp(normMeta({ ...(row.meta || {}), test_id: row.test_id,
        title: row.title, question_count: row.question_count }));
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/create ───────────────────────────────────────────────
  if (ep === 'test/create' && request.method === 'POST') {
    const {
      authorId, title, description, subject, category, visibility,
      timeLimit, passScore, shuffleQuestions, showResult,
      authorName, questions, difficulty, poll_time, max_attempts,
    } = body || {};
    if (!title) return jsonResp({ error: 'Title kerak' }, 400);
    const tid = genTid();
    const qs  = (questions || []).map(q => webToBot(q));
    const meta = {
      creator_id:       parseInt(authorId) || 0,
      creator_name:     authorName || '',
      category:         category || subject || 'Boshqa',
      difficulty:       difficulty || 'medium',
      visibility:       visibility || 'public',
      time_limit:       parseInt(timeLimit) || 0,
      poll_time:        parseInt(poll_time) || 30,
      passing_score:    parseInt(passScore) || 60,
      max_attempts:     parseInt(max_attempts) || 0,
      description:      description || '',
      shuffle_questions: !!shuffleQuestions,
      show_result:       showResult !== false,
      source:            'web',
      created_at:        new Date().toISOString(),
    };
    try {
      await sbUpsert('tests', {
        test_id:        tid,
        title:          title,
        questions:      qs,
        meta:           meta,
        question_count: qs.length,
        is_active:      true,
        is_paused:      false,
        solve_count:    0,
        avg_score:      0,
      });
      return jsonResp({ ok: true, id: tid, test_id: tid });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/questions GET ───────────────────────────────────
  if (ep.match(/^test\/[^/]+\/questions$/) && request.method === 'GET') {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid, 'questions');
      const webQs = (row?.questions || []).map((q, i) => botToWeb(q, i));
      return jsonResp(webQs);
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/questions POST (tahrirlash) ─────────────────────
  if (ep.match(/^test\/[^/]+\/questions$/) && request.method === 'POST') {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid, 'test_id,meta,question_count');
      if (!row) return jsonResp({ error: 'Test topilmadi' }, 404);
      const oldQc = row.question_count || 0;

      const qs = (body?.questions || []).map(q => webToBot(q));
      await sbUpdate('tests', 'test_id', tid, {
        questions:      qs,
        question_count: qs.length,
        meta:           { ...(row.meta || {}), updated_at: new Date().toISOString() },
      });
      // Bot ga xabar (ixtiyoriy — botda WEB_CMD handler o'chirilgan, faqat log uchun)
      const creatorId = (row.meta || {}).creator_id;
      if (creatorId && BOT_TOKEN) {
        tgPost('sendMessage', {
          chat_id: creatorId,
          text:    `✏️ Test yangilandi: <code>${tid}</code>\n📋 ${oldQc} → ${qs.length} ta savol`,
          parse_mode: 'HTML',
        }).catch(() => {});
      }
      return jsonResp({ ok: true, count: qs.length, old_count: oldQc });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/update POST (meta yangilash) ────────────────────
  if (ep.match(/^test\/[^/]+\/update$/) && request.method === 'POST') {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid, 'test_id,meta');
      if (!row) return jsonResp({ error: 'Test topilmadi' }, 404);
      const allowed = ['title','category','difficulty','visibility','time_limit',
        'poll_time','passing_score','max_attempts','is_active','shuffle_questions',
        'show_result','ref_required','ref_count'];
      const updates  = {};
      const metaPatch = { ...(row.meta || {}) };
      for (const k of allowed) {
        if (body && k in body) {
          updates[k] = body[k];
          metaPatch[k] = body[k];
        }
      }
      const dbPatch = { meta: metaPatch };
      if ('title' in updates)     dbPatch.title     = updates.title;
      if ('is_active' in updates) dbPatch.is_active = updates.is_active;
      if ('is_paused' in updates) dbPatch.is_paused = updates.is_paused;
      await sbUpdate('tests', 'test_id', tid, dbPatch);
      return jsonResp({ ok: true, updates });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/delete POST ────────────────────────────────────
  if (ep.match(/^test\/[^/]+\/delete$/) && request.method === 'POST') {
    const tid = ep.split('/')[1];
    try {
      // Soft delete — is_active=false
      await sbUpdate('tests', 'test_id', tid, { is_active: false });
      return jsonResp({ ok: true, deleted: tid });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── test/{id}/split POST ─────────────────────────────────────
  if (ep.match(/^test\/[^/]+\/split$/) && request.method === 'POST') {
    const tid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid, '*');
      if (!row) return jsonResp({ error: 'Test topilmadi' }, 404);
      const allQs = row.questions || [];
      if (!allQs.length) return jsonResp({ error: 'Savollar topilmadi' }, 404);

      const { parts } = body || {};
      if (!parts || !parts.length) return jsonResp({ error: 'parts kerak' }, 400);

      const D = {'0':'0️⃣','1':'1️⃣','2':'2️⃣','3':'3️⃣','4':'4️⃣',
                 '5':'5️⃣','6':'6️⃣','7':'7️⃣','8':'8️⃣','9':'9️⃣'};
      function numEmoji(n) {
        if (n === 10) return '🔟';
        if (n === 100) return '💯';
        return String(n).split('').map(c => D[c] || c).join('');
      }

      const meta = row.meta || {};
      const created = [];
      for (const p of parts) {
        const chunk = allQs.slice(p.from - 1, p.to);
        if (!chunk.length) continue;
        const newTid   = genTid();
        const partTitle = `${row.title} ${numEmoji(p.from)}➖${numEmoji(p.to)}`;
        const newMeta  = { ...meta, source: 'web_split', created_at: new Date().toISOString() };
        await sbUpsert('tests', {
          test_id:        newTid,
          title:          partTitle,
          questions:      chunk,
          meta:           newMeta,
          question_count: chunk.length,
          is_active:      true,
          is_paused:      false,
          solve_count:    0,
          avg_score:      0,
        });
        created.push({ tid: newTid, title: partTitle, count: chunk.length });
      }
      if (!created.length) return jsonResp({ error: 'Hech qaysi qism saqlanmadi' }, 500);
      return jsonResp({ ok: true, created });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── photo/stream ──────────────────────────────────────────────
  if (ep === 'photo/stream') {
    const fid = url.searchParams.get('fid');
    if (!fid) return new Response('fid kerak', { status: 400 });
    const photoUrl = await getPhotoUrl(fid);
    if (!photoUrl) return new Response('Topilmadi', { status: 404 });
    return Response.redirect(photoUrl, 302);
  }

  // ── photo/url POST ────────────────────────────────────────────
  if (ep === 'photo/url' && request.method === 'POST') {
    const { file_id } = body || {};
    if (!file_id) return jsonResp({ error: 'file_id kerak' }, 400);
    const photoUrl = await getPhotoUrl(file_id);
    if (!photoUrl) return jsonResp({ error: 'URL topilmadi' }, 404);
    return jsonResp({ ok: true, url: photoUrl });
  }

  // ── photo/upload POST ─────────────────────────────────────────
  if (ep === 'photo/upload' && request.method === 'POST') {
    const { image_b64, filename } = body || {};
    if (!image_b64) return jsonResp({ error: 'image_b64 kerak' }, 400);

    // Supabase Storage da saqlash
    if (SUPABASE_URL && SUPABASE_KEY) {
      try {
        const b64data = image_b64.replace(/^data:image\/\w+;base64,/, '');
        const mime    = image_b64.startsWith('data:image/png') ? 'image/png'
                      : image_b64.startsWith('data:image/gif') ? 'image/gif'
                      : 'image/jpeg';
        const ext  = mime.split('/')[1];
        const name = filename || `photo_${Date.now()}.${ext}`;
        const binaryStr = atob(b64data);
        const bytes     = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

        const uploadRes = await fetch(
          `${SUPABASE_URL}/storage/v1/object/quiz-images/${name}`,
          {
            method:  'POST',
            headers: {
              'Authorization':  `Bearer ${SUPABASE_KEY}`,
              'Content-Type':   mime,
              'x-upsert':       'true',
            },
            body: bytes,
          }
        );
        if (!uploadRes.ok) throw new Error(await uploadRes.text());
        const pubUrl = `${SUPABASE_URL}/storage/v1/object/public/quiz-images/${name}`;
        return jsonResp({ ok: true, file_id: pubUrl, url: pubUrl });
      } catch (e) {
        return jsonResp({ error: 'Storage xato: ' + String(e) }, 500);
      }
    }

    // Fallback: Telegram ga yuklash (kanal bo'lsa)
    if (!BOT_TOKEN) return jsonResp({ error: 'Rasm yuklash sozlanmagan' }, 500);
    try {
      const b64data = image_b64.replace(/^data:image\/\w+;base64,/, '');
      const mime    = image_b64.startsWith('data:image/png') ? 'image/png' : 'image/jpeg';
      const ext     = mime.split('/')[1];
      const name    = filename || `photo_${Date.now()}.${ext}`;
      const binaryStr = atob(b64data);
      const bytes     = new Uint8Array(binaryStr.length);
      for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
      const blob = new Blob([bytes], { type: mime });
      // Adminga yuborish (chat_id = birinchi admin)
      const adminId = ADMIN_IDS[0];
      if (!adminId) return jsonResp({ error: 'ADMIN_IDS sozlanmagan' }, 500);
      const form = new FormData();
      form.append('chat_id', adminId);
      form.append('photo', blob, name);
      form.append('disable_notification', 'true');
      const res  = await fetch(`${TG}/sendPhoto`, { method: 'POST', body: form });
      const data = await res.json();
      if (!data?.ok) return jsonResp({ error: 'TG xato: ' + data?.description }, 500);
      const photos  = data.result.photo || [];
      const biggest = photos[photos.length - 1];
      return jsonResp({ ok: true, file_id: biggest?.file_id || '', message_id: data.result.message_id });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── result/save POST ──────────────────────────────────────────
  if (ep === 'result/save' && request.method === 'POST') {
    const {
      userId, user_id, testId, testTitle, subject,
      userName, user_name, userUsername, user_username,
      score, correct, total, percentage, passing_score, passed,
      elapsed, detailed_results, userAnswers, completedAt, source,
    } = body || {};

    const finalUid   = String(userId || user_id || '0');
    const finalName  = userName || user_name || ('User' + finalUid);
    const finalUname = userUsername || user_username || '';
    if (!finalUid || finalUid === '0' || !testId) {
      return jsonResp({ error: 'userId va testId kerak' });
    }

    const pct = parseFloat(percentage || score || 0);
    const ps  = parseFloat(passing_score || 60);

    try {
      // user_stats jadvalida saqlaymiz — bot bilan BIR XIL formatda:
      // data = { tid: {attempts, all_pcts, best_score, avg_score, last_at, passed, ever_passed, ever_completed} }
      // (by_test wrapper ISHLATILMAYDI — bot tomoni ham to'g'ridan-to'g'ri shu strukturada yozadi)
      const tg_id = parseInt(finalUid) || 0;
      let existing = null;
      if (tg_id) {
        existing = await sbSelectOne('user_stats', 'tg_id', tg_id);
      }
      const statsData = existing?.data || {};
      const e = statsData[testId] || { attempts: 0, all_pcts: [], best_score: 0, ever_passed: false, ever_completed: false };

      const attempts   = (e.attempts || 0) + 1;
      const all_pcts   = [...(e.all_pcts || []), pct];
      const best_score = Math.max(e.best_score || 0, pct);
      const avg_score  = Math.round(all_pcts.reduce((a,b) => a+b, 0) / all_pcts.length * 10) / 10;
      const this_passed = passed !== undefined ? !!passed : (pct >= ps);

      statsData[testId] = {
        attempts,
        all_pcts,
        best_score,
        avg_score,
        last_at:         completedAt || new Date().toISOString(),
        passed:          this_passed,
        ever_passed:     (e.ever_passed || false) || this_passed,
        ever_completed:  (e.ever_completed || false) || true,
      };

      if (tg_id) {
        await sbUpsert('user_stats', { tg_id, data: statsData });
        // Foydalanuvchi ro'yxatga qo'shish (yangi bo'lsa)
        await sbUpsert('users', {
          tg_id,
          data: { name: finalName, username: finalUname },
          is_blocked: false,
        });
      }

      // Test statistikasini yangilash
      const testRow = await sbSelectOne('tests', 'test_id', testId, 'solve_count,avg_score');
      if (testRow) {
        const sc  = (testRow.solve_count || 0) + 1;
        const avg = Math.round(((testRow.avg_score || 0) * (sc - 1) + pct) / sc * 10) / 10;
        await sbUpdate('tests', 'test_id', testId, { solve_count: sc, avg_score: avg });
      }

      return jsonResp({ ok: true, result_id: `${finalUid}_${testId}_${Date.now()}` });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── user/{uid} ────────────────────────────────────────────────
  if (ep.startsWith('user/') && ep.split('/').length === 2) {
    const uid = ep.split('/')[1];
    if (!/^\d+$/.test(uid)) return jsonResp({ error: "Noto'g'ri ID" }, 400);
    try {
      const res = await tgPost('getChat', { chat_id: parseInt(uid) });
      if (!res?.ok) return jsonResp({ error: 'Topilmadi' }, 404);
      const u = res.result;
      return jsonResp({
        id:       String(u.id),
        uid:      String(u.id),
        name:     [u.first_name, u.last_name].filter(Boolean).join(' ') || `User${uid}`,
        username: u.username || '',
        is_admin: ADMIN_IDS.includes(String(u.id)),
        role:     ADMIN_IDS.includes(String(u.id)) ? 'admin' : 'user',
      });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── admin/login ───────────────────────────────────────────────
  if (ep === 'admin/login') {
    if (!ADMIN_IDS.includes(String(body?.uid)))  return jsonResp({ ok: false, error: 'Admin emassiz' });
    if (body?.password !== ADMIN_PASS)           return jsonResp({ ok: false, error: "Parol noto'g'ri" });
    return jsonResp({ ok: true });
  }

  // ── admin/tests ───────────────────────────────────────────────
  if (ep === 'admin/tests') {
    try {
      const rows = await sbSelect('tests', {
        select: 'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score',
        order:  'created_at.desc',
      });
      return jsonResp(rows.map(r => normMeta({
        ...(r.meta || {}), test_id: r.test_id, title: r.title,
        question_count: r.question_count, solve_count: r.solve_count,
        avg_score: r.avg_score, is_active: r.is_active, is_paused: r.is_paused,
      })));
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── admin/stats ───────────────────────────────────────────────
  if (ep === 'admin/stats') {
    try {
      const rows = await sbSelect('tests', {
        select: 'test_id,title,meta,question_count,is_active,is_paused,solve_count,avg_score,created_at',
      });
      const active    = rows.filter(r => r.is_active !== false);
      const pub       = active.filter(r => (r.meta || {}).visibility === 'public');
      const totalSolve = rows.reduce((s, r) => s + (r.solve_count || 0), 0);
      const scored    = rows.filter(r => r.avg_score);
      const avgScore  = scored.length
        ? Math.round(scored.reduce((s, r) => s + r.avg_score, 0) / scored.length) : 0;
      const byCategory = {};
      rows.forEach(r => {
        const cat = (r.meta || {}).category || (r.meta || {}).subject || 'other';
        if (!byCategory[cat]) byCategory[cat] = { count: 0, solves: 0, avg: [] };
        byCategory[cat].count++;
        byCategory[cat].solves += r.solve_count || 0;
        if (r.avg_score) byCategory[cat].avg.push(r.avg_score);
      });
      const categories = Object.entries(byCategory).map(([name, d]) => ({
        name, count: d.count, solves: d.solves,
        avg: d.avg.length ? Math.round(d.avg.reduce((a,b) => a+b) / d.avg.length) : 0,
      })).sort((a,b) => b.solves - a.solves);
      const now   = Date.now();
      const days7 = Array.from({length:7}, (_,i) => new Date(now-i*86400000).toISOString().slice(0,10)).reverse();
      const byDay = {};
      days7.forEach(d => { byDay[d] = { created: 0, solves: 0 }; });
      rows.forEach(r => {
        const d = String(r.created_at || (r.meta||{}).created_at || '').slice(0, 10);
        if (byDay[d]) { byDay[d].created++; byDay[d].solves += r.solve_count || 0; }
      });
      return jsonResp({
        totalTests: rows.length, activeTests: active.length, pubTests: pub.length,
        totalSolve, avgScore, categories,
        topTests: [...active].sort((a,b)=>(b.solve_count||0)-(a.solve_count||0)).slice(0,5)
          .map(r => normMeta({ ...(r.meta||{}), test_id: r.test_id, title: r.title,
            question_count: r.question_count, solve_count: r.solve_count })),
        timeline: days7.map(d => ({ date: d, ...byDay[d] })),
      });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── admin/test/{id}/pause ─────────────────────────────────────
  if (ep.match(/^admin\/test\/.+\/pause$/)) {
    const tid = ep.split('/')[2];
    try {
      const row = await sbSelectOne('tests', 'test_id', tid, 'is_paused');
      if (!row) return jsonResp({ error: 'Topilmadi' }, 404);
      const newPaused = !row.is_paused;
      await sbUpdate('tests', 'test_id', tid, { is_paused: newPaused });
      return jsonResp({ ok: true, is_paused: newPaused });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── admin/test/{id}/delete ────────────────────────────────────
  if (ep.match(/^admin\/test\/.+\/delete$/)) {
    const tid = ep.split('/')[2];
    try {
      await sbUpdate('tests', 'test_id', tid, { is_active: false });
      return jsonResp({ ok: true });
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  // ── otp/verify ────────────────────────────────────────────────
  if (ep === 'otp/verify') {
    // OTP bot tomonidan (RAM) boshqariladi.
    // Vercel dan Streamlit'ga so'rov yuborish orqali tekshiramiz.
    const code = (body?.code || '').toUpperCase().trim();
    if (!code) return jsonResp({ ok: false, error: 'Kod kerak' });

    // Eski OTP format (hash asosida)
    const parts = code.split(':');
    if (parts.length === 3) {
      const [testId, ts, hash] = parts;
      if (Date.now() - parseInt(ts) > 600_000) return jsonResp({ ok: false, error: 'Muddati tugagan' });
      const buf = new TextEncoder().encode(`${testId}:${ts}:${BOT_TOKEN.slice(-8)}`);
      const hb  = await crypto.subtle.digest('SHA-256', buf);
      const exp = Array.from(new Uint8Array(hb)).map(b => b.toString(16).padStart(2,'0')).join('').slice(0,8).toUpperCase();
      if (exp !== hash) return jsonResp({ ok: false, error: "Noto'g'ri kod" });
      const row = await sbSelectOne('tests', 'test_id', testId,
        'test_id,title,meta,question_count').catch(() => null);
      return jsonResp({ ok: true, test_id: testId, meta: row ? normMeta({ ...(row.meta||{}), test_id: row.test_id, title: row.title }) : {} });
    }
    return jsonResp({ ok: false, error: "Noto'g'ri kod formati" });
  }

  // ── results/{uid} ─────────────────────────────────────────────
  if (ep.match(/^results\/\d+/)) {
    const uid = ep.split('/')[1];
    try {
      const row = await sbSelectOne('user_stats', 'tg_id', parseInt(uid));
      if (!row) return jsonResp([]);
      const data = row.data || {};
      const results = Object.entries(data).map(([tid, s]) => ({
        test_id:         tid,
        attempts:        s.attempts || 0,
        best_score:      s.best_score || 0,
        avg_score:       s.avg_score || 0,
        last_at:         s.last_at || '',
        passed:          s.passed || false,
        ever_passed:     s.ever_passed ?? s.passed ?? false,
        ever_completed:  s.ever_completed ?? true,
      }));
      return jsonResp(results);
    } catch (e) {
      return jsonResp([]);
    }
  }

  return jsonResp({ error: "Noma'lum endpoint" }, 404);
}
