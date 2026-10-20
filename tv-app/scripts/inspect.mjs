// Relaunch the app with the web inspector and stream its console over CDP (retail TVs block dlog).
// Usage: node --env-file-if-exists=.env.local scripts/inspect.mjs [--keys 39,39] [--step 25] [--port 9222]
//   --keys  key codes sent one by one via CDP (39 = right, 37 = left, 13 = OK)
//   --step  seconds to wait before each key and before exiting
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    keys: { type: "string", default: "" },
    step: { type: "string", default: "25" },
    port: { type: "string", default: "9222" },
  },
});
const tizenHome = process.env.TIZEN_HOME ?? "C:\\tizen-studio";
const sdb = join(tizenHome, "tools", process.platform === "win32" ? "sdb.exe" : "sdb");
const target = `${process.env.TV_HOST}:26101`;
const appId = readFileSync("public/config.xml", "utf8").match(/<tizen:application id="([^"]+)"/)[1];
const localPort = Number(values.port);
const stepMs = Number(values.step) * 1000;
const keys = values.keys ? values.keys.split(",").map(Number) : [];

const sdbRun = (...args) => execFileSync(sdb, ["-s", target, ...args], { encoding: "utf8" });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const debugOutput = sdbRun("shell", "0", "debug", appId);
const remotePort = debugOutput.match(/port:\s*(\d+)/)?.[1];
if (!remotePort) {
  console.error(`No inspector port in: ${debugOutput}`);
  process.exit(1);
}
sdbRun("forward", `tcp:${localPort}`, `tcp:${remotePort}`);

let pages = [];
for (let attempt = 0; attempt < 20 && pages.length === 0; attempt++) {
  await sleep(500);
  pages = await fetch(`http://127.0.0.1:${localPort}/json`).then((r) => r.json()).catch(() => []);
}
const page = pages.find((p) => p.webSocketDebuggerUrl);
if (!page) {
  console.error("Inspector did not expose a page");
  process.exit(1);
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = nextId++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

const stamp = () => new Date().toLocaleTimeString();
ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message.result);
    pending.delete(message.id);
  } else if (message.method === "Runtime.consoleAPICalled") {
    const text = message.params.args.map((a) => a.value ?? a.description ?? "").join(" ");
    console.log(`${stamp()} console.${message.params.type}: ${text}`);
  } else if (message.method === "Runtime.exceptionThrown") {
    console.log(`${stamp()} EXCEPTION: ${message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text}`);
  }
});
await new Promise((resolve) => ws.addEventListener("open", resolve));
await send("Runtime.enable");

const pressKey = async (keyCode) => {
  for (const type of ["rawKeyDown", "keyUp"]) {
    await send("Input.dispatchKeyEvent", { type, windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode });
  }
  console.log(`${stamp()} >>> key ${keyCode}`);
};

const dumpStatus = async () => {
  const result = await send("Runtime.evaluate", {
    expression: "document.getElementById('status').textContent + '\\n--- overlay: ' + document.getElementById('overlay').textContent",
    returnByValue: true,
  });
  console.log(`${stamp()} --- status panel ---\n${result?.result?.value}`);
};

for (const key of keys) {
  await sleep(stepMs);
  await dumpStatus();
  await pressKey(key);
}
await sleep(stepMs);
await dumpStatus();
ws.close();
sdbRun("forward", "--remove", `tcp:${localPort}`);
