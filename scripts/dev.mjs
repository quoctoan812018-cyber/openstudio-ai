// `pnpm dev`: chạy daemon + web cùng lúc. Token ngẫu nhiên mỗi lần chạy, chỉ truyền qua biến môi trường.
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const shell = process.platform === "win32";
const port = process.env.OPENSTUDIO_PORT ?? "8787";
const token = randomBytes(24).toString("base64url");
const env = {
  ...process.env,
  OPENSTUDIO_PORT: port,
  OPENSTUDIO_TOKEN: token,
  VITE_DAEMON_URL: `http://127.0.0.1:${port}`,
  VITE_DAEMON_TOKEN: token,
};
const procs = [
  spawn("node", ["scripts/daemon.mjs"], { cwd: root, stdio: "inherit", env }),
  spawn("pnpm", ["--filter", "@openstudio/web", "dev"], { cwd: root, stdio: "inherit", shell, env }),
];
let closing = false;
const stopAll = (code = 0) => {
  if (closing) return;
  closing = true;
  for (const p of procs) p.kill();
  process.exit(code);
};
for (const p of procs) p.on("exit", (c) => stopAll(c ?? 0));
process.on("SIGINT", () => stopAll());
process.on("SIGTERM", () => stopAll());
