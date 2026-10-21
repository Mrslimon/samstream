/**
 * Picture in picture over Live TV (milestone 17 spike).
 *
 * A web app cannot draw over another app, but Samsung's TV Window API shows the
 * TV's own source (tuner or HDMI) inside our app. With it full screen behind a
 * transparent page, the camera sits in a corner on top of the broadcast.
 */

const FULL_SCREEN = ["0px", "0px", "1920px", "1080px"];

/** Show the TV's source full screen; resolves false if the TV refuses. */
export function showLiveTv(log: (line: string) => void): Promise<boolean> {
  const tvwindow = globalThis.tizen?.tvwindow;
  if (!tvwindow) {
    log("pip: tizen.tvwindow missing");
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    try {
      try {
        const source = tvwindow.getSource("MAIN");
        log(`pip: source ${source.type} ${source.number}`);
      } catch (error) {
        log(`pip: getSource failed: ${String(error)}`);
      }
      tvwindow.show(
        (rect) => {
          log(`pip: tv window ${rect.join(" ")}`);
          resolve(true);
        },
        (error) => {
          log(`pip: show refused: ${error.name} ${error.message}`);
          resolve(false);
        },
        FULL_SCREEN,
        "MAIN",
      );
    } catch (error) {
      log(`pip: show threw: ${String(error)}`);
      resolve(false);
    }
  });
}

export function hideLiveTv(): void {
  try {
    globalThis.tizen?.tvwindow?.hide(
      () => undefined,
      () => undefined,
      "MAIN",
    );
  } catch {
    // Not shown, or no TV Window API.
  }
}
