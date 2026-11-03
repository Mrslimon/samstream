// Package dist/ as a signed .wgt and deploy it with the Tizen Studio CLI.
// Usage: node --env-file-if-exists=.env.local scripts/tizen.mjs <package|install|run|deploy|notifier|notifier-install>
//
// The notifier is a separate nodisplay .NET package (Tizen has no Web-UI + .NET
// hybrid — see docs/hybrid-package.md). "notifier" builds its .tpk;
// "notifier-install" installs that .tpk on the TV. The web app starts it, so the
// user sees only Samstream's icon.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const tizenHome = process.env.TIZEN_HOME ?? "C:\\tizen-studio";
const tizen = join(tizenHome, "tools", "ide", "bin", process.platform === "win32" ? "tizen.bat" : "tizen");
const sdb = join(tizenHome, "tools", process.platform === "win32" ? "sdb.exe" : "sdb");
const profile = process.env.TIZEN_PROFILE ?? "samstream";
const target = `${process.env.TV_HOST ?? fail("TV_HOST is not set")}:26101`;

const configXml = readFileSync("public/config.xml", "utf8");
const appId = configXml.match(/<tizen:application id="([^"]+)"/)?.[1] ?? fail("no app id in config.xml");
const wgt = "Samstream.wgt";
// The .NET notifier project and the .tpk `dotnet build` emits for it.
const notifierDir = "notifier-dotnet";
const notifierTpkDir = join(notifierDir, "bin", "Release", "tizen40");
const notifierTpk = join(notifierTpkDir, "org.samstream.notifier-1.0.0.tpk");
const dotnet = process.env.DOTNET ?? "dotnet";

function fail(message) {
  console.error(message);
  process.exit(1);
}

function exec(command, args) {
  console.log(`> ${command} ${args.join(" ")}`);
  // .bat files can only be spawned through a shell on Windows.
  execFileSync(command, args, { stdio: "inherit", shell: process.platform === "win32" });
}

// The CLI only reads profiles from its global config, so point it at TIZEN_PROFILES_PATH
// for the duration of the package step and put the previous value back afterwards.
function withProfilesPath(run) {
  const profilesPath = process.env.TIZEN_PROFILES_PATH;
  if (!profilesPath) {
    return run();
  }
  const listing = execFileSync(tizen, ["cli-config", "-l"], { encoding: "utf8", shell: process.platform === "win32" });
  const previous = listing.match(/default\.profiles\.path=(.*)/)?.[1]?.trim();
  // cmd.exe needs the key=value pair quoted, or tizen.bat splits it on "=".
  const setPath = (value) => exec(tizen, ["cli-config", `"default.profiles.path=${value}"`]);
  setPath(profilesPath);
  try {
    return run();
  } finally {
    if (previous) setPath(previous);
  }
}

const steps = {
  package: () => withProfilesPath(() => exec(tizen, ["package", "-t", "wgt", "-s", profile, "--", "dist"])),
  // Build the .NET notifier .tpk (its own nodisplay package).
  notifier: () => exec(dotnet, ["build", "-c", "Release", notifierDir]),
  // Install the notifier .tpk on the TV. Re-sign with HA's identity first for a
  // retail TV (the dev profile here won't install — err 118).
  "notifier-install": () => {
    if (!existsSync(notifierTpk)) fail(`notifier .tpk not found at ${notifierTpk} (run "notifier" first)`);
    exec(sdb, ["connect", target]);
    exec(tizen, ["install", "-n", notifierTpk, "-s", target, "--", notifierTpkDir]);
  },
  install: () => {
    exec(sdb, ["connect", target]);
    exec(tizen, ["install", "-n", wgt, "-s", target, "--", "dist"]);
  },
  run: () => exec(tizen, ["run", "-p", appId, "-s", target]),
};

const command = process.argv[2];
const plan = command === "deploy" ? ["package", "install", "run"] : [command];
for (const step of plan) {
  (steps[step] ?? (() => fail(`unknown command: ${step}`)))();
}
