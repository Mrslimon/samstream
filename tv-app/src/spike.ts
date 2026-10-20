import { FIT_LABELS, loadFit, nextFit, saveFit } from "./fit";
import { renderHelp } from "./help";
import { MsePlayer } from "./mse";
import { Player, type PlayerCallbacks, type StreamPlayer } from "./player";
import { showOverlay } from "./overlay";

export interface SpikeStream {
  label: string;
  url: string;
  /** "avplay" (default) for HLS/HTTP/RTSP URLs, "mse" for go2rtc ws://…/api/ws?src= URLs. */
  type?: "avplay" | "mse";
  lowLatency?: boolean;
  /** MSE only: also ask go2rtc for audio (PCMU is converted to FLAC). */
  audio?: boolean;
}

export interface SpikeElements {
  overlay: HTMLElement;
  status: HTMLElement;
  help: HTMLElement;
  video: HTMLVideoElement;
}

const KEY_LEFT = 37;
const KEY_UP = 38;
const KEY_RIGHT = 39;
const KEY_DOWN = 40;
const KEY_ENTER = 13;
const KEY_BACK = 10009;
const KEY_GREEN = 404;
const KEY_INFO = 457;
const KEY_0 = 48;
const KEY_9 = 57;
const HELP_VISIBLE_MS = 10_000;
const FIT_TOAST_MS = 2_500;

/** VITE_SPIKE_STREAMS is a JSON array of {label, url, type?}; anything malformed is dropped. */
export function parseSpikeStreams(raw: string | undefined): SpikeStream[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is SpikeStream =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as SpikeStream).label === "string" &&
        typeof (item as SpikeStream).url === "string",
    );
  } catch {
    return [];
  }
}

/** Hide credentials before showing a URL on screen. */
export function redactUrl(url: string): string {
  return url.replace(/\/\/[^/@]*@/, "//***@");
}

/** Milestone 2: cycle through candidate stream URLs and report what the TV can play. */
export function runSpike(streams: SpikeStream[], elements: SpikeElements): void {
  const { overlay, status, help, video } = elements;
  const avplay = globalThis.webapis?.avplay;
  const lines: string[] = [];
  let current = 0;
  let fit = loadFit();
  let helpTimer: ReturnType<typeof setTimeout> | undefined;
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  const render = (line: string): void => {
    lines.unshift(`${new Date().toLocaleTimeString()}  ${line}`);
    lines.length = Math.min(lines.length, 12);
    status.textContent = lines.join("\n");
    console.log(`[samstream] ${line}`);
  };

  const callbacks: PlayerCallbacks = {
    onStatus: (state) => render(`${streams[current].label}: ${state}`),
    onFirstFrame: (elapsed, info) =>
      render(
        `${streams[current].label}: FIRST FRAME ${elapsed} ms` +
          (info ? `  ${info.codec} ${info.width}x${info.height}` : ""),
      ),
    onError: (message) => render(`${streams[current].label}: ERROR ${message}`),
  };

  const mse = new MsePlayer(video, callbacks);
  const native = avplay ? new Player(avplay, callbacks) : undefined;
  const players: StreamPlayer[] = native ? [native, mse] : [mse];
  let active: StreamPlayer | undefined;

  const showHelp = (): void => {
    help.hidden = false;
    clearTimeout(helpTimer);
    helpTimer = setTimeout(() => (help.hidden = true), HELP_VISIBLE_MS);
  };

  const applyFit = (announce: boolean): void => {
    for (const player of players) player.setFit(fit);
    if (announce) {
      showOverlay(overlay, FIT_LABELS[fit]);
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => (overlay.textContent = ""), FIT_TOAST_MS);
    }
  };

  const select = (index: number): void => {
    current = (index + streams.length) % streams.length;
    const stream = streams[current];
    const player = stream.type === "mse" ? mse : native;
    active?.stop();
    if (!player) {
      render("webapis.avplay missing: not running on a Samsung TV");
      return;
    }
    active = player;
    render(`▶ [${current + 1}/${streams.length}] ${redactUrl(stream.url)}`);
    player.play(stream.url, stream.lowLatency === true, stream.audio === true);
  };

  for (let digit = 1; digit <= Math.min(streams.length, 9); digit++) {
    globalThis.tizen?.tvinputdevice.registerKey(String(digit));
  }
  globalThis.tizen?.tvinputdevice.registerKey("ColorF1Green");
  globalThis.tizen?.tvinputdevice.registerKey("Info");

  document.addEventListener("keydown", (event) => {
    const key = event.keyCode;
    if (key === KEY_RIGHT) select(current + 1);
    else if (key === KEY_LEFT) select(current - 1);
    else if (key === KEY_ENTER) select(current);
    else if (key > KEY_0 && key <= KEY_9) select(key - KEY_0 - 1);
    else if (key === KEY_UP || key === KEY_DOWN) {
      fit = nextFit(fit, key === KEY_UP ? 1 : -1);
      saveFit(fit);
      applyFit(true);
    } else if (key === KEY_GREEN || key === KEY_INFO) showHelp();
    else if (key === KEY_BACK) {
      active?.stop();
      globalThis.tizen?.application.getCurrentApplication().exit();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) active?.stop();
    else select(current);
  });

  renderHelp(help);
  showHelp();
  // Announce the restored fit so it is obvious the saved choice survived a restart.
  applyFit(true);
  render(`fit restored: ${fit}`);
  select(0);
}
