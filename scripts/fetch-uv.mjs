// Tải bản uv (Apache-2.0/MIT) đúng nền tảng vào apps/desktop/build/uv, kiểm SHA-256 do chính astral-sh công bố.
// Dùng:  node scripts/fetch-uv.mjs <win32|darwin|linux> <x64|arm64> [phiên bản]
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const [platform = process.platform, arch = process.arch, version = "0.12.23"] = process.argv.slice(2);
const TARGETS = {
  "win32-x64": ["x86_64-pc-windows-msvc", "zip"],
  "darwin-arm64": ["aarch64-apple-darwin", "tar.gz"],
  "darwin-x64": ["x86_64-apple-darwin", "tar.gz"],
  "linux-x64": ["x86_64-unknown-linux-gnu", "tar.gz"],
};
const t = TARGETS[`${platform}-${arch}`];
if (!t) throw new Error(`Nền tảng không hỗ trợ: ${platform}-${arch}. Hỗ trợ: ${Object.keys(TARGETS).join(", ")}`);
const [triple, ext] = t;
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "apps", "desktop", "build", "uv");
const exe = platform === "win32" ? "uv.exe" : "uv";
const marker = join(out, ".version");
if (existsSync(join(out, exe)) && existsSync(marker) && readFileSync(marker, "utf8") === `${version} ${triple}`) {
  console.log(`uv ${version} (${triple}) đã có`);
  process.exit(0);
}

const base = `https://github.com/astral-sh/uv/releases/download/${version}/uv-${triple}.${ext}`;
const get = async (url) => {
  const r = await fetch(url, { redirect: "follow" });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return Buffer.from(await r.arrayBuffer());
};
const tmp = mkdtempSync(join(tmpdir(), "uv-"));
try {
  const [archive, sums] = await Promise.all([get(base), get(`${base}.sha256`)]);
  const want = sums.toString("utf8").trim().split(/\s+/)[0].toLowerCase();
  const got = createHash("sha256").update(archive).digest("hex");
  if (want !== got) throw new Error(`SHA-256 không khớp cho ${base}\n  mong đợi ${want}\n  nhận được ${got}`);
  const file = join(tmp, `uv.${ext}`);
  writeFileSync(file, archive);
  // Windows: .zip qua PowerShell (tar GNU của Git Bash hiểu "C:" là máy từ xa); macOS/Linux: tar, chạy trong thư mục tạm bằng đường dẫn tương đối
  if (ext === "zip") execFileSync("powershell", ["-NoProfile", "-Command", `Expand-Archive -LiteralPath '${file}' -DestinationPath '${tmp}' -Force`], { stdio: "inherit" });
  else execFileSync("tar", ["-xzf", `uv.${ext}`], { cwd: tmp, stdio: "inherit" });
  const find = (d) => readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? find(join(d, n)) : n === exe ? [join(d, n)] : []));
  const [bin] = find(tmp);
  if (!bin) throw new Error(`Không thấy ${exe} trong gói giải nén`);
  mkdirSync(out, { recursive: true });
  copyFileSync(bin, join(out, exe));
  if (platform !== "win32") chmodSync(join(out, exe), 0o755);
  writeFileSync(marker, `${version} ${triple}`);
  console.log(`Đã tải uv ${version} (${triple}), sha256 ${got.slice(0, 12)}… → ${join(out, exe)}`);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
