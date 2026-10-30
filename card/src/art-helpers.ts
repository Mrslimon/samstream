/** Frame art: what the card's picker and uploader need, kept free of the DOM. */

/** The Frame's screen: 4K, landscape. Uploads are cropped to exactly this. */
export const SCREEN = { width: 3840, height: 2160 } as const;
export const ASPECT = SCREEN.width / SCREEN.height;
/** Zooming in further leaves too few pixels for a 4K screen to look right. */
export const MAX_ZOOM = 4;

/** A rectangle of the source picture, in its own pixels. */
export interface Crop {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ArtItem {
  content_id: string;
  category_id?: string;
  width?: number;
  height?: number;
  matte_id?: string;
  thumbnail: string;
}

export interface ArtListing {
  current: string | null;
  art: ArtItem[];
  mattes: { styles: string[]; colours: Record<string, [number, number, number]> };
  upload_url: string;
}

/** The largest screen-shaped part of the picture, centred (zoom 1). */
export function coverCrop(imageWidth: number, imageHeight: number): Crop {
  const width = Math.min(imageWidth, imageHeight * ASPECT);
  const height = width / ASPECT;
  return { x: (imageWidth - width) / 2, y: (imageHeight - height) / 2, width, height };
}

/** Keep a crop inside the picture. */
export function clampCrop(crop: Crop, imageWidth: number, imageHeight: number): Crop {
  return {
    ...crop,
    x: Math.min(Math.max(crop.x, 0), imageWidth - crop.width),
    y: Math.min(Math.max(crop.y, 0), imageHeight - crop.height),
  };
}

/** Zoom (1 = the whole cover crop) around the current crop's centre. */
export function zoomCrop(crop: Crop, imageWidth: number, imageHeight: number, zoom: number): Crop {
  const cover = coverCrop(imageWidth, imageHeight);
  const z = Math.min(Math.max(zoom, 1), MAX_ZOOM);
  const width = cover.width / z;
  const height = width / ASPECT;
  const cx = crop.x + crop.width / 2;
  const cy = crop.y + crop.height / 2;
  return clampCrop({ x: cx - width / 2, y: cy - height / 2, width, height }, imageWidth, imageHeight);
}

/** Move the crop by a drag measured in picture pixels. */
export function panCrop(crop: Crop, dx: number, dy: number, imageWidth: number, imageHeight: number): Crop {
  return clampCrop({ ...crop, x: crop.x + dx, y: crop.y + dy }, imageWidth, imageHeight);
}

/** How sharp the crop will look on the 4K screen. */
export type Sharpness = "sharp" | "fine" | "soft";
export function sharpness(crop: Crop): Sharpness {
  if (crop.width >= SCREEN.width * 0.95) return "sharp";
  if (crop.width >= SCREEN.width / 2) return "fine";
  return "soft";
}

/** Border id the TV takes: `none` or `<style>_<colour>`. */
export function matteId(style: string, colour: string): string {
  return style === "none" || !colour ? "none" : `${style}_${colour}`;
}

export function parseMatte(id: string | undefined): { style: string; colour: string } {
  if (!id || id === "none") return { style: "none", colour: "" };
  const cut = id.lastIndexOf("_");
  return cut < 0 ? { style: id, colour: "" } : { style: id.slice(0, cut), colour: id.slice(cut + 1) };
}

/**
 * Border width in the preview, as a share of the screen width. The TV draws
 * its own mats; this only shows roughly how much of the picture they cover.
 */
const MATTE_INSET: Record<string, number> = {
  none: 0,
  modernthin: 0.04,
  modern: 0.07,
  modernwide: 0.1,
  flexible: 0.07,
  shadowbox: 0.08,
  panoramic: 0.1,
  triptych: 0.08,
  mix: 0.07,
  squares: 0.07,
};
export function matteInset(style: string): number {
  return MATTE_INSET[style] ?? 0.07;
}

export function rgb(colour: [number, number, number] | undefined): string {
  return colour ? `rgb(${colour[0]}, ${colour[1]}, ${colour[2]})` : "transparent";
}

/** The upload address with its border and "show it now". */
export function uploadTarget(base: string, matte: string, show: boolean): string {
  const query = new URLSearchParams({ matte });
  if (show) query.set("show", "1");
  return `${base}?${query.toString()}`;
}
