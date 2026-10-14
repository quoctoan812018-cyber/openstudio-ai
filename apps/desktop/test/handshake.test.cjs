"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { parseHandshake } = require("../src/handshake.cjs");

test("chấp nhận handshake loopback hợp lệ", () => {
  assert.deepStrictEqual(parseHandshake('{"address":"http://127.0.0.1:5000/","token":"abc"}'), {
    address: "http://127.0.0.1:5000",
    token: "abc",
  });
});

test("từ chối địa chỉ không phải loopback", () => {
  assert.strictEqual(parseHandshake('{"address":"http://evil.example:80","token":"abc"}'), null);
  assert.strictEqual(parseHandshake('{"address":"http://0.0.0.0:80","token":"abc"}'), null);
});

test("từ chối dòng không phải JSON hoặc thiếu token", () => {
  assert.strictEqual(parseHandshake("INFO started"), null);
  assert.strictEqual(parseHandshake('{"address":"http://127.0.0.1:1","token":""}'), null);
});
