"use strict";

/** Daemon in ra một dòng JSON {"address","token"} khi sẵn sàng. Trả null nếu dòng không hợp lệ hoặc không phải loopback. */
function parseHandshake(line) {
  let o;
  try {
    o = JSON.parse(line);
  } catch {
    return null;
  }
  if (!o || typeof o.address !== "string" || typeof o.token !== "string" || !o.token) return null;
  let u;
  try {
    u = new URL(o.address);
  } catch {
    return null;
  }
  if (u.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(u.hostname)) return null;
  return { address: o.address.replace(/\/$/, ""), token: o.token };
}

module.exports = { parseHandshake };
