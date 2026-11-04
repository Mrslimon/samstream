import "@fontsource/readex-pro/arabic-300.css";
import "@fontsource/readex-pro/latin-300.css";
import "@fontsource/readex-pro/arabic-400.css";
import "@fontsource/readex-pro/latin-400.css";
import "@fontsource/readex-pro/arabic-500.css";
import "@fontsource/readex-pro/latin-500.css";
import "@fontsource/readex-pro/arabic-600.css";
import "@fontsource/readex-pro/latin-600.css";
import "./styles.css";
import { App, type AppElements, type Connection } from "./app";
import { parseOpen, parsePayload, readLaunchPayload } from "./launch";
import { resolveLanguage, strings } from "./i18n";
import { parseMedia, parseNotice } from "./notice";
import { startNotifier } from "./notifier";
import { fetchSession, loadSettings, xhrFetch } from "./settings";
import { parseStreams } from "./streams";

function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`#${id} missing from index.html`);
  }
  return element as T;
}

const POLL_MS = 2_000;

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

function lastStream(haUrl: string | undefined) {
  try {
    const saved = storage()?.getItem("samstream.lastStream");
    return saved ? parsePayload(JSON.parse(saved), haUrl) : undefined;
  } catch {
    return undefined;
  }
}

async function boot(): Promise<void> {
  const { settings, source, config, session } = await loadSettings(xhrFetch, storage());
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
    hud: byId("hud"),
    hudLabel: byId("hud-label"),
    hudClock: byId("hud-clock"),
    controls: byId("cam-controls"),
    toast: byId("toast"),
    tvFrame: byId("tv-frame"),
    mjpeg: byId<HTMLImageElement>("mjpeg-image"),
    noticeClock: byId("notice-clock"),
    notice: {
      root: byId("notice"),
      icon: byId("notice-icon"),
      title: byId("notice-title"),
      body: byId("notice-body"),
    },
    media: {
      root: byId("media"),
      video: byId<HTMLVideoElement>("media-video"),
      hud: byId("media-hud"),
      title: byId("media-title"),
      bar: byId("media-bar"),
    },
    sound: byId<HTMLAudioElement>("sound"),
    help: byId("help"),
    debug: byId("debug"),
    video: byId<HTMLVideoElement>("mse-video"),
  };

  const haUrl = config?.ha_url;
  const connection: Connection = !config
    ? "none"
    : source === "home-assistant"
      ? "connected"
      : "offline";
  const previous = lastStream(haUrl);
  // Resume where it left off first, then the configured list (Configure →
  // Cameras), so Left/Right works even before any play_stream automation.
  const streams = [
    ...(previous ? [previous.stream] : []),
    ...settings.cameras.filter((stream) => stream.url !== previous?.stream.url),
    ...parseStreams(import.meta.env.VITE_SPIKE_STREAMS),
  ];
  const app = new App(elements, streams, __APP_VERSION__, language, connection);
  app.start();

  // Start the notifier (the .NET half of the package) and hand it this TV's
  // secret, so HA can post native notifications while Samstream is open and
  // after it backgrounds. A no-op off a real TV or before HA has installed us.
  if (config?.tv_secret) {
    startNotifier(config.tv_secret, (message) => app.debug(message));
  }
  app.debug(`settings: ${source} ${JSON.stringify(settings)}`);
  app.debug(`home assistant: ${haUrl ? haUrl.replace(/\/\/.*@/, "//") : "not set (not installed by HA)"}`);

  // Commands from HA (play_stream / stop_stream), pulled because Samsung TVs drop
  // launch data for sideloaded apps.
  let seq = session?.seq ?? 0;
  // The play command on screen; its first frame starts HA's `duration`.
  let playSeq: number | undefined;
  const apply = (command: unknown): void => {
    const action = (command as { action?: unknown } | null)?.action;
    if (action === "stop") {
      app.debug("HA: stop");
      app.stop();
      return;
    }
    const notice = action === "notice" ? parseNotice(command) : undefined;
    if (notice) {
      app.debug(`HA: notice ${notice.severity}`);
      playSeq = seq;
      app.showNotice(notice);
      return;
    }
    const media = action === "media" ? parseMedia(command) : undefined;
    if (media) {
      app.debug(`HA: media ${media.kind}`);
      playSeq = seq;
      app.playMedia(media);
      return;
    }
    const open = action === "open" ? parseOpen(command) : undefined;
    if (open) {
      app.debug(`HA: open ${open.youtube ? `youtube ${open.youtube}` : open.url}`);
      app.openExternal(open);
      return;
    }
    const payload = action === "play" ? parsePayload(command, haUrl) : undefined;
    if (payload) {
      app.debug(`HA: play ${payload.stream.label || "camera"}`);
      playSeq = seq;
      app.playPayload(payload);
    }
  };
  app.onEnded = () => {
    if (config && playSeq !== undefined) {
      fetchSession(xhrFetch, config, seq, { ended: playSeq }).catch(() => undefined);
    }
  };
  // Back closes Samstream: tell HA first, so it resumes the app underneath.
  app.onClosing = () =>
    config && playSeq !== undefined
      ? fetchSession(xhrFetch, config, seq, { closed: playSeq }).then(
          () => undefined,
          () => undefined,
        )
      : Promise.resolve();
  app.onFirstFrame = () => {
    if (config && playSeq !== undefined) {
      // With the input under Samstream, so HA can switch back to it afterwards.
      fetchSession(xhrFetch, config, seq, {
        playing: playSeq,
        ...(app.tvSourceShown ? { source: app.tvSourceShown } : {}),
      }).catch(() => undefined);
    }
  };
  if (session?.command) apply(session.command);
  if (config) {
    setInterval(() => {
      if (document.hidden) return;
      fetchSession(xhrFetch, config, seq).then(
        (answer) => {
          if (answer.session.seq !== seq) {
            seq = answer.session.seq;
            if (answer.session.command) apply(answer.session.command);
          }
        },
        () => undefined, // HA briefly unreachable: try again next round.
      );
    }, POLL_MS);
  }

  const launch = readLaunchPayload(haUrl);
  app.debug(launch ? `launched by HA: ${launch.stream.label || "camera"}` : "plain launch");
  if (launch) app.playPayload(launch);
  // HA opening Samstream while it already runs.
  window.addEventListener("appcontrol", () => {
    const again = readLaunchPayload(haUrl);
    app.debug(again ? `relaunched by HA: ${again.stream.label || "camera"}` : "relaunch without payload");
    if (again) app.playPayload(again);
  });
}

void boot();
