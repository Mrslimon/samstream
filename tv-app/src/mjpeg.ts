import type { FitMode } from "./fit";
import type { PlayerCallbacks, StreamPlayer } from "./player";

/**
 * The camera as a picture stream (multipart MJPEG) in an ordinary <img>.
 *
 * Used while the TV's own picture is in a corner: a playing <video> takes the
 * TV's one hardware video layer, which the TV window needs; an image is drawn
 * like any web content, so both show at once.
 */
export class MjpegPlayer implements StreamPlayer {
  private started = 0;

  constructor(
    private readonly image: HTMLImageElement,
    private readonly callbacks: PlayerCallbacks,
  ) {
    image.addEventListener("load", () => {
      // Multipart streams fire load once per frame on some engines: report once.
      if (this.started) {
        this.callbacks.onFirstFrame(Date.now() - this.started, {
          codec: "mjpeg",
          width: image.naturalWidth,
          height: image.naturalHeight,
        });
        this.started = 0;
      }
    });
    image.addEventListener("error", () => {
      if (image.getAttribute("src")) this.callbacks.onError("picture stream error");
    });
  }

  play(url: string): void {
    this.stop();
    this.started = Date.now();
    this.image.style.display = "block";
    this.image.src = url;
    this.callbacks.onStatus("picture stream (TV in a corner)");
  }

  stop(): void {
    this.started = 0;
    this.image.removeAttribute("src");
    this.image.style.display = "none";
  }

  setFit(mode: FitMode): void {
    this.image.style.objectFit = mode;
  }
}
