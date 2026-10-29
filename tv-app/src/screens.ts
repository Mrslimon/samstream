import type { MediaItem, Notice, Severity } from "./notice";
import { scrollWhenLong, showOverlay } from "./overlay";

const SVG_NS = "http://www.w3.org/2000/svg";
// Line icons drawn with currentColor (the TV has no emoji font to rely on).
const ICONS: Record<Severity, string[]> = {
  info: ["M32 6a26 26 0 1 0 0 52a26 26 0 1 0 0-52z", "M32 28v16", "M32 20v0.5"],
  warning: ["M32 7 59 55H5z", "M32 25v14", "M32 46v0.5"],
  alert: [
    "M18 44V30a14 14 0 0 1 28 0v14l4 5H14z",
    "M27 53a5 5 0 0 0 10 0",
    "M32 10v6",
  ],
  // Drawn stroke by stroke in CSS (pathLength 1): the ring, then the tick.
  success: ["M32 6a26 26 0 1 1 0 52a26 26 0 1 1 0-52z", "M20 33l8 8l16-17"],
};

function icon(severity: Severity): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 64 64");
  for (const d of ICONS[severity]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    // Lets CSS draw any path with stroke-dash offsets from 1 to 0.
    path.setAttribute("pathLength", "1");
    svg.appendChild(path);
  }
  return svg;
}

export interface NoticeElements {
  root: HTMLElement;
  icon: HTMLElement;
  title: HTMLElement;
  body: HTMLElement;
}

/** Full-screen message (`samstream.show_message`), with an optional sound. */
export class NoticeScreen {
  private shown: Notice | undefined;

  constructor(
    private readonly el: NoticeElements,
    private readonly sound: HTMLAudioElement,
  ) {}

  show(notice: Notice): void {
    const same = this.shown?.title === notice.title && this.shown.severity === notice.severity;
    this.shown = notice;
    this.el.root.setAttribute("data-severity", notice.severity);
    this.el.icon.textContent = "";
    this.el.icon.appendChild(icon(notice.severity));
    this.el.title.textContent = notice.title;
    this.el.title.hidden = !notice.title;
    const card = showOverlay(this.el.body, notice.message);
    this.el.body.hidden = !notice.message;
    this.el.root.hidden = false;
    scrollWhenLong(card);
    // A text-only update (same title) does not ring again.
    if (notice.sound && !same) {
      this.sound.src = notice.sound;
      this.sound.play().catch(() => undefined);
    }
  }

  hide(): void {
    this.shown = undefined;
    this.el.root.hidden = true;
    this.sound.pause();
    this.sound.removeAttribute("src");
    this.sound.load();
  }
}

export interface MediaElements {
  root: HTMLElement;
  video: HTMLVideoElement;
  hud: HTMLElement;
  title: HTMLElement;
  bar: HTMLElement;
}

export interface MediaCallbacks {
  onStart(): void;
  onEnd(): void;
  onError(message: string): void;
}

const KEY_LEFT = 37;
const KEY_RIGHT = 39;
const KEY_ENTER = 13;
const KEY_PLAY = 415;
const KEY_PAUSE = 19;
const KEY_PLAY_PAUSE = 10252;
const SEEK_SECONDS = 10;
const HUD_MS = 5_000;

/** A video (or audio) file from HA's media library. */
export class MediaScreen {
  private started = false;
  private hudTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly el: MediaElements,
    private readonly callbacks: MediaCallbacks,
  ) {
    const video = el.video;
    video.addEventListener("playing", () => {
      if (!this.started && video.getAttribute("src")) {
        this.started = true;
        callbacks.onStart();
      }
    });
    video.addEventListener("ended", () => callbacks.onEnd());
    video.addEventListener("error", () => {
      if (video.getAttribute("src")) {
        callbacks.onError(`video error ${video.error?.code ?? "?"}`);
      }
    });
    video.addEventListener("timeupdate", () => {
      const fraction = video.duration > 0 ? video.currentTime / video.duration : 0;
      el.bar.style.width = `${(fraction * 100).toFixed(2)}%`;
    });
  }

  show(item: MediaItem): void {
    this.started = false;
    this.el.root.classList.toggle("audio", item.kind === "audio");
    this.el.title.textContent = item.title;
    this.el.bar.style.width = "0";
    this.el.root.hidden = false;
    this.el.video.src = item.url;
    this.el.video.play().catch((error: unknown) => this.callbacks.onError(String(error)));
    this.showHud();
  }

  /** Remote keys while a video plays; false when the key is not ours. */
  onKey(key: number): boolean {
    const video = this.el.video;
    if (key === KEY_ENTER || key === KEY_PLAY_PAUSE) {
      if (video.paused) void video.play();
      else video.pause();
    } else if (key === KEY_PLAY) {
      void video.play();
    } else if (key === KEY_PAUSE) {
      video.pause();
    } else if (key === KEY_LEFT || key === KEY_RIGHT) {
      const step = key === KEY_RIGHT ? SEEK_SECONDS : -SEEK_SECONDS;
      video.currentTime = Math.max(0, video.currentTime + step);
    } else {
      return false;
    }
    this.showHud();
    return true;
  }

  pause(): void {
    this.el.video.pause();
  }

  hide(): void {
    clearTimeout(this.hudTimer);
    this.el.root.hidden = true;
    this.el.video.pause();
    this.el.video.removeAttribute("src");
    this.el.video.load();
  }

  /** Title and progress show for a moment after any key, then fade. */
  private showHud(): void {
    this.el.root.classList.remove("idle");
    clearTimeout(this.hudTimer);
    this.hudTimer = setTimeout(() => {
      if (!this.el.root.classList.contains("audio")) this.el.root.classList.add("idle");
    }, HUD_MS);
  }
}
