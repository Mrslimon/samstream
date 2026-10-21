/**
 * The TV's own picture (Live TV or an HDMI input) in a corner, while the camera
 * plays full screen around it.
 *
 * Samsung's TV Window API shows the TV source in a window behind the page. A
 * small window stays inside Samstream; a full-screen one makes the TV bring Live
 * TV itself to the front (tested on the QN800C), so only corners are offered.
 */

export type Corner = "top_left" | "top_right" | "bottom_left" | "bottom_right";

export const CORNERS: readonly Corner[] = ["top_left", "top_right", "bottom_left", "bottom_right"];

const WIDTH = 640;
const HEIGHT = 360;
const MARGIN = 64;
const SCREEN = { width: 1920, height: 1080 };

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function cornerRect(corner: Corner): Rect {
  const right = corner.endsWith("right");
  const bottom = corner.startsWith("bottom");
  return {
    left: right ? SCREEN.width - MARGIN - WIDTH : MARGIN,
    top: bottom ? SCREEN.height - MARGIN - HEIGHT : MARGIN,
    width: WIDTH,
    height: HEIGHT,
  };
}

/** clip-path for the camera video: everything but `rect` (the TV shows there). */
export function holeClipPath(rect: Rect): string {
  const x1 = rect.left;
  const y1 = rect.top;
  const x2 = rect.left + rect.width;
  const y2 = rect.top + rect.height;
  const outer = "0 0, 100% 0, 100% 100%, 0 100%, 0 0";
  const inner = `${x1}px ${y1}px, ${x1}px ${y2}px, ${x2}px ${y2}px, ${x2}px ${y1}px, ${x1}px ${y1}px`;
  return `polygon(evenodd, ${outer}, ${inner})`;
}

/** Show the TV's source in `rect`; resolves false if the TV refuses. */
export function showTvWindow(rect: Rect, log: (line: string) => void): Promise<boolean> {
  const tvwindow = globalThis.tizen?.tvwindow;
  if (!tvwindow) {
    log("tv corner: tizen.tvwindow missing");
    return Promise.resolve(false);
  }
  const area = [rect.left, rect.top, rect.width, rect.height].map((value) => `${value}px`);
  return new Promise((resolve) => {
    try {
      tvwindow.show(
        () => resolve(true),
        (error) => {
          log(`tv corner refused: ${error.name} ${error.message}`);
          resolve(false);
        },
        area,
        "MAIN",
      );
    } catch (error) {
      log(`tv corner: ${String(error)}`);
      resolve(false);
    }
  });
}

export function hideTvWindow(): void {
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
