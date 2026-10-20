import type { FitMode } from "./fit";
import type { PlayerCallbacks, StreamPlayer } from "./player";

// Codecs offered to go2rtc; it answers with the subset the camera stream actually uses.
const VIDEO_CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0"];
const AUDIO_CODECS = ["mp4a.40.2", "mp4a.40.5", "flac", "opus"];
const STATS_INTERVAL_MS = 2_000;
const STATS_REPORTS = 10;

// Live edge control: jump forward when we fall behind, drop played data to bound memory.
const MAX_LAG_SECONDS = 1;
const LIVE_EDGE_OFFSET = 0.2;
const KEEP_BACK_SECONDS = 5;
const TRIM_AFTER_SECONDS = 15;

export function supportedCodecs(
  isTypeSupported: (type: string) => boolean,
  withAudio = true,
): string[] {
  const candidates = withAudio ? [...VIDEO_CODECS, ...AUDIO_CODECS] : VIDEO_CODECS;
  return candidates.filter((codec) => isTypeSupported(`video/mp4; codecs="${codec}"`));
}

function describeRanges(ranges: TimeRanges): string {
  const parts: string[] = [];
  for (let i = 0; i < ranges.length; i++) {
    parts.push(`${ranges.start(i).toFixed(1)}-${ranges.end(i).toFixed(1)}`);
  }
  return parts.join(",") || "none";
}

/**
 * Plays a go2rtc stream over its WebSocket MSE protocol (fMP4 remux of the camera's own
 * H.264/H.265, no transcoding): ws://<go2rtc>:1984/api/ws?src=<stream>.
 */
export class MsePlayer implements StreamPlayer {
  private socket: WebSocket | undefined;
  private source: MediaSource | undefined;
  private buffer: SourceBuffer | undefined;
  private queue: ArrayBuffer[] = [];
  private mime = "";
  private bytes = 0;
  private statsTimer: ReturnType<typeof setInterval> | undefined;

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly callbacks: PlayerCallbacks,
  ) {
    video.addEventListener("error", () => {
      const error = video.error;
      if (this.socket && error) {
        this.callbacks.onError(`video error ${error.code} ${error.message}`);
      }
    });
  }

  play(url: string, _lowLatency = false, withAudio = false): void {
    this.stop();
    const started = Date.now();
    this.video.style.display = "block";
    this.startStats();

    const onPlaying = (): void => {
      this.video.removeEventListener("playing", onPlaying);
      this.callbacks.onFirstFrame(Date.now() - started, {
        codec: this.mime,
        width: this.video.videoWidth,
        height: this.video.videoHeight,
      });
    };
    this.video.addEventListener("playing", onPlaying);

    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => {
      const codecs = supportedCodecs((type) => MediaSource.isTypeSupported(type), withAudio);
      this.callbacks.onStatus(`ws open, offering ${codecs.join(",")}`);
      socket.send(JSON.stringify({ type: "mse", value: codecs.join(",") }));
    };
    socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      if (typeof event.data !== "string") {
        this.bytes += event.data.byteLength;
        this.queue.push(event.data);
        this.flush();
        return;
      }
      const message = JSON.parse(event.data) as { type: string; value: string };
      if (message.type === "mse") {
        this.openSource(message.value);
      } else if (message.type === "error") {
        this.callbacks.onError(message.value);
      }
    };
    socket.onerror = () => this.callbacks.onError("websocket error");
    socket.onclose = () => this.callbacks.onStatus("ws closed");
  }

  stop(): void {
    clearInterval(this.statsTimer);
    this.statsTimer = undefined;
    this.bytes = 0;
    if (this.socket) {
      this.socket.onmessage = null;
      this.socket.onclose = null;
      this.socket.close();
      this.socket = undefined;
    }
    if (this.source?.readyState === "open") {
      try {
        this.source.endOfStream();
      } catch {
        // Already ending.
      }
    }
    this.source = undefined;
    this.buffer = undefined;
    this.queue = [];
    this.video.removeAttribute("src");
    this.video.load();
    this.video.style.display = "none";
  }

  setFit(mode: FitMode): void {
    this.video.style.objectFit = mode;
  }

  /** Spike diagnostics: is data arriving, is it buffered, is the clock moving? */
  private startStats(): void {
    let reports = 0;
    this.statsTimer = setInterval(() => {
      const v = this.video;
      this.callbacks.onStatus(
        `rx ${(this.bytes / 1024).toFixed(0)} KB, queue ${this.queue.length}, ` +
          `buffered ${describeRanges(v.buffered)}, t=${v.currentTime.toFixed(1)}, ` +
          `ready=${v.readyState}, paused=${v.paused}`,
      );
      if (++reports >= STATS_REPORTS) {
        clearInterval(this.statsTimer);
      }
    }, STATS_INTERVAL_MS);
  }

  private openSource(mime: string): void {
    this.mime = mime;
    this.callbacks.onStatus(`mse ${mime}`);
    const source = new MediaSource();
    this.source = source;
    this.video.src = URL.createObjectURL(source);
    source.addEventListener("sourceopen", () => {
      URL.revokeObjectURL(this.video.src);
      let buffer: SourceBuffer;
      try {
        buffer = source.addSourceBuffer(mime);
      } catch (error) {
        this.callbacks.onError(`addSourceBuffer(${mime}): ${String(error)}`);
        return;
      }
      buffer.mode = "segments";
      buffer.addEventListener("updateend", () => this.onUpdateEnd());
      buffer.addEventListener("error", () => this.callbacks.onError("sourcebuffer error"));
      this.buffer = buffer;
      this.flush();
      this.video.play().catch((error: unknown) => this.callbacks.onError(`play(): ${String(error)}`));
    });
  }

  private flush(): void {
    const buffer = this.buffer;
    if (!buffer || buffer.updating || this.queue.length === 0) {
      return;
    }
    const next = this.queue.shift();
    if (next) {
      try {
        buffer.appendBuffer(next);
      } catch (error) {
        this.callbacks.onError(`appendBuffer: ${String(error)}`);
      }
    }
  }

  private onUpdateEnd(): void {
    const buffer = this.buffer;
    const ranges = this.video.buffered;
    if (buffer && ranges.length > 0) {
      const start = ranges.start(0);
      const end = ranges.end(ranges.length - 1);
      if (end - this.video.currentTime > MAX_LAG_SECONDS) {
        this.video.currentTime = end - LIVE_EDGE_OFFSET;
      }
      if (this.queue.length === 0 && this.video.currentTime - start > TRIM_AFTER_SECONDS) {
        buffer.remove(start, this.video.currentTime - KEEP_BACK_SECONDS);
        return;
      }
    }
    this.flush();
  }
}
