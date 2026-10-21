import "@fontsource/readex-pro/arabic-300.css";
import "@fontsource/readex-pro/latin-300.css";
import "@fontsource/readex-pro/arabic-400.css";
import "@fontsource/readex-pro/latin-400.css";
import "@fontsource/readex-pro/arabic-500.css";
import "@fontsource/readex-pro/latin-500.css";
import "@fontsource/readex-pro/arabic-600.css";
import "@fontsource/readex-pro/latin-600.css";
import "./styles.css";
import { App, type AppElements } from "./app";
import { resolveLanguage, strings } from "./i18n";
import { loadSettings, xhrFetch } from "./settings";
import { parseStreams } from "./streams";

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`#${id} missing from index.html`);
  }
  return element as T;
}

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

async function boot(): Promise<void> {
  const { settings, source } = await loadSettings(xhrFetch, storage());
  const language = resolveLanguage(settings.language, navigator.language);
  document.documentElement.dataset.theme = settings.theme;
  console.log(`[samstream] settings from ${source}: ${JSON.stringify(settings)}`);

  const text = strings(language);
  byId("info-title").textContent = text.infoTitle;
  byId("info-text").textContent = text.infoText;

  const elements: AppElements = {
    home: byId("home"),
    statusText: byId("status-text"),
    statusDot: byId("status-dot"),
    previewText: byId("preview-text"),
    version: byId("version"),
    playButton: byId<HTMLButtonElement>("play-button"),
    helpButton: byId<HTMLButtonElement>("help-button"),
    exitButton: byId<HTMLButtonElement>("exit-button"),
    player: byId("player"),
    overlay: byId("overlay"),
    live: byId("live"),
    help: byId("help"),
    debug: byId("debug"),
    video: byId<HTMLVideoElement>("mse-video"),
  };

  // Launch payloads from Home Assistant (stream URL, overlay text) land in milestone 8.
  const streams = parseStreams(import.meta.env.VITE_SPIKE_STREAMS);
  new App(elements, streams, __APP_VERSION__, language).start();
}

void boot();
