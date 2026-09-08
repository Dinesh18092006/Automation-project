const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const PORT = parseInt(process.env.PORT || '3000', 10);
const PUBLIC_DIR = __dirname;

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
};

// Helper to parse .env file if present
function loadEnvFile(envFilePath) {
  try {
    if (fs.existsSync(envFilePath)) {
      const content = fs.readFileSync(envFilePath, 'utf8');
      content.split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (trimmed && !trimmed.startsWith('#')) {
          const eqIdx = trimmed.indexOf('=');
          if (eqIdx > 0) {
            const key = trimmed.slice(0, eqIdx).trim();
            const val = trimmed.slice(eqIdx + 1).trim();
            if (!process.env[key]) {
              process.env[key] = val;
            }
          }
        }
      });
    }
  } catch (e) {
    // Ignore .env read errors
  }
}

// Check local frontend .env and root .env
loadEnvFile(path.join(__dirname, '.env'));
loadEnvFile(path.join(__dirname, '..', '.env'));

const server = http.createServer((req, res) => {
  // Parse requested URL path
  const reqPath = decodeURI(req.url.split('?')[0]);

  // Handle dynamic /env.js for client-side configuration injection
  if (reqPath === '/env.js') {
    const safeEnv = {
      AI_WORKFLOW_WEBHOOK_URL: process.env.VITE_AI_WORKFLOW_WEBHOOK_URL || process.env.AI_WORKFLOW_WEBHOOK_URL || 'https://api.agents.snsihub.ai/webhook/memora-chat',
      AI_WORKFLOW_TEST_WEBHOOK_URL: process.env.VITE_AI_WORKFLOW_TEST_WEBHOOK_URL || process.env.AI_WORKFLOW_TEST_WEBHOOK_URL || 'https://api.agents.snsihub.ai/webhook-test/memora-chat',
      SUPABASE_URL: process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL || 'https://vzxlgygptsdtyiowowfq.supabase.co',
      SUPABASE_ANON_KEY: process.env.VITE_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec',
    };
    const jsContent = `window.ENV = ${JSON.stringify(safeEnv, null, 2)};`;
    res.writeHead(200, {
      'Content-Type': 'application/javascript; charset=utf-8',
      'Cache-Control': 'no-cache',
    });
    res.end(jsContent);
    return;
  }

  // Handle /api/config JSON endpoint
  if (reqPath === '/api/config') {
    const safeEnv = {
      AI_WORKFLOW_WEBHOOK_URL: process.env.VITE_AI_WORKFLOW_WEBHOOK_URL || process.env.AI_WORKFLOW_WEBHOOK_URL || 'https://api.agents.snsihub.ai/webhook/memora-chat',
      AI_WORKFLOW_TEST_WEBHOOK_URL: process.env.VITE_AI_WORKFLOW_TEST_WEBHOOK_URL || process.env.AI_WORKFLOW_TEST_WEBHOOK_URL || 'https://api.agents.snsihub.ai/webhook-test/memora-chat',
      SUPABASE_URL: process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL || 'https://vzxlgygptsdtyiowowfq.supabase.co',
      SUPABASE_ANON_KEY: process.env.VITE_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6eGxneWdwdHNkdHlpb3dvd2ZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDcyNDQsImV4cCI6MjEwMzgyMzI0NH0.pLgvSOj18ZPbcq6BNSPeQSMMx36HuWrjI_ycyg_J8ec',
    };
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-cache',
    });
    res.end(JSON.stringify(safeEnv));
    return;
  }

  // Handle /api/workbench/audio-webhook proxy to stream multipart audio to SNS Webhook
  if (reqPath === '/api/workbench/audio-webhook') {
    if (req.method !== 'POST') {
      res.writeHead(405, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Method Not Allowed' }));
      return;
    }

    const targetUrlStr = req.headers['x-target-webhook-url'] || process.env.VITE_AI_WORKFLOW_WEBHOOK_URL || process.env.AI_WORKFLOW_WEBHOOK_URL || 'https://api.agents.snsihub.ai/webhook/memora-chat';
    try {
      const targetUrl = new URL(targetUrlStr);
      const isHttps = targetUrl.protocol === 'https:';
      const clientModule = isHttps ? https : http;

      const proxyHeaders = { ...req.headers };
      delete proxyHeaders.host;
      delete proxyHeaders['x-target-webhook-url'];
      proxyHeaders.host = targetUrl.host;

      const proxyReqOptions = {
        hostname: targetUrl.hostname,
        port: targetUrl.port || (isHttps ? 443 : 80),
        path: targetUrl.pathname + (targetUrl.search || ''),
        method: 'POST',
        headers: proxyHeaders,
      };

      const proxyReq = clientModule.request(proxyReqOptions, (proxyRes) => {
        const resHeaders = { ...proxyRes.headers };
        resHeaders['access-control-allow-origin'] = '*';
        res.writeHead(proxyRes.statusCode || 200, resHeaders);
        proxyRes.pipe(res);
      });

      proxyReq.on('error', (err) => {
        console.error('[PROXY] Webhook error:', err.message);
        res.writeHead(502, { 'Content-Type': 'application/json', 'access-control-allow-origin': '*' });
        res.end(JSON.stringify({ error: 'Failed to contact SNS Webhook', detail: err.message }));
      });

      req.pipe(proxyReq);
      return;
    } catch (err) {
      console.error('[PROXY] Invalid URL:', err.message);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid Webhook URL configuration' }));
      return;
    }
  }

  let filePath = path.join(PUBLIC_DIR, reqPath === '/' ? 'index.html' : reqPath);

  // Security check: ensure path is within PUBLIC_DIR
  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain' });
    res.end('403 Forbidden');
    return;
  }

  fs.stat(filePath, (err, stats) => {
    if (err) {
      // If file not found, try index.html for SPA fallback
      const fallbackPath = path.join(PUBLIC_DIR, 'index.html');
      fs.readFile(fallbackPath, (fbErr, fbContent) => {
        if (fbErr) {
          res.writeHead(404, { 'Content-Type': 'text/plain' });
          res.end('404 Not Found');
        } else {
          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
          res.end(fbContent);
        }
      });
      return;
    }

    if (stats.isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    fs.readFile(filePath, (readErr, content) => {
      if (readErr) {
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        res.end('500 Internal Server Error');
        return;
      }
      res.writeHead(200, {
        'Content-Type': contentType,
        'Cache-Control': 'no-cache',
      });
      res.end(content);
    });
  });
});

server.listen(PORT, () => {
  console.log(`\n=================================================`);
  console.log(`  Frontend Server running at: http://localhost:${PORT}`);
  console.log(`=================================================\n`);
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    const nextPort = PORT + 1;
    console.warn(`Port ${PORT} is busy, trying port ${nextPort}...`);
    server.listen(nextPort);
  } else {
    console.error('Server error:', err);
  }
});
