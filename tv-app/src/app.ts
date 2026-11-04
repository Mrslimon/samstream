import { FIT_LABELS, loadFit, nextFit, saveFit } from "./fit";
import { FocusRow } from "./focus";
import { renderHelp } from "./help";
import { applyLanguage, strings, type Language, type Strings } from "./i18n";
import { MjpegPlayer } from "./mjpeg";
import { MsePlayer } from "./mse";
import { scrollWhenLong, showOverlay } from "./overlay";
import {
  cornerRect,
  hideTvWindow,
  holeClipPath,
  showTvWindow,
  tvSource,
  type Corner,
} from "./pip";
import { Player, type PlayerCallbacks, type StreamPlayer } from "./player";
import type { LaunchPayload } from "./launch";
import type { MediaItem, Notice } from "./notice";
import {
  MediaScreen,
  NoticeScreen,
  type MediaElements,
  type NoticeElements,
} from "./screens";
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
  controls: HTMLElement;
  noticeClock: HTMLElement;
  toast: HTMLElement;
  tvFrame: HTMLElement;
  mjpeg: HTMLImageElement;
  help: HTMLElement;
  debug: HTMLElement;
  video: HTMLVideoElement;
  notice: NoticeElements;
  media: MediaElements;
  sound: HTMLAudioElement;
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
// The YouTube Tizen app, forced when opening a YouTube link (samstream.open_url).
const YOUTUBE_APP_ID = "111299001912";
const HELP_VISIBLE_MS = 10_000;
const TOAST_MS = 2_500;
// The camera name and clock fold away after this; the LIVE badge stays.
const HUD_FULL_MS = 5_000;
const CLOCK_MS = 10_000;
// After a video ends, close ourselves if HA has not taken the TV back by then.
const END_FALLBACK_MS = 5_000;
// How long Back waits for HA to hear about it before closing anyway.
const CLOSE_REPORT_MS = 800;

/** Home screen (cards + action bar) and the full-screen player. */
export class App {
  private readonly text: Strings;
  private readonly rtl: boolean;
  private readonly focusRow: FocusRow;
  private readonly native: Player | undefined;
  private readonly mse: MsePlayer;
  private readonly mjpeg: MjpegPlayer;
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
  /** Called when what HA sent is on screen (first camera frame, notice, video start). */
  onFirstFrame: (() => void) | undefined;
  /** Called when a video from HA's media library ends. */
  onEnded: (() => void) | undefined;
  /** Called before Back closes the app HA opened; resolves when HA has heard. */
  onClosing: (() => Promise<void>) | undefined;
  /** The input in the corner ("TV1", "HDMI2"), reported to HA with the first frame. */
  tvSourceShown: string | undefined;
  private readonly noticeScreen: NoticeScreen;
  private readonly mediaScreen: MediaScreen;
  // A notice or a media file on screen instead of home / camera.
  private screen: "notice" | "media" | undefined;
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
    this.mjpeg = new MjpegPlayer(el.mjpeg, callbacks);
    this.noticeScreen = new NoticeScreen(el.notice, el.sound);
    this.mediaScreen = new MediaScreen(el.media, {
      onStart: () => {
        this.log("media: playing");
        this.onFirstFrame?.();
      },
      onEnd: () => {
        this.log("media: ended");
        this.onEnded?.();
        // HA returns to what was on (and closes us); this is the fallback.
        setTimeout(() => {
          if (this.screen === "media") this.back();
        }, END_FALLBACK_MS);
      },
      onError: (message) => this.log(`media: ERROR ${message}`),
    });
    for (const player of this.players()) player.setFit(this.fit);

    this.renderHome(version);
    this.renderControlLabels();
  }

  start(): void {
    for (let digit = 1; digit <= Math.min(this.streams.length, 9); digit++) {
      globalThis.tizen?.tvinputdevice.registerKey(String(digit));
    }
    for (const key of [
      "ColorF1Green",
      "ColorF2Yellow",
      "Info",
      "MediaPlay",
      "MediaPause",
      "MediaPlayPause",
    ]) {
      globalThis.tizen?.tvinputdevice.registerKey(key);
    }
    document.addEventListener("keydown", (event) => this.onKey(event.keyCode));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.active?.stop();
        this.mediaScreen.pause();
      } else if (this.playing) this.play(this.current);
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
    if (
      this.playing &&
      this.streams[this.current]?.url === payload.stream.url
    ) {
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

  /** A full-screen message (`samstream.show_message`); same title only updates. */
  showNotice(notice: Notice): void {
    this.fromHa = true;
    this.enterScreen("notice");
    this.noticeScreen.show(notice);
    this.onFirstFrame?.();
  }

  /** A video or audio file from HA's media library. */
  playMedia(item: MediaItem): void {
    this.fromHa = true;
    this.enterScreen("media");
    this.log(`▶ media ${item.kind} ${item.title}`);
    this.mediaScreen.show(item);
  }

  /** HA's `stop_stream`: close if HA opened the app, else back to home. */
  stop(): void {
    if (this.fromHa) this.exit();
    else if (this.playing || this.screen) this.showHome();
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

  /** Name the SmartThings-style control hints in the UI language. */
  private renderControlLabels(): void {
    const controls = this.el.controls;
    const label = (dir: string): HTMLElement | null =>
      controls.querySelector<HTMLElement>(`.cam-ctl[data-dir="${dir}"] .cam-label`);
    const names: Record<string, string> = {
      up: this.text.camFit,
      left: this.text.camPrev,
      right: this.text.camNext,
    };
    for (const [dir, name] of Object.entries(names)) {
      const element = label(dir);
      if (element) element.textContent = name;
    }
    const close = controls.querySelector<HTMLElement>(".cam-close-text");
    if (close) close.textContent = this.text.close;
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
    if (this.screen === "notice") {
      if (key === KEY_BACK || key === KEY_ENTER) this.back();
    } else if (this.screen === "media") {
      if (!this.mediaScreen.onKey(key) && key === KEY_BACK) this.back();
    } else if (this.playing) {
      this.onPlayerKey(key);
    } else if (key === KEY_BACK) {
      this.exit();
    } else if (!this.focusRow.move(key) && key === KEY_ENTER) {
      (document.activeElement as HTMLElement | null)?.click();
    }
  }

  private onPlayerKey(key: number): void {
    // Any key wakes the camera chrome (top bar + controls), SmartThings-style.
    // The D-pad drives the triangle: Up = fit, Left = previous, Right = next,
    // Down = close; the matching control lights up so the press is visible.
    this.showHud(this.streamLabel());
    if (key === KEY_RIGHT) {
      this.pressControl("right");
      this.play(this.current + 1);
    } else if (key === KEY_LEFT) {
      this.pressControl("left");
      this.play(this.current - 1);
    } else if (key === KEY_UP) {
      this.pressControl("up");
      this.fit = nextFit(this.fit, 1);
      saveFit(this.fit);
      for (const player of this.players()) player.setFit(this.fit);
      this.toast(FIT_LABELS[this.fit]);
    } else if (key === KEY_ENTER) {
      this.play(this.current);
    } else if (key > KEY_0 && key <= KEY_9) {
      this.play(key - KEY_0 - 1);
    } else if (key === KEY_DOWN || key === KEY_BACK) {
      this.pressControl("down");
      this.back();
    }
  }

  /** Light up the control the pressed D-pad key maps to, and pulse it. */
  private pressControl(dir: "up" | "left" | "right" | "down"): void {
    const controls = this.el.controls;
    if (dir === "down") {
      this.pulse(controls.querySelector<HTMLElement>(".cam-close-hint"));
      return;
    }
    const target = controls.querySelector<HTMLElement>(`.cam-ctl[data-dir="${dir}"]`);
    // Move the "focus" highlight to the direction just pressed.
    for (const ctl of controls.querySelectorAll<HTMLElement>(".cam-ctl")) {
      ctl.classList.toggle("active", ctl === target);
    }
    this.pulse(target);
  }

  /** Re-fire the press animation, even on repeated presses of the same key. */
  private pulse(element: HTMLElement | null): void {
    if (!element) return;
    element.classList.remove("pressed");
    // Force a reflow so removing then adding the class restarts the animation.
    void element.offsetWidth;
    element.classList.add("pressed");
  }

  /** Drop the control highlight so a freshly opened camera starts neutral. */
  private clearControls(): void {
    for (const element of this.el.controls.querySelectorAll<HTMLElement>(
      ".cam-ctl, .cam-close-hint",
    )) {
      element.classList.remove("active", "pressed");
    }
  }

  /** Back from anything HA opened: close the app (TV returns); else home. */
  private back(): void {
    if (!this.fromHa) {
      this.showHome();
      return;
    }
    // Let HA know (it resumes the app underneath), but never hang on it.
    const told = this.onClosing?.() ?? Promise.resolve();
    const timeout = new Promise<void>((resolve) =>
      setTimeout(resolve, CLOSE_REPORT_MS),
    );
    void Promise.race([told, timeout]).then(() => this.exit());
  }

  /** Show a notice or media screen; the camera and home make way. */
  private enterScreen(screen: "notice" | "media"): void {
    this.setTvCorner(undefined);
    this.active?.stop();
    this.active = undefined;
    this.playing = false;
    if (this.screen && this.screen !== screen) this.leaveScreen();
    this.screen = screen;
    document.body.classList.add("playing");
    this.el.home.hidden = true;
    this.el.player.hidden = true;
  }

  private leaveScreen(): void {
    if (this.screen === "notice") this.noticeScreen.hide();
    if (this.screen === "media") this.mediaScreen.hide();
    this.screen = undefined;
  }

  private play(index: number): void {
    if (this.streams.length === 0) {
      return;
    }
    // Opening the camera from home / a notice starts with no control lit; moving
    // between cameras keeps the highlight on the last direction pressed.
    if (!this.playing) this.clearControls();
    this.current = (index + this.streams.length) % this.streams.length;
    const stream = this.streams[this.current];
    // Corner mode: pictures, since a playing video would take the TV's layer.
    const corner =
      stream.tvCorner && stream.mjpegUrl ? stream.tvCorner : undefined;
    const player = corner
      ? this.mjpeg
      : stream.type === "mse"
        ? this.mse
        : this.native;
    this.active?.stop();
    this.leaveScreen();
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
    this.setTvCorner(corner);
    player.play(
      corner ? (stream.mjpegUrl as string) : stream.url,
      stream.lowLatency === true,
      stream.audio === true,
    );
  }

  /**
   * The TV's picture in `corner` (undefined: none). The camera video gets a hole
   * there, the frame outlines it, and the pill and message move out of its way.
   */
  private setTvCorner(corner: Corner | undefined): void {
    const video = this.el.video;
    const frame = this.el.tvFrame;
    // The full control cluster belongs to the full-screen camera, not the corner.
    this.el.controls.hidden = Boolean(corner);
    const clear = () => {
      document.documentElement.classList.remove("tv-corner");
      video.style.clipPath = "";
      this.el.mjpeg.style.clipPath = "";
      frame.hidden = true;
      this.el.hud.style.top = "";
      this.el.overlay.style.bottom = "";
    };
    if (!corner) {
      if (!frame.hidden) hideTvWindow();
      clear();
      return;
    }
    const rect = cornerRect(corner);
    // The TV window draws behind the whole page: nothing opaque may cover it.
    document.documentElement.classList.add("tv-corner");
    video.style.clipPath = holeClipPath(rect);
    this.el.mjpeg.style.clipPath = holeClipPath(rect);
    frame.style.left = `${rect.left}px`;
    frame.style.top = `${rect.top}px`;
    frame.style.width = `${rect.width}px`;
    frame.style.height = `${rect.height}px`;
    frame.hidden = false;
    const hudSide = this.rtl ? "right" : "left";
    if (corner === `top_${hudSide}`)
      this.el.hud.style.top = `${rect.top + rect.height + 24}px`;
    if (corner.startsWith("bottom"))
      this.el.overlay.style.bottom = `${1080 - rect.top + 24}px`;
    void showTvWindow(rect, (line) => this.log(line)).then((shown) => {
      this.log(
        shown
          ? `tv corner: ${corner}`
          : "tv corner: not available, camera only",
      );
      if (!shown) {
        clear();
        return;
      }
      this.tvSourceShown = tvSource();
      this.log(`tv corner source: ${this.tvSourceShown ?? "?"}`);
    });
  }

  private showHome(): void {
    this.setTvCorner(undefined);
    this.active?.stop();
    this.leaveScreen();
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
    this.el.controls.classList.remove("dim");
    clearTimeout(this.hudTimer);
    this.hudTimer = setTimeout(() => {
      this.el.hud.classList.add("compact");
      this.el.controls.classList.add("dim");
    }, HUD_FULL_MS);
  }

  private updateClock(): void {
    this.el.hudClock.textContent = this.el.noticeClock.textContent =
      new Date().toLocaleTimeString(
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
    return this.native
      ? [this.native, this.mse, this.mjpeg]
      : [this.mse, this.mjpeg];
  }

  /**
   * Open another app from inside Samstream (`samstream.open_url`): the YouTube
   * app on a video, or any URL in the TV's browser. Tizen's app-control launch
   * works from the privileged app where the remote channel's launch does not.
   */
  openExternal(target: { youtube?: string; url?: string }): void {
    const tizen = globalThis.tizen;
    if (!tizen?.application?.launchAppControl || !tizen.ApplicationControl) {
      this.log("open: tizen app-control missing (not a Samsung TV)");
      return;
    }
    const view = "http://tizen.org/appcontrol/operation/view";
    const uri = target.youtube
      ? `https://www.youtube.com/watch?v=${target.youtube}`
      : target.url;
    if (!uri) return;
    // A YouTube link is forced to the YouTube app; any other URL lets the TV
    // choose (its browser). Then Samstream drops to the background behind it.
    const appId = target.youtube ? YOUTUBE_APP_ID : null;
    this.active?.stop();
    try {
      tizen.application.launchAppControl(
        new tizen.ApplicationControl(view, uri),
        appId,
        () => this.log(`open: ${uri}`),
        (error) => this.log(`open failed: ${error.name ?? ""} ${error.message ?? ""}`),
      );
    } catch (error) {
      this.log(`open: ${String(error)}`);
    }
  }

  private exit(): void {
    this.setTvCorner(undefined);
    this.active?.stop();
    this.leaveScreen();
    globalThis.tizen?.application.getCurrentApplication().exit();
  }
}
