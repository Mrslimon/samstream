/** How the video fills the 16:9 screen; persisted per TV in localStorage. */
export type FitMode = "contain" | "cover" | "fill";

export const FIT_MODES: readonly FitMode[] = ["contain", "cover", "fill"];

export const FIT_LABELS: Record<FitMode, string> = {
  contain: "ملاءمة · Fit",
  cover: "ملء مع قص · Fill (crop)",
  fill: "تمديد · Stretch",
};

// AVPlay display methods with the same visual result as the CSS object-fit values.
export const AVPLAY_DISPLAY_MODE: Record<FitMode, string> = {
  contain: "PLAYER_DISPLAY_MODE_LETTER_BOX",
  cover: "PLAYER_DISPLAY_MODE_CROPPED_FULL",
  fill: "PLAYER_DISPLAY_MODE_FULL_SCREEN",
};

const STORAGE_KEY = "samstream.fit";

export function nextFit(current: FitMode, step: 1 | -1): FitMode {
  const index = FIT_MODES.indexOf(current);
  return FIT_MODES[(index + step + FIT_MODES.length) % FIT_MODES.length];
}

export function loadFit(): FitMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return FIT_MODES.find((mode) => mode === stored) ?? "contain";
  } catch {
    return "contain";
  }
}

export function saveFit(mode: FitMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Storage unavailable: the choice just won't survive a restart.
  }
}
