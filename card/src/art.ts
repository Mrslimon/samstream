import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  MAX_ZOOM,
  SCREEN,
  coverCrop,
  matteId,
  matteInset,
  panCrop,
  parseMatte,
  rgb,
  sharpness,
  uploadTarget,
  zoomCrop,
  type ArtListing,
  type Crop,
} from "./art-helpers";
import type { Hass } from "./helpers";
import type { Strings } from "./strings";

const JPEG_QUALITY = 0.92;

interface Editor {
  image: HTMLImageElement;
  url: string;
  crop: Crop;
  zoom: number;
  style: string;
  colour: string;
}

interface ServiceAnswer {
  response: Record<string, ArtListing>;
}

/** The Art section: a Frame's gallery, its border, and a crop-then-upload editor. */
export class SamstreamArt extends LitElement {
  static properties = {
    hass: { attribute: false },
    entity: { type: String },
    text: { attribute: false },
    listing: { state: true },
    editor: { state: true },
    busy: { state: true },
    note: { state: true },
    border: { state: true },
  };

  hass!: Hass;
  entity = "";
  text!: Strings;
  listing: ArtListing | undefined;
  editor: Editor | undefined;
  busy = false;
  note = "";
  /** The border being chosen for the artwork showing now. */
  border: { style: string; colour: string } | undefined;
  private loadedFor = "";
  private drag: { x: number; y: number } | undefined;

  protected updated(changed: PropertyValues): void {
    if (changed.has("entity") && this.entity && this.entity !== this.loadedFor) {
      this.loadedFor = this.entity;
      void this.load();
    }
    if (this.editor) this.draw();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this.editor) URL.revokeObjectURL(this.editor.url);
  }

  private async load(): Promise<void> {
    try {
      const answer = await this.hass.callWS<ServiceAnswer>({
        type: "call_service",
        domain: "samstream",
        service: "list_art",
        service_data: {},
        target: { entity_id: this.entity },
        return_response: true,
      });
      this.listing = answer.response[this.entity];
      this.border = undefined;
    } catch {
      this.note = this.text.artFailed;
    }
  }

  protected render(): TemplateResult {
    const t = this.text;
    return html`
      <section>
        <div class="row">
          <h3>${t.art}</h3>
          <label class="upload">
            <ha-icon icon="mdi:image-plus"></ha-icon>${t.artUpload}
            <input type="file" accept="image/jpeg,image/png" @change=${this.pick} hidden />
          </label>
        </div>
        ${this.editor ? this.renderEditor(this.editor) : this.renderGallery()}
        ${this.note ? html`<p class="hint">${this.note}</p>` : nothing}
      </section>
    `;
  }

  private renderGallery(): TemplateResult {
    const listing = this.listing;
    if (!listing) return html`<p class="hint">…</p>`;
    const current = listing.art.find((item) => item.content_id === listing.current);
    return html`
      <div class="grid">
        ${listing.art.map(
          (item) => html`<button
            class="thumb ${item.content_id === listing.current ? "current" : ""}"
            title=${item.content_id}
            @click=${() => this.show(item.content_id)}
          >
            <span class="name">${item.content_id}</span>
            <img
              src=${item.thumbnail}
              alt=${item.content_id}
              loading="lazy"
              @error=${(event: Event) => ((event.target as HTMLElement).style.visibility = "hidden")}
            />
          </button>`,
        )}
      </div>
      ${current ? this.renderBorder(current.content_id, current.matte_id) : nothing}
    `;
  }

  private renderBorder(contentId: string, matte: string | undefined): TemplateResult {
    const t = this.text;
    const chosen = this.border ?? parseMatte(matte);
    const changed = matteId(chosen.style, chosen.colour) !== (matte ?? "none");
    return html`
      <div class="border">
        <span class="label">${t.artBorder}</span>
        ${this.matteChoices(chosen, (style, colour) => (this.border = { style, colour }))}
        <button
          class="primary"
          ?disabled=${!changed || this.busy}
          @click=${() => this.show(contentId, matteId(chosen.style, chosen.colour))}
        >
          ${t.artApply}
        </button>
      </div>
    `;
  }

  /** Style chips and colour swatches (colours only matter with a border). */
  private matteChoices(
    chosen: { style: string; colour: string },
    choose: (style: string, colour: string) => void,
  ): TemplateResult {
    const mattes = this.listing?.mattes ?? { styles: ["none"], colours: {} };
    const colours = Object.keys(mattes.colours);
    const colour = chosen.colour || colours[0] || "";
    return html`
      <div class="chips">
        ${mattes.styles.map(
          (style) => html`<button
            class="chip ${style === chosen.style ? "selected" : ""}"
            @click=${() => choose(style, colour)}
          >
            ${style === "none" ? this.text.artNoBorder : style}
          </button>`,
        )}
      </div>
      ${chosen.style === "none"
        ? nothing
        : html`<div class="swatches">
            ${colours.map(
              (name) => html`<button
                class="swatch ${name === colour ? "selected" : ""}"
                title=${name}
                style="background:${rgb(mattes.colours[name])}"
                @click=${() => choose(chosen.style, name)}
              ></button>`,
            )}
          </div>`}
    `;
  }

  private renderEditor(editor: Editor): TemplateResult {
    const t = this.text;
    const quality = sharpness(editor.crop);
    const size = `${Math.round(editor.crop.width)}×${Math.round(editor.crop.height)}`;
    return html`
      <p class="hint">${t.artCropHint}</p>
      <canvas
        class="source"
        @pointerdown=${this.dragStart}
        @pointermove=${this.dragMove}
        @pointerup=${this.dragEnd}
        @pointercancel=${this.dragEnd}
      ></canvas>
      <label class="zoom">
        <ha-icon icon="mdi:magnify-plus-outline"></ha-icon>
        <input
          type="range"
          min="1"
          max=${MAX_ZOOM}
          step="0.01"
          .value=${String(editor.zoom)}
          @input=${this.zoomTo}
        />
      </label>
      <div class="quality ${quality}">
        ${quality === "sharp" ? t.artSharp : quality === "fine" ? t.artFine : t.artSoft}
        <span class="size">${size} → ${SCREEN.width}×${SCREEN.height}</span>
      </div>
      <h4>${t.artOnTv}</h4>
      <canvas class="preview"></canvas>
      <span class="label">${t.artBorder}</span>
      ${this.matteChoices(editor, (style, colour) => (this.editor = { ...editor, style, colour }))}
      <div class="actions">
        <button @click=${this.close} ?disabled=${this.busy}>${t.artCancel}</button>
        <button class="primary" @click=${this.upload} ?disabled=${this.busy}>
          ${this.busy ? t.artUploading : t.artUploadShow}
        </button>
      </div>
    `;
  }

  private pick = async (event: Event): Promise<void> => {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } catch {
      URL.revokeObjectURL(url);
      this.note = this.text.artNotPicture;
      return;
    }
    if (this.editor) URL.revokeObjectURL(this.editor.url);
    this.note = "";
    this.editor = {
      image,
      url,
      crop: coverCrop(image.naturalWidth, image.naturalHeight),
      zoom: 1,
      style: "none",
      colour: "",
    };
  };

  private close = (): void => {
    if (this.editor) URL.revokeObjectURL(this.editor.url);
    this.editor = undefined;
  };

  private zoomTo = (event: Event): void => {
    const editor = this.editor;
    if (!editor) return;
    const zoom = Number((event.target as HTMLInputElement).value);
    const { naturalWidth: w, naturalHeight: h } = editor.image;
    this.editor = { ...editor, zoom, crop: zoomCrop(editor.crop, w, h, zoom) };
  };

  private dragStart = (event: PointerEvent): void => {
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    this.drag = { x: event.clientX, y: event.clientY };
  };

  private dragMove = (event: PointerEvent): void => {
    const editor = this.editor;
    if (!this.drag || !editor) return;
    const canvas = event.target as HTMLCanvasElement;
    // Screen pixels to picture pixels: the canvas shows the whole picture.
    const scale = editor.image.naturalWidth / canvas.clientWidth;
    const dx = (event.clientX - this.drag.x) * scale;
    const dy = (event.clientY - this.drag.y) * scale;
    this.drag = { x: event.clientX, y: event.clientY };
    const { naturalWidth: w, naturalHeight: h } = editor.image;
    this.editor = { ...editor, crop: panCrop(editor.crop, dx, dy, w, h) };
  };

  private dragEnd = (): void => {
    this.drag = undefined;
  };

  /** Whole picture with the hidden part dimmed, and the TV preview. */
  private draw(): void {
    const editor = this.editor;
    const source = this.renderRoot.querySelector<HTMLCanvasElement>("canvas.source");
    const preview = this.renderRoot.querySelector<HTMLCanvasElement>("canvas.preview");
    if (!editor || !source || !preview) return;
    const { image, crop } = editor;
    const width = source.clientWidth || 320;
    const scale = width / image.naturalWidth;
    source.width = width * devicePixelRatio;
    source.height = image.naturalHeight * scale * devicePixelRatio;
    source.style.height = `${image.naturalHeight * scale}px`;
    const ctx = source.getContext("2d");
    if (ctx) {
      ctx.setTransform(scale * devicePixelRatio, 0, 0, scale * devicePixelRatio, 0, 0);
      ctx.drawImage(image, 0, 0);
      ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
      const { x, y, width: cw, height: ch } = crop;
      const w = image.naturalWidth;
      const h = image.naturalHeight;
      ctx.fillRect(0, 0, w, y);
      ctx.fillRect(0, y + ch, w, h - y - ch);
      ctx.fillRect(0, y, x, ch);
      ctx.fillRect(x + cw, y, w - x - cw, ch);
      ctx.strokeStyle = "white";
      ctx.lineWidth = 2 / scale;
      ctx.strokeRect(x, y, cw, ch);
      ctx.globalAlpha = 0.35;
      for (const third of [1, 2]) {
        ctx.beginPath();
        ctx.moveTo(x + (cw * third) / 3, y);
        ctx.lineTo(x + (cw * third) / 3, y + ch);
        ctx.moveTo(x, y + (ch * third) / 3);
        ctx.lineTo(x + cw, y + (ch * third) / 3);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    this.drawScreen(preview, preview.clientWidth || 320, editor);
  }

  /** The TV screen: the crop, inside the chosen border's colour. */
  private drawScreen(canvas: HTMLCanvasElement, width: number, editor: Editor): void {
    const height = width / (SCREEN.width / SCREEN.height);
    canvas.width = width * devicePixelRatio;
    canvas.height = height * devicePixelRatio;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    const inset = editor.style === "none" ? 0 : matteInset(editor.style) * width;
    if (inset) {
      ctx.fillStyle = rgb(this.listing?.mattes.colours[editor.colour]);
      ctx.fillRect(0, 0, width, height);
    }
    const { crop, image } = editor;
    ctx.drawImage(
      image,
      crop.x,
      crop.y,
      crop.width,
      crop.height,
      inset,
      inset,
      width - 2 * inset,
      height - 2 * inset,
    );
  }

  /** Crop to exactly the screen size in the browser, then send only that. */
  private upload = async (): Promise<void> => {
    const editor = this.editor;
    const listing = this.listing;
    if (!editor || !listing || !this.hass.fetchWithAuth) return;
    this.busy = true;
    this.note = "";
    try {
      const canvas = document.createElement("canvas");
      canvas.width = SCREEN.width;
      canvas.height = SCREEN.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("no canvas");
      ctx.imageSmoothingQuality = "high";
      const { crop } = editor;
      ctx.drawImage(editor.image, crop.x, crop.y, crop.width, crop.height, 0, 0, SCREEN.width, SCREEN.height);
      const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/jpeg", JPEG_QUALITY));
      if (!blob) throw new Error("no picture");
      const matte = matteId(editor.style, editor.colour);
      const reply = await this.hass.fetchWithAuth(uploadTarget(listing.upload_url, matte, true), {
        method: "POST",
        headers: { "Content-Type": "image/jpeg" },
        body: blob,
      });
      if (!reply.ok) throw new Error(String(reply.status));
      this.close();
      this.note = this.text.artUploaded;
      await this.load();
    } catch {
      this.note = this.text.artFailed;
    } finally {
      this.busy = false;
    }
  };

  private async show(contentId: string, matte?: string): Promise<void> {
    this.busy = true;
    try {
      await this.hass.callService("samstream", "select_art", {
        entity_id: this.entity,
        content_id: contentId,
        ...(matte ? { matte } : {}),
      });
      if (this.listing) this.listing = { ...this.listing, current: contentId };
      if (matte) await this.load();
    } catch {
      this.note = this.text.artFailed;
    } finally {
      this.busy = false;
    }
  }

  static styles = css`
    h3,
    h4 {
      margin: 0;
      font-size: 0.95rem;
      font-weight: 500;
    }
    h4 {
      margin-top: 12px;
      color: var(--secondary-text-color);
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .upload {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      color: var(--primary-color);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
      gap: 6px;
    }
    .thumb {
      padding: 0;
      border: 2px solid transparent;
      border-radius: 6px;
      overflow: hidden;
      background: var(--secondary-background-color);
      cursor: pointer;
      aspect-ratio: 16 / 9;
      position: relative;
    }
    /* Shown when the TV has no thumbnail (some store artwork). */
    .thumb .name {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .thumb.current {
      border-color: var(--primary-color);
    }
    .thumb img {
      position: relative;
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .border {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 12px;
    }
    .label {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
    .chips,
    .swatches {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .chip {
      border: 1px solid var(--divider-color);
      border-radius: 14px;
      padding: 4px 10px;
      background: none;
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .chip.selected {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, white);
    }
    .swatch {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      border: 2px solid var(--divider-color);
      cursor: pointer;
    }
    .swatch.selected {
      border-color: var(--primary-color);
      box-shadow: 0 0 0 2px var(--card-background-color, white) inset;
    }
    canvas {
      width: 100%;
      display: block;
      border-radius: 6px;
      background: #000;
    }
    canvas.source {
      touch-action: none;
      cursor: grab;
    }
    .zoom {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 6px;
    }
    .zoom input {
      flex: 1;
    }
    .quality {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.85rem;
      margin-top: 4px;
    }
    .quality.sharp {
      color: var(--success-color, #2e7d32);
    }
    .quality.soft {
      color: var(--warning-color, #e65100);
    }
    .size {
      color: var(--secondary-text-color);
      direction: ltr;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }
    .actions button,
    .border .primary {
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      padding: 6px 14px;
      background: none;
      color: var(--primary-text-color);
      cursor: pointer;
    }
    button.primary {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, white);
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .border .primary {
      align-self: flex-start;
    }
    .hint {
      margin: 6px 0 0;
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
  `;
}

if (!customElements.get("samstream-art")) customElements.define("samstream-art", SamstreamArt);
