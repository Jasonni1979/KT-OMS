/**
 * KT-OMS 前端静态服务 + API 反代（演示用，免 Vite dev server）
 * 用法：node serve.mjs [port]
 */
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '..')
const DIST = process.env.KTOMS_DIST || path.join(REPO_ROOT, 'frontend', 'dist')
const PORT = Number(process.argv[2] || process.env.KTOMS_WEB_PORT || 5173)
const API = process.env.KTOMS_API || 'http://127.0.0.1:8000'

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
}

const server = http.createServer(async (req, res) => {
  const url = req.url || '/'
  // API 反代
  if (url.startsWith('/api/')) {
    try {
      const chunks = []
      for await (const c of req) chunks.push(c)
      const body = chunks.length ? Buffer.concat(chunks) : undefined
      const headers = { ...req.headers }
      delete headers.host
      delete headers['content-length']
      const r = await fetch(`${API}${url}`, {
        method: req.method,
        headers,
        body: ['GET', 'HEAD'].includes(req.method) ? undefined : body,
      })
      const buf = Buffer.from(await r.arrayBuffer())
      const out = {}
      r.headers.forEach((v, k) => { if (!['content-encoding', 'transfer-encoding'].includes(k)) out[k] = v })
      res.writeHead(r.status, out)
      res.end(buf)
    } catch (e) {
      res.writeHead(502, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ code: 500, message: `代理失败: ${e.message}`, data: null }))
    }
    return
  }
  // 静态文件（history 模式回退到 index.html）
  let filePath = path.join(DIST, decodeURIComponent(url.split('?')[0]))
  if (!filePath.startsWith(DIST)) { res.writeHead(403); res.end('forbidden'); return }
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(DIST, 'index.html')
  }
  if (!fs.existsSync(filePath)) { res.writeHead(404); res.end('not found'); return }
  const ext = path.extname(filePath)
  res.writeHead(200, { 'content-type': MIME[ext] || 'application/octet-stream', 'cache-control': 'no-cache' })
  fs.createReadStream(filePath).pipe(res)
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[web] 静态服务已启动：http://127.0.0.1:${PORT}（dist=${DIST}，API→${API}）`)
})
