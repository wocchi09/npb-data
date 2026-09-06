'use strict';
const http = require('node:http');
const handler = require('./api/analyze-atbat.js');
const server = http.createServer((req, res) => {
  if (req.url?.split('?')[0] !== '/api/analyze-atbat') { res.writeHead(404).end(); return; }
  handler(req, res).catch(() => { if (!res.headersSent) res.writeHead(500); res.end(); });
});
server.requestTimeout = 10000;
server.listen(3000, '127.0.0.1', () => console.log('AI ANALYST API: http://127.0.0.1:3000/api/analyze-atbat'));
