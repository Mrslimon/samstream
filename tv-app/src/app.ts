import { FIT_LABELS, loadFit, nextFit, saveFit } from "./fit";
import { FocusRow } from "./focus";
import { renderHelp } from "./help";
import { applyLanguage, strings, type Language, type Strings } from "./i18n";
import { MsePlayer } from "./mse";
import { scrollWhenLong, showOverlay } from "./overlay";
import { Player, type PlayerCallbacks, type StreamPlayer } from "./player";
import type { LaunchPayload } from "./launch";
import { redactUrl, type CameraStream } from "./streams";

/** How the app reached Home Assistant at start. */
export type Connection = "connected" | "offline" | "none";

const LAST_STREAM_KEY = "samstream.lastStream";

export interface AppElements {
  home: HTMLElement;
  statusText: HTMLElement;
  statusDot: HTMLElement;
  previewText: HTMLElement;
  version: HTMLElement;
  playButton: HTMLButtonElement;
  helpButton: HTMLButtonElement;
  exitButton: HTMLButtonElement;
  player: HTMLElement;
  overlay: HTMLElement;
  live: HTMLElement;
  hud: HTMLElement;
  hudLabel: HTMLElement;
  hudClock: HTMLElement;
  toast: HTMLElement;
  help: HTMLElement;
  debug: HTMLElement;
  video: HTMLVideoElement;
}

const KEY_UP = 38;
const KEY_DOWN = 40;
const KEY_LEFT = 37;
const KEY_RIGHT = 39;
const KEY_ENTER = 13;
const KEY_BACK = 10009;
const KEY_GREEN = 404;
const KEY_YELLOW = 405;
const KEY_INFO = 457;
const KEY_0 = 48;
const KEY_9 = 57;
const HELP_VISIBLE_MS = 10_000;
const TOAST_MS = 2_500;
// The camera name and clock fold away after this; the LIVE badge stays.
const HUD_FULL_MS = 5_000;
const CLOCK_MS = 10_000;

/** Home screen (cards + action bar) and the full-screen player. */
export class App {
  private readonly text: Strings;
  private readonly rtl: boolean;
  private readonly focusRow: FocusRow;
  private readonly native: Player | undefined;
  private readonly mse: MsePlayer;
  private active: StreamPlayer | undefined;
  private playing = false;
  private current = 0;
  private fit = loadFit();
  private debugLines: string[] = [];
  private helpTimer: ReturnType<typeof setTimeout> | undefined;
  private toastTimer: ReturnType<typeof setTimeout> | undefined;
  private hudTimer: ReturnType<typeof setTimeout> | undefined;
  // Opened by HA for a camera: Back and HA's stop close the app, so the TV
  // returns to what was on before. Opened from the TV's app list: Back goes home.
  private fromHa = false;
  /** Called when a stream shows its first frame. */
  onFirstFrame: (() => void) | undefined;
  // Text from Home Assistant shown over the video until the next stream.
  private message = "";

  constructor(
    private readonly el: AppElements,
    private streams: CameraStream[],
    version: string,
    language: Language,
    private readonly connection: Connection = "none",
  ) {
    applyLanguage(document.documentElement, language);
    this.text = strings(language);
    this.rtl = language === "ar";
    this.focusRow = new FocusRow(
      () => [el.playButton, el.helpButton, el.exitButton],
      () => this.rtl,
    );

    const callbacks: PlayerCallbacks = {
      onStatus: (state) => this.log(`${this.streamLabel()}: ${state}`),
      onFirstFrame: (elapsed, info) => {
        this.log(
          `${this.streamLabel()}: FIRST FRAME ${elapsed} ms` +
            (info ? `  ${info.codec} ${info.width}x${info.height}` : ""),
        );
        this.onFirstFrame?.();
      },
      onError: (message) => this.log(`${this.streamLabel()}: ERROR ${message}`),
    };
    const avplay = globalThis.webapis?.avplay;
    this.native = avplay ? new Player(avplay, callbacks) : undefined;
    this.mse = new MsePlayer(el.video, callbacks);
    for (const player of this.players()) player.setFit(this.fit);

    this.renderHome(version);
  }

  start(): void {
    for (let digit = 1; digit <= Math.min(this.streams.length, 9); digit++) {
      globalThis.tizen?.tvinputdevice.registerKey(String(digit));
    }
    for (const key of ["ColorF1Green", "ColorF2Yellow", "Info"]) {
      globalThis.tizen?.tvinputdevice.registerKey(key);
    }
    document.addEventListener("keydown", (event) => this.onKey(event.keyCode));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.active?.stop();
      else if (this.playing) this.play(this.current);
    });
    this.el.playButton.addEventListener("click", () => {
      this.fromHa = false;
      this.play(0);
    });
    this.el.helpButton.addEventListener("click", () =>
      this.showHelp(this.text.helpHome),
    );
    this.el.exitButton.addEventListener("click", () => this.exit());
    this.updateClock();
    setInterval(() => this.updateClock(), CLOCK_MS);
    this.showHome();
  }

  /** Play what Home Assistant sent (at launch, or while already open). */
  playPayload(payload: LaunchPayload): void {
    this.fromHa = true;
    this.message = payload.message;
    if (this.playing && this.streams[this.current]?.url === payload.stream.url) {
      // Same camera already on screen: only the text changes, no reload.
      this.showMessage();
      return;
    }
    this.streams = [
      payload.stream,
      ...this.streams.filter((s) => s.url !== payload.stream.url),
    ];
    this.el.playButton.hidden = false;
    try {
      localStorage.setItem(LAST_STREAM_KEY, JSON.stringify(payload));
    } catch {
      // Storage unavailable: just no "Play camera" after a restart.
    }
    this.play(0);
  }

  /** HA's `stop_stream`: close if HA opened the camera, else back to home. */
  stop(): void {
    if (this.fromHa) this.exit();
    else if (this.playing) this.showHome();
  }

  /** Line for the debug panel (Yellow key). */
  debug(line: string): void {
    this.log(line);
  }

  private renderHome(version: string): void {
    const ready = this.streams.length > 0;
    const status = {
      connected: this.text.statusConnected,
      offline: this.text.statusOffline,
      none: ready ? this.text.statusReady : this.text.statusWaiting,
    }[this.connection];
    this.el.statusText.textContent = status;
    this.el.statusDot.classList.toggle(
      "ready",
      this.connection === "connected" || ready,
    );
    this.el.previewText.textContent = this.text.previewIdle;
    this.el.version.textContent = `v${version}`;
    this.el.playButton.textContent = this.text.playCamera;
    this.el.playButton.hidden = !ready;
    this.el.helpButton.textContent = this.text.help;
    this.el.exitButton.textContent = this.text.exit;
    this.el.live.textContent = this.text.live;
  }

  private onKey(key: number): void {
    if (key === KEY_YELLOW) {
      this.el.debug.hidden = !this.el.debug.hidden;
      return;
    }
    if (key === KEY_GREEN || key === KEY_INFO) {
      this.showHelp(this.playing ? this.text.helpPlayer : this.text.helpHome);
      return;
    }
    if (this.playing) {
      this.onPlayerKey(key);
    } else if (key === KEY_BACK) {
      this.exit();
    } else if (!this.focusRow.move(key) && key === KEY_ENTER) {
      (document.activeElement as HTMLElement | null)?.click();
    }
  }

  private onPlayerKey(key: number): void {
    if (key === KEY_RIGHT) this.play(this.current + 1);
    else if (key === KEY_LEFT) this.play(this.current - 1);
    else if (key === KEY_ENTER) this.play(this.current);
    else if (key > KEY_0 && key <= KEY_9) this.play(key - KEY_0 - 1);
    else if (key === KEY_UP || key === KEY_DOWN) {
      this.fit = nextFit(this.fit, key === KEY_UP ? 1 : -1);
      saveFit(this.fit);
      for (const player of this.players()) player.setFit(this.fit);
      this.toast(FIT_LABELS[this.fit]);
    } else if (key === KEY_BACK) {
      if (this.fromHa) this.exit();
      else this.showHome();
    }
  }

  private play(index: number): void {
    if (this.streams.length === 0) {
      return;
    }
    this.current = (index + this.streams.length) % this.streams.length;
    const stream = this.streams[this.current];
    const player = stream.type === "mse" ? this.mse : this.native;
    this.active?.stop();
    this.playing = true;
    document.body.classList.add("playing");
    this.el.home.hidden = true;
    this.el.player.hidden = false;
    if (!player) {
      this.log("webapis.avplay missing: not running on a Samsung TV");
      return;
    }
    this.active = player;
    this.log(
      `▶ [${this.current + 1}/${this.streams.length}] ${redactUrl(stream.url)}`,
    );
    this.showMessage();
    this.showHud(stream.label ?? "");
    player.play(stream.url, stream.lowLatency === true, stream.audio === true);
  }

  private showHome(): void {
    this.active?.stop();
    this.active = undefined;
    this.playing = false;
    document.body.classList.remove("playing");
    this.el.player.hidden = true;
    this.el.home.hidden = false;
    this.focusRow.focus(0);
  }

  private showHelp(lines: readonly string[]): void {
    renderHelp(this.el.help, this.text.helpTitle, lines);
    this.el.help.hidden = false;
    clearTimeout(this.helpTimer);
    this.helpTimer = setTimeout(
      () => (this.el.help.hidden = true),
      HELP_VISIBLE_MS,
    );
  }

  /** Status pill: LIVE, camera name and time; folds to the badge after a while. */
  private showHud(label: string): void {
    this.el.hudLabel.textContent = label;
    this.el.hud.classList.remove("compact");
    clearTimeout(this.hudTimer);
    this.hudTimer = setTimeout(
      () => this.el.hud.classList.add("compact"),
      HUD_FULL_MS,
    );
  }

  private updateClock(): void {
    this.el.hudClock.textContent = new Date().toLocaleTimeString(
      document.documentElement.lang || undefined,
      {
        hour: "2-digit",
        minute: "2-digit",
      },
    );
  }

  /** Brief chip at the top (fit mode); the HA message stays where it is. */
  private toast(text: string): void {
    this.el.toast.textContent = text;
    this.el.toast.hidden = false;
    // Restart the entry animation for back-to-back toasts.
    this.el.toast.classList.remove("show");
    void this.el.toast.offsetWidth;
    this.el.toast.classList.add("show");
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.el.toast.hidden = true), TOAST_MS);
  }

  private showMessage(): void {
    if (this.message) {
      const card = showOverlay(this.el.overlay, this.message);
      this.el.overlay.hidden = false;
      scrollWhenLong(card);
    } else {
      this.el.overlay.hidden = true;
    }
  }

  private log(line: string): void {
    this.debugLines.unshift(`${new Date().toLocaleTimeString()}  ${line}`);
    this.debugLines = this.debugLines.slice(0, 12);
    this.el.debug.textContent = this.debugLines.join("\n");
    console.log(`[samstream] ${line}`);
  }

  private streamLabel(): string {
    return this.streams[this.current]?.label ?? "";
  }

  private players(): StreamPlayer[] {
    return this.native ? [this.native, this.mse] : [this.mse];
  }

  private exit(): void {
    this.active?.stop();
    globalThis.tizen?.application.getCurrentApplication().exit();
  }
}
