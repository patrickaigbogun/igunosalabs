const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const PORT = Number(process.env.PORT || 80);
const PUBLIC_DIR = path.join(__dirname, 'public');
const RESEND_API_KEY = process.env.RESEND_API_KEY || '';
const CONTACT_TO = process.env.CONTACT_TO || 'robotics@dexx.systems';
const CONTACT_FROM = process.env.CONTACT_FROM || 'Igunosalabs <robotics@dexx.systems>';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.json': 'application/json; charset=utf-8',
};

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}

async function handleContact(req, res) {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 16384) {
      return sendJson(res, 413, { ok: false, error: 'Payload too large.' });
    }
  }

  let body;
  try {
    body = JSON.parse(raw || '{}');
  } catch {
    return sendJson(res, 400, { ok: false, error: 'Invalid JSON.' });
  }

  const email = String(body.email || '').trim();
  const project = String(body.project || '').trim();
  const note = String(body.note || '').trim();

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return sendJson(res, 400, { ok: false, error: 'Please enter a valid email address.' });
  }

  const record = {
    email,
    project: project || 'General',
    note,
    timestamp: new Date().toISOString(),
  };

  try {
    fs.appendFileSync('/tmp/inquiries.jsonl', JSON.stringify(record) + '\n');
  } catch {}

  if (!RESEND_API_KEY) {
    console.warn('[contact] RESEND_API_KEY not set; logged inquiry:', record);
    return sendJson(res, 200, { ok: true, queued: true });
  }

  try {
    const resp = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: CONTACT_FROM,
        to: [CONTACT_TO],
        reply_to: email,
        subject: `Igunosalabs Inquiry${project ? `: ${project}` : ''} — ${email}`,
        text: [
          `New inquiry from robotics.dexx.systems`,
          ``,
          `Email: ${email}`,
          `Project: ${project || 'General / Open to discuss'}`,
          note ? `Note: ${note}` : null,
          `Time: ${record.timestamp}`,
        ]
          .filter(Boolean)
          .join('\n'),
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      console.error('[contact] Resend error:', resp.status, errText);
      return sendJson(res, 502, { ok: false, error: 'Could not deliver message right now.' });
    }

    return sendJson(res, 200, { ok: true });
  } catch (err) {
    console.error('[contact] Fetch failed:', err);
    return sendJson(res, 502, { ok: false, error: 'Delivery service unreachable.' });
  }
}

function serveStatic(req, res) {
  const urlPath = (req.url || '/').split('?')[0];
  let cleanPath = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, '');
  if (cleanPath === '/' || cleanPath === '') cleanPath = '/index.html';

  let filePath = path.join(PUBLIC_DIR, cleanPath);

  // Support clean URLs like /projects/egwe -> /projects/egwe.html
  if (!fs.existsSync(filePath) && !path.extname(filePath)) {
    const htmlCandidate = filePath + '.html';
    if (fs.existsSync(htmlCandidate)) filePath = htmlCandidate;
  }

  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, 'index.html');
  }

  if (!filePath.startsWith(PUBLIC_DIR) || !fs.existsSync(filePath)) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    return res.end('Not found');
  }

  const ext = path.extname(filePath).toLowerCase();
  const headers = {
    'Content-Type': MIME[ext] || 'application/octet-stream',
  };
  if (['.jpg', '.jpeg', '.png', '.webp', '.svg', '.css'].includes(ext)) {
    headers['Cache-Control'] = 'public, max-age=86400';
  }

  res.writeHead(200, headers);
  fs.createReadStream(filePath).pipe(res);
}

const server = http.createServer((req, res) => {
  if (req.method === 'POST' && (req.url || '').split('?')[0] === '/api/contact') {
    return handleContact(req, res);
  }
  if (req.method === 'GET' || req.method === 'HEAD') {
    return serveStatic(req, res);
  }
  res.writeHead(405, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Method not allowed');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Igunosalabs server listening on port ${PORT}`);
});
