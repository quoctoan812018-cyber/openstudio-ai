"use strict";
const { contextBridge, ipcRenderer } = require("electron");

// Chỉ lộ địa chỉ + token của daemon cục bộ; không lộ Node/fs cho trang web.
contextBridge.exposeInMainWorld("openstudioDesktop", {
  connection: ipcRenderer.sendSync("openstudio:get-connection"),
});
