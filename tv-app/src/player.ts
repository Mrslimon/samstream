import { AVPLAY_DISPLAY_MODE, type FitMode } from "./fit";
import type { AVPlay, AVPlayStreamInfo } from "./tizen";

export interface PlayerCallbacks {
  onStatus(status: string): void;
  onFirstFrame(elapsedMs: number, video: VideoInfo | undefined): void;
  onError(message: string): void;
}

export interface VideoInfo {
  codec: string;
  width: number;
  height: number;
}

/** Common surface of the AVPlay (HLS/HTTP) and MSE (go2rtc WebSocket) players. */
export interface StreamPlayer {
  play(url: string, lowLatency?: boolean, withAudio?: boolean): void;
  stop(): void;
  setFit(mode: FitMode): void;
}

/** Pull codec and resolution out of AVPlay's VIDEO stream info (extra_info is a JSON string). */
export function parseVideoInfo(streams: AVPlayStreamInfo[]): VideoInfo | undefined {
  const video = streams.find((stream) => stream.type === "VIDEO");
  if (!video) {
    return undefined;
  }
  try {
    const extra = JSON.parse(video.extra_info) as Record<string, string>;
    return {
      codec: extra.fourCC ?? "?",
      width: Number(extra.Width ?? 0),
      height: Number(extra.Height ?? 0),
    };
  } catch {
    return undefined;
  }
}

/** Thin AVPlay wrapper: one stream at a time, full screen. */
export class Player implements StreamPlayer {
  private fit: FitMode = "contain";

  constructor(
    private readonly avplay: AVPlay,
    private readonly callbacks: PlayerCallbacks,
  ) {}

  play(url: string, lowLatency = false): void {
    this.stop();
    const started = Date.now();
    let firstFrame = false;

    this.callbacks.onStatus("open");
    this.avplay.open(url);
    this.avplay.setListener({
      onbufferingstart: () => this.callbacks.onStatus("buffering"),
      onbufferingcomplete: () => this.callbacks.onStatus("buffered"),
      // The first play-time tick is the first rendered frame; bufferingcomplete can fire much later.
      oncurrentplaytime: () => {
        if (firstFrame) {
          return;
        }
        firstFrame = true;
        this.callbacks.onFirstFrame(
          Date.now() - started,
          parseVideoInfo(this.avplay.getCurrentStreamInfo()),
        );
      },
      onstreamcompleted: () => this.callbacks.onStatus("ended"),
      onevent: (type, data) => this.callbacks.onStatus(`event ${type} ${data}`),
      onerror: (type) => this.callbacks.onError(type),
    });
    this.avplay.setDisplayRect(0, 0, 1920, 1080);
    this.applyFit();
    if (lowLatency) {
      // Live camera: keep the play buffer as small as the firmware allows.
      try {
        this.avplay.setBufferingParam(
          "PLAYER_BUFFER_FOR_PLAY",
          "PLAYER_BUFFER_SIZE_IN_SECOND",
          1,
        );
        this.avplay.setTimeoutForBuffering(10);
      } catch (error) {
        this.callbacks.onStatus(`buffering params rejected: ${describe(error)}`);
      }
    }
    this.avplay.prepareAsync(
      () => {
        this.callbacks.onStatus("prepared");
        this.avplay.play();
      },
      (error) => this.callbacks.onError(`prepare failed: ${describe(error)}`),
    );
  }

  stop(): void {
    const state = this.avplay.getState();
    if (state === "PLAYING" || state === "PAUSED" || state === "READY") {
      this.avplay.stop();
    }
    if (state !== "NONE") {
      this.avplay.close();
    }
  }

  setFit(mode: FitMode): void {
    this.fit = mode;
    if (this.avplay.getState() !== "NONE") {
      this.applyFit();
    }
  }

  private applyFit(): void {
    try {
      this.avplay.setDisplayMethod(AVPLAY_DISPLAY_MODE[this.fit]);
    } catch (error) {
      this.callbacks.onStatus(`fit ${this.fit} rejected: ${describe(error)}`);
    }
  }
}

function describe(error: unknown): string {
  if (error && typeof error === "object" && "name" in error) {
    const { name, message } = error as { name: unknown; message?: unknown };
    return message ? `${String(name)}: ${String(message)}` : String(name);
  }
  return String(error);
}
