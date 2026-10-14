"use strict";
// Quyết định đường dẫn cho chế độ dev (chạy từ repo) và chế độ đóng gói (resources của app + userData).
// Không có đường dẫn cứng: mọi thứ suy ra từ vị trí app / thư mục dữ liệu người dùng.
const path = require("node:path");

function resolvePaths({ packaged, resourcesPath, userData, repoRoot, platform = process.platform }) {
  const exe = platform === "win32" ? ".exe" : "";
  if (!packaged) {
    return {
      packaged: false,
      root: repoRoot,
      daemonDir: path.join(repoRoot, "apps", "daemon"),
      webDist: path.join(repoRoot, "apps", "web", "dist"),
      dataDir: null, // để daemon dùng config.toml (.runtime/)
      uv: "uv",
    };
  }
  const venv = path.join(userData, "env", "venv");
  return {
    packaged: true,
    root: resourcesPath, // chứa config.toml, skills/, models/registry.yaml
    daemonDir: path.join(resourcesPath, "daemon"),
    webDist: path.join(resourcesPath, "web"),
    dataDir: path.join(userData, "data"),
    uv: path.join(resourcesPath, "uv", `uv${exe}`),
    venv,
    python: platform === "win32" ? path.join(venv, "Scripts", "python.exe") : path.join(venv, "bin", "python"),
    uvCache: path.join(userData, "env", "uv-cache"),
    pythonDir: path.join(userData, "env", "python"),
    stamp: path.join(userData, "env", "synced.json"),
  };
}

/** Env cho `uv sync` ở lần chạy đầu: venv và Python do uv quản lý nằm trong userData (ghi được), không đụng thư mục cài đặt. */
function syncEnv(paths, base = process.env) {
  return {
    ...base,
    UV_PROJECT_ENVIRONMENT: paths.venv,
    UV_CACHE_DIR: paths.uvCache,
    UV_PYTHON_INSTALL_DIR: paths.pythonDir,
    UV_NO_PROGRESS: "1",
  };
}

module.exports = { resolvePaths, syncEnv };
