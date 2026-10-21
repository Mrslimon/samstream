#!/usr/bin/env node
// Samsung account sign-in for the Samstream Home Assistant integration.
//
// Samsung's sign-in page only redirects to http://localhost:4794/signin/callback, so
// Home Assistant (a server elsewhere on the network) cannot receive the answer itself.
// This helper runs on any computer with a browser: it opens the sign-in page, catches
// the callback on localhost, and forwards it to Home Assistant with a one-time code.
//
//   npx samstream-signin <home-assistant-url> <code>
import { exec } from "node:child_process";
import { createServer } from "node:http";

const PORT = 4794;
const CALLBACK_PATH = "/signin/callback";
const GIVE_UP_AFTER_MS = 10 * 60 * 1000;

const [haUrl, code] = process.argv.slice(2);
if (!haUrl || !code) {
  console.error("Usage: npx samstream-signin <home-assistant-url> <code>");
  console.error("Example: npx samstream-signin http://192.168.1.5:8123 9f3a1c2e");
  process.exit(2);
}
const endpoint = `${haUrl.replace(/\/+$/, "")}/api/samstream/signin/${encodeURIComponent(code)}`;

function page(ok, detail = "") {
  const [title, en, ar] = ok
    ? ["Samstream", "Signed in. You can close this tab and go back to Home Assistant.", "تم تسجيل الدخول. يمكنك إغلاق هذه الصفحة والعودة إلى Home Assistant."]
    : ["Samstream", `Sign-in could not be passed to Home Assistant. ${detail}`, "تعذّر إرسال تسجيل الدخول إلى Home Assistant."];
  return `<!doctype html><meta charset="utf-8"><title>${title}</title>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;line-height:1.6">
<h1>${ok ? "✓" : "✗"} ${title}</h1><p>${en}</p><p dir="rtl">${ar}</p></body>`;
}

function openBrowser(url) {
  const command =
    process.platform === "win32" ? `start "" "${url}"` : process.platform === "darwin" ? `open "${url}"` : `xdg-open "${url}"`;
  exec(command, () => {});
}

async function main() {
  const start = await fetch(endpoint).catch((err) => {
    throw new Error(`Cannot reach Home Assistant at ${haUrl}: ${err.message}`);
  });
  if (!start.ok) {
    throw new Error(`Home Assistant does not know this code (HTTP ${start.status}). Start "Sign in with Samsung" again and use the new code.`);
  }
  const { sign_in_url: signInUrl } = await start.json();

  const listeners = [];
  const done = new Promise((resolve, reject) => {
    const handler = (req, res) => {
      if (req.method !== "POST" || !req.url.startsWith(CALLBACK_PATH)) {
        res.writeHead(404).end();
        return;
      }
      let body = "";
      req.setEncoding("utf8");
      req.on("data", (chunk) => (body += chunk));
      req.on("end", async () => {
        try {
          const forwarded = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ body }),
          });
          const ok = forwarded.ok;
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(page(ok, ok ? "" : `HTTP ${forwarded.status}`));
          ok ? resolve() : reject(new Error(`Home Assistant rejected the sign-in (HTTP ${forwarded.status})`));
        } catch (err) {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(page(false, err.message));
          reject(err);
        }
      });
    };
    // Loopback only: the browser on this machine is the only client.
    for (const host of ["127.0.0.1", "::1"]) {
      const server = createServer(handler);
      server.on("error", (err) => {
        if (host === "127.0.0.1") reject(new Error(`Port ${PORT} is busy (is Apps2Samsung or Tizen Studio open?): ${err.message}`));
      });
      server.listen(PORT, host);
      listeners.push(server);
    }
    setTimeout(() => reject(new Error("No sign-in within 10 minutes.")), GIVE_UP_AFTER_MS).unref();
  });

  console.log("Opening the Samsung sign-in page in your browser...");
  console.log(`If it does not open, visit:\n${signInUrl}\n`);
  openBrowser(signInUrl);
  try {
    await done;
    console.log("Done: Home Assistant received the sign-in. Go back to it to finish.");
  } finally {
    for (const server of listeners) server.close();
  }
}

main().catch((err) => {
  console.error(`Error: ${err.message}`);
  process.exit(1);
});
