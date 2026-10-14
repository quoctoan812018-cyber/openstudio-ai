"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { resolvePaths, syncEnv } = require("../src/paths.cjs");

test("dev: dùng repo, không ép thư mục dữ liệu", () => {
  const p = resolvePaths({ packaged: false, repoRoot: "/r" });
  assert.equal(p.root, "/r");
  assert.equal(p.dataDir, null);
  assert.equal(p.webDist, path.join("/r", "apps", "web", "dist"));
});

test("đóng gói: tài nguyên chỉ đọc ở resources, dữ liệu + venv ở userData", () => {
  const p = resolvePaths({ packaged: true, resourcesPath: "/res", userData: "/u", platform: "win32" });
  assert.equal(p.uv, path.join("/res", "uv", "uv.exe"));
  assert.equal(p.python, path.join("/u", "env", "venv", "Scripts", "python.exe"));
  assert.equal(p.dataDir, path.join("/u", "data"));
  assert.ok(!p.venv.startsWith("/res") && !p.dataDir.startsWith("/res"));
  const q = resolvePaths({ packaged: true, resourcesPath: "/res", userData: "/u", platform: "linux" });
  assert.equal(q.uv, path.join("/res", "uv", "uv"));
  assert.equal(q.python, path.join("/u", "env", "venv", "bin", "python"));
});

test("syncEnv trỏ venv/cache/python vào userData", () => {
  const p = resolvePaths({ packaged: true, resourcesPath: "/res", userData: "/u", platform: "linux" });
  const e = syncEnv(p, { PATH: "x" });
  assert.equal(e.UV_PROJECT_ENVIRONMENT, p.venv);
  assert.equal(e.UV_CACHE_DIR, p.uvCache);
  assert.equal(e.UV_PYTHON_INSTALL_DIR, p.pythonDir);
  assert.equal(e.PATH, "x");
});
