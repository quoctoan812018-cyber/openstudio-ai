// Chạy daemon qua uv. Nếu không có OPENSTUDIO_TOKEN thì daemon tự sinh và in ra stdout.
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const child = spawn("uv", ["run", "--project", "apps/daemon", "python", "-m", "openstudio"], {
  cwd: root, stdio: "inherit", shell: process.platform === "win32",
  env: { ...process.env, OPENSTUDIO_ROOT: root, PYTHONPATH: join(root, "apps/daemon") },
});
const stop = () => child.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
child.on("exit", (code) => process.exit(code ?? 0));
