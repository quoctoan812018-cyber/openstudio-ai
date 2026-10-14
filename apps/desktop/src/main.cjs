"use strict";
// Electron chỉ bọc web: khởi động daemon, nạp bản build web, cung cấp kết nối qua preload.
// Dev: chạy daemon từ repo bằng `uv run`. Đóng gói: lần đầu `uv sync` tạo môi trường Python trong userData rồi chạy daemon từ đó.
const { app, BrowserWindow, ipcMain, net, protocol, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const nodeCrypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { pathToFileURL } = require("node:url");
const { parseHandshake } = require("./handshake.cjs");
const { resolvePaths, syncEnv } = require("./paths.cjs");

const SMOKE = process.argv.includes("--smoke");
const DEV_URL = process.env.OPENSTUDIO_DEV_URL; // ví dụ http://127.0.0.1:5173
const APP_ORIGIN = "app://openstudio";
// Tên cố định → thư mục dữ liệu ổn định (%APPDATA%\OpenStudio AI, ~/Library/Application Support/OpenStudio AI, ~/.config/OpenStudio AI),
// không phụ thuộc tên gói npm. OPENSTUDIO_USER_DATA ghi đè để kiểm thử gói cài đặt trong thư mục sạch.
app.setName("OpenStudio AI");
if (process.env.OPENSTUDIO_USER_DATA) app.setPath("userData", process.env.OPENSTUDIO_USER_DATA);

const P = resolvePaths({
  packaged: app.isPackaged,
  resourcesPath: process.resourcesPath,
  userData: app.getPath("userData"),
  repoRoot: path.resolve(__dirname, "..", "..", ".."),
});

protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);

let daemon = null;
let connection = null;
let win = null;

const SPLASH = (msg) =>
  "data:text/html;charset=utf-8," +
  encodeURIComponent(`<!doctype html><meta charset="utf-8"><body style="font:15px system-ui;margin:0;display:grid;place-items:center;height:100vh;background:#18181b;color:#e4e4e7">
  <div style="max-width:32rem;text-align:center"><h2 style="margin:0 0 .5rem">OpenStudio AI</h2><p id="m" style="white-space:pre-wrap">${msg}</p></div>`);

function status(msg) {
  console.log(`[setup] ${msg}`);
  if (win && !win.isDestroyed()) {
    win.webContents.executeJavaScript(`document.getElementById("m") && (document.getElementById("m").textContent = ${JSON.stringify(msg)})`).catch(() => {});
  }
}

/** Mã định danh môi trường Python cần có: đổi khi pyproject/uv.lock đổi (cập nhật app) → đồng bộ lại. */
function envFingerprint() {
  const h = nodeCrypto.createHash("sha256");
  for (const f of ["pyproject.toml", "uv.lock"]) h.update(fs.readFileSync(path.join(P.daemonDir, f)));
  return h.digest("hex");
}

function envReady(fp) {
  try {
    return JSON.parse(fs.readFileSync(P.stamp, "utf8")).fingerprint === fp && fs.existsSync(P.python);
  } catch {
    return false;
  }
}

function ensureEnv() {
  const fp = envFingerprint();
  if (envReady(fp)) return Promise.resolve();
  status("Lần chạy đầu: đang tạo môi trường Python (cần mạng, vài phút)…\nFirst run: creating the Python environment (needs internet, a few minutes)…");
  fs.mkdirSync(path.dirname(P.stamp), { recursive: true });
  return new Promise((resolve, reject) => {
    const p = spawn(P.uv, ["sync", "--project", P.daemonDir, "--frozen", "--no-dev"], { env: syncEnv(P), windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let tail = "";
    const onLine = (line) => {
      tail = (tail + "\n" + line).slice(-1500);
      if (line.trim()) status(line.trim().slice(0, 160));
    };
    readline.createInterface({ input: p.stdout }).on("line", onLine);
    readline.createInterface({ input: p.stderr }).on("line", onLine);
    p.on("error", (e) => reject(new Error(`Không chạy được uv (${P.uv}): ${e.message}`)));
    p.on("exit", (code) => {
      if (code !== 0) return reject(new Error(`uv sync lỗi (mã ${code}):${tail}`));
      fs.writeFileSync(P.stamp, JSON.stringify({ fingerprint: fp, at: new Date().toISOString() }));
      resolve();
    });
  });
}

function daemonCommand() {
  const env = {
    ...process.env,
    OPENSTUDIO_ROOT: P.root,
    OPENSTUDIO_PORT: "0",
    PYTHONPATH: P.daemonDir,
    OPENSTUDIO_WEB_ORIGINS: APP_ORIGIN,
    OPENSTUDIO_TOKEN: "", // để daemon tự sinh token ngẫu nhiên
    ...(P.dataDir ? { OPENSTUDIO_DATA_DIR: P.dataDir } : {}),
  };
  if (P.packaged) return { cmd: P.python, args: ["-m", "openstudio"], opts: { cwd: P.root, env, windowsHide: true } };
  return {
    cmd: "uv",
    args: ["run", "--project", "apps/daemon", "python", "-m", "openstudio"],
    opts: { cwd: P.root, env, windowsHide: true, shell: process.platform === "win32" },
  };
}

function startDaemon() {
  return new Promise((resolve, reject) => {
    const { cmd, args, opts } = daemonCommand();
    daemon = spawn(cmd, args, { ...opts, stdio: ["ignore", "pipe", "inherit"] });
    const timer = setTimeout(() => reject(new Error("Daemon không khởi động kịp (120s)")), 120000);
    readline.createInterface({ input: daemon.stdout }).on("line", (line) => {
      const hs = parseHandshake(line);
      if (hs) {
        clearTimeout(timer);
        resolve(hs);
      }
    });
    daemon.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Daemon thoát sớm (mã ${code})`));
    });
  });
}

function stopDaemon() {
  if (!daemon || daemon.killed) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(daemon.pid), "/T", "/F"], { windowsHide: true });
  else daemon.kill();
  daemon = null;
}

function registerAppProtocol() {
  const base = path.resolve(P.webDist);
  protocol.handle("app", (req) => {
    const url = new URL(req.url);
    const rel = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
    const file = path.resolve(path.join(base, rel));
    if (file !== base && !file.startsWith(base + path.sep)) return new Response("Forbidden", { status: 403 });
    return net.fetch(pathToFileURL(file).toString());
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    show: !SMOKE,
    title: "OpenStudio AI",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  return win;
}

app.whenReady().then(async () => {
  // đăng ký TRƯỚC khi nạp trang bất kỳ: preload gọi sendSync, thiếu handler sẽ treo renderer (null cho tới khi daemon sẵn sàng)
  ipcMain.on("openstudio:get-connection", (e) => (e.returnValue = connection));
  try {
    createWindow();
    await win.loadURL(SPLASH("Đang khởi động… / Starting…"));
    if (P.packaged) await ensureEnv();
    status("Đang khởi động daemon… / Starting the daemon…");
    connection = await startDaemon();
    if (!DEV_URL) registerAppProtocol();
    await win.loadURL(DEV_URL ?? `${APP_ORIGIN}/index.html`);
    if (SMOKE) {
      // Kiểm tra: trang nạp xong và ConnectionGate đi qua → thấy menu điều hướng
      await new Promise((r) => setTimeout(r, 2500));
      const text = await win.webContents.executeJavaScript("document.body.innerText");
      const ok = /Bảng điều khiển|Dashboard/.test(text);
      console.log(ok ? "SMOKE_OK" : `SMOKE_FAIL: ${text.slice(0, 200)}`);
      stopDaemon();
      app.exit(ok ? 0 : 1);
    }
  } catch (err) {
    console.error(String(err));
    stopDaemon();
    if (SMOKE || !win || win.isDestroyed()) return app.exit(1);
    await win.loadURL(SPLASH("Không khởi động được / Failed to start:\n" + String(err).slice(0, 1200).replace(/[<>&]/g, "")));
  }
});

app.on("window-all-closed", () => {
  stopDaemon();
  app.quit();
});
app.on("before-quit", stopDaemon);
