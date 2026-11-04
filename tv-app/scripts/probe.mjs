// Package probe/ as a signed .wgt and install+run it — a throwaway investigation app.
// Usage: node --env-file-if-exists=.env.local scripts/probe.mjs
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const tizenHome = process.env.TIZEN_HOME ?? "C:\\tizen-studio";
const tizen = join(tizenHome, "tools", "ide", "bin", process.platform === "win32" ? "tizen.bat" : "tizen");
const sdb = join(tizenHome, "tools", process.platform === "win32" ? "sdb.exe" : "sdb");
const profile = process.env.TIZEN_PROFILE ?? "samstream";
const host = process.env.TV_HOST;
if (!host) { console.error("TV_HOST not set"); process.exit(1); }
const target = `${host}:26101`;
const appId = "SmStrmPrb0.Probe";
const wgt = "SamstreamProbe.wgt";

function exec(command, args) {
  console.log(`> ${command} ${args.join(" ")}`);
  execFileSync(command, args, { stdio: "inherit", shell: process.platform === "win32" });
}

function withProfilesPath(run) {
  const profilesPath = process.env.TIZEN_PROFILES_PATH;
  if (!profilesPath) return run();
  const listing = execFileSync(tizen, ["cli-config", "-l"], { encoding: "utf8", shell: process.platform === "win32" });
  const previous = listing.match(/default\.profiles\.path=(.*)/)?.[1]?.trim();
  const setPath = (value) => exec(tizen, ["cli-config", `"default.profiles.path=${value}"`]);
  setPath(profilesPath);
  try { return run(); } finally { if (previous) setPath(previous); }
}

withProfilesPath(() => exec(tizen, ["package", "-t", "wgt", "-s", profile, "--", "probe"]));
exec(sdb, ["connect", target]);
exec(tizen, ["install", "-n", wgt, "-s", target, "--", "probe"]);
exec(tizen, ["run", "-p", appId, "-s", target]);
