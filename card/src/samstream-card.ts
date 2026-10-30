import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  SECTIONS,
  cameraList,
  deviceButtons,
  friendlyName,
  initials,
  sectionsOf,
  tileColor,
  type AppsAnswer,
  type Hass,
  type Section,
  type TvApp,
  POINTER_SCALE,
  touchGesture,
} from "./helpers";
import { languageOf, strings, type Strings } from "./strings";
import "./art";

export interface CardConfig {
  type: string;
  entity: string;
  cameras?: string[];
  /** Sections in order: tv, cameras, message, apps, remote, media. */
  sections?: string[];
  show_cameras?: boolean;
  show_message?: boolean;
  show_apps?: boolean;
  show_remote?: boolean;
}

type Severity = "info" | "warning" | "alert";
const SEVERITIES: Severity[] = ["info", "warning", "alert"];
const FEEDBACK_MS = 3_000;
// Held buttons: arrows and volume repeat; OK / Back / Home send a long press.
const REPEAT_AFTER_MS = 400;
const REPEAT_EVERY_MS = 150;
const LONG_PRESS_MS = 600;
const LONG_PRESS_SECONDS = 1.5;
// One pointer move in flight at a time; movement meanwhile is summed and sent
// as soon as the TV has the previous one, so a drag never queues up behind.
const POINTER_FLUSH_MS = 16;
// A long press on touch screens must not open the browser's menu.
const noMenu = (event: Event) => event.preventDefault();

/** custom:samstream-card: the TV, its cameras, messages, apps and a remote. */
export class SamstreamCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    config: { state: true },
    apps: { state: true },
    camera: { state: true },
    feedback: { state: true },
    severity: { state: true },
    volumeDrag: { state: true },
  };

  hass!: Hass;
  config!: CardConfig;
  apps: AppsAnswer | undefined;
  camera = "";
  feedback = "";
  severity: Severity = "info";
  // While the volume slider is being dragged: the percentage to show, so the
  // label leads the TV instead of waiting for the next (up to 10 s) poll.
  volumeDrag: number | undefined;
  private appsFor: string | undefined;
  private feedbackTimer: ReturnType<typeof setTimeout> | undefined;
  private holdTimer: ReturnType<typeof setTimeout> | undefined;
  private repeatTimer: ReturnType<typeof setInterval> | undefined;
  private held = false;
  private touch: { x: number; y: number; at: number; travel: number } | undefined;
  private pending = { x: 0, y: 0 };
  private flushTimer: ReturnType<typeof setTimeout> | undefined;
  private pointerBusy = false;

  setConfig(config: CardConfig): void {
    if (!config.entity) throw new Error("Choose the Samstream TV (media player).");
    this.config = config;
  }

  getCardSize(): number {
    return 8;
  }

  static getConfigForm() {
    const text = (hass?: Hass) => strings(languageOf(hass?.locale?.language ?? hass?.language));
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "media_player", integration: "samstream" } },
        },
        {
          name: "sections",
          selector: {
            select: {
              multiple: true,
              reorder: true,
              mode: "list",
              options: SECTIONS.map((value) => ({ value, label: text()[sectionKey(value)] })),
            },
          },
        },
        { name: "cameras", selector: { entity: { domain: "camera", multiple: true } } },
      ],
      computeLabel: (field: { name: string }, hass?: Hass) => {
        const t = text(hass);
        if (field.name === "sections") return t.sections;
        if (field.name === "cameras") return t.camerasField;
        return undefined;
      },
    };
  }

  static getStubConfig(hass: Hass): Partial<CardConfig> {
    const tv = Object.values(hass.entities ?? {}).find(
      (entry) => entry.platform === "samstream" && entry.entity_id.startsWith("media_player."),
    );
    return { entity: tv?.entity_id ?? "", sections: ["tv", "cameras", "message", "apps", "remote", "media"] };
  }

  private get text(): Strings {
    return strings(languageOf(this.hass?.locale?.language ?? this.hass?.language));
  }

  private get rtl(): boolean {
    return languageOf(this.hass?.locale?.language ?? this.hass?.language) === "ar";
  }

  protected updated(changed: PropertyValues): void {
    if (!changed.has("hass") || !this.hass || !this.config) return;
    // Refresh the app list when the app on screen changes, or a TV button was
    // pressed (a button's state is its last press: "Download app logos").
    const appId = (this.hass.states[this.config.entity]?.attributes.app_id as string) ?? null;
    const key = `${appId}|${deviceButtons(this.hass, this.config.entity)}`;
    if (this.apps === undefined || key !== this.appsFor) {
      this.appsFor = key;
      this.loadApps();
    }
    // Drop the held slider value once the TV reports the level we set.
    if (this.volumeDrag !== undefined) {
      const level = this.hass.states[this.config.entity]?.attributes.volume_level;
      if (typeof level === "number" && Math.round(level * 100) === this.volumeDrag) {
        this.volumeDrag = undefined;
      }
    }
  }

  private loadApps(): void {
    this.hass
      .callWS<AppsAnswer>({ type: "samstream/apps", entity_id: this.config.entity })
      .then((answer) => (this.apps = answer))
      .catch(() => (this.apps = { home: "Home", current: null, apps: [] }));
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this.hass || !this.config) return nothing;
    const state = this.hass.states[this.config.entity];
    if (!state) {
      return html`<ha-card><div class="empty">${this.config.entity}?</div></ha-card>`;
    }
    const on = state.state !== "off" && state.state !== "unavailable";
    const sections = sectionsOf(this.config);
    // Off: only the power control works; keep one even without the TV section.
    const frame = state.attributes.frame_tv === true;
    const shown = (on ? sections : sections.includes("tv") ? ["tv" as Section] : []).filter(
      (section) => section !== "art" || frame,
    );
    return html`
      <ha-card dir=${this.rtl ? "rtl" : "ltr"}>
        ${on || shown.length > 0 ? nothing : this.renderPowerOnly()}
        ${shown.map((section, index) => this.renderSection(section, on, index === 0))}
        ${this.feedback ? html`<div class="feedback">${this.feedback}</div>` : nothing}
      </ha-card>
    `;
  }

  private renderSection(section: Section, on: boolean, first: boolean): TemplateResult {
    const body = {
      tv: () => this.renderHeader(on),
      cameras: () => this.renderCameras(),
      message: () => this.renderMessage(),
      apps: () => this.renderApps(),
      remote: () => this.renderRemote(),
      media: () => this.renderMedia(),
      keyboard: () => this.renderKeyboard(),
      touchpad: () => this.renderTouchpad(),
      art: () =>
        html`<samstream-art .hass=${this.hass} .entity=${this.config.entity} .text=${this.text}></samstream-art>`,
    }[section]();
    return html`<div class="section ${first ? "first" : ""}">${body}</div>`;
  }

  private renderPowerOnly(): TemplateResult {
    return html`<div class="power-only">
      <span>${friendlyName(this.hass, this.config.entity)} · ${this.text.off}</span>
      ${this.powerButton(false)}
    </div>`;
  }

  private powerButton(on: boolean): TemplateResult {
    return html`<button
      class="round ${on ? "on" : ""}"
      title=${this.text.power}
      @click=${() => this.call("media_player", "toggle", { entity_id: this.config.entity })}
    >
      <ha-icon icon="mdi:power"></ha-icon>
    </button>`;
  }

  private renderHeader(on: boolean): TemplateResult {
    const t = this.text;
    const state = this.hass.states[this.config.entity];
    const source = (state.attributes.source as string | undefined) ?? "";
    const appId = state.attributes.app_id as string | undefined;
    const app = this.apps?.apps.find((a) => a.id === appId);
    const subtitle = !on ? t.off : source === "Home" ? t.home : (app?.name ?? source);
    return html`
      <div class="header">
        ${app ? this.tile(app, "small") : html`<div class="tv"><ha-icon icon="mdi:television"></ha-icon></div>`}
        <div class="titles">
          <div class="name">${friendlyName(this.hass, this.config.entity)}</div>
          <div class="sub">${subtitle}</div>
        </div>
        ${this.powerButton(on)}
      </div>
    `;
  }

  private renderCameras(): TemplateResult {
    const t = this.text;
    const cameras = cameraList(this.hass, this.config.cameras);
    if (cameras.length === 0) {
      return html`<section><h3>${t.cameras}</h3><p class="hint">${t.noCameras}</p></section>`;
    }
    const selected = cameras.includes(this.camera) ? this.camera : cameras[0];
    return html`
      <section>
        <h3>${t.cameras}</h3>
        <div class="chips">
          ${cameras.map(
            (id) => html`<button
              class="chip ${id === selected ? "selected" : ""}"
              @click=${() => (this.camera = id)}
            >
              <ha-icon icon="mdi:cctv"></ha-icon>${friendlyName(this.hass, id)}
            </button>`,
          )}
        </div>
        <div class="row">
          <input id="camera-message" dir="auto" placeholder=${t.messagePlaceholder} />
          <label class="duration"
            ><input id="camera-duration" type="number" min="1" placeholder="—" /><span
              >${t.seconds}</span
            ></label
          >
        </div>
        <label class="check">
          <input id="camera-tv-corner" type="checkbox" />
          <span>${t.tvCorner}</span>
        </label>
        <div class="actions">
          <button class="primary" @click=${() => this.playCamera(selected)}>
            <ha-icon icon="mdi:television-play"></ha-icon>${t.showCamera}
          </button>
          <button @click=${() => this.call("samstream", "stop_stream", { entity_id: this.config.entity })}>
            <ha-icon icon="mdi:stop"></ha-icon>${t.stop}
          </button>
        </div>
      </section>
    `;
  }

  private renderMessage(): TemplateResult {
    const t = this.text;
    const labels: Record<Severity, string> = { info: t.info, warning: t.warning, alert: t.alert };
    return html`
      <section>
        <h3>${t.message}</h3>
        <input id="notice-title" dir="auto" placeholder=${t.title} />
        <textarea id="notice-message" dir="auto" rows="2" placeholder=${t.messagePlaceholder}></textarea>
        <div class="row">
          <div class="chips">
            ${SEVERITIES.map(
              (severity) => html`<button
                class="chip ${severity} ${severity === this.severity ? "selected" : ""}"
                @click=${() => (this.severity = severity)}
              >
                ${labels[severity]}
              </button>`,
            )}
          </div>
          <label class="duration"
            ><input id="notice-duration" type="number" min="1" placeholder="—" /><span
              >${t.seconds}</span
            ></label
          >
        </div>
        <div class="actions">
          <button class="primary" @click=${() => this.showNotice()}>
            <ha-icon icon="mdi:message-alert"></ha-icon>${t.showMessage}
          </button>
          <button @click=${() => this.updateText()}>
            <ha-icon icon="mdi:message-text"></ha-icon>${t.updateText}
          </button>
        </div>
      </section>
    `;
  }

  private renderApps(): TemplateResult {
    const t = this.text;
    const state = this.hass.states[this.config.entity];
    const current = state.attributes.app_id as string | undefined;
    const atHome = state.attributes.source === "Home";
    const home: TvApp = { id: "__home__", name: t.home, logo: null };
    return html`
      <section>
        <h3>${t.apps}</h3>
        <div class="apps">
          <button
            class="app ${atHome ? "current" : ""}"
            @click=${() => this.selectSource(this.apps?.home ?? "Home")}
          >
            <div class="tile home"><ha-icon icon="mdi:home"></ha-icon></div>
            <span>${home.name}</span>
          </button>
          ${(this.apps?.sources ?? []).map(
            (source) => html`<button
              class="app ${state.attributes.source === source ? "current" : ""}"
              @click=${() => this.selectSource(source)}
            >
              <div class="tile home">
<ha-icon icon=${sourceIcon(source)}></ha-icon>
              </div>
              <span>${source === "Live TV" ? t.liveTv : source === "Input list" ? t.inputList : source}</span>
            </button>`,
          )}
          ${(this.apps?.apps ?? []).map(
            (app) => html`<button
              class="app ${app.id === current ? "current" : ""}"
              title=${app.name}
              @click=${() => this.selectSource(app.name)}
            >
              ${this.tile(app, "large")}<span dir="auto">${app.name}</span>
            </button>`,
          )}
        </div>
      </section>
    `;
  }

  private renderRemote(): TemplateResult {
    const t = this.text;
    const key = (code: string, icon: string, label: string, mode: "repeat" | "hold" = "repeat") => {
      const k = this.pressable(() => this.sendKey(code), mode, code);
      return html`<button class="key" title=${label} @pointerdown=${k.down} @pointerup=${k.up} @pointerleave=${k.cancel} @pointercancel=${k.cancel} @contextmenu=${noMenu}>
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
    };
    const ok = this.pressable(() => this.sendKey("KEY_ENTER"), "hold", "KEY_ENTER");
    // Arrows keep their physical meaning; only the layout mirrors in RTL.
    return html`
      <section>
        <h3>${t.remote}</h3>
        <div class="remote">
          <div class="pad">
            <span></span>${key("KEY_UP", "mdi:chevron-up", "▲")}<span></span>
            ${key(this.rtl ? "KEY_RIGHT" : "KEY_LEFT", this.rtl ? "mdi:chevron-right" : "mdi:chevron-left", "◀")}
            <button class="key ok" @pointerdown=${ok.down} @pointerup=${ok.up} @pointerleave=${ok.cancel} @pointercancel=${ok.cancel} @contextmenu=${noMenu}>
              ${t.ok}
            </button>
            ${key(this.rtl ? "KEY_LEFT" : "KEY_RIGHT", this.rtl ? "mdi:chevron-left" : "mdi:chevron-right", "▶")}
            <span></span>${key("KEY_DOWN", "mdi:chevron-down", "▼")}<span></span>
          </div>
          <div class="side">
            ${key("KEY_RETURN", "mdi:arrow-u-left-top", t.back, "hold")}
            ${key("KEY_HOME", "mdi:home", t.home, "hold")}
            ${key("KEY_MENU", "mdi:menu", t.menu, "hold")}
          </div>
        </div>
      </section>
    `;
  }

  private renderMedia(): TemplateResult {
    const t = this.text;
    const media = (service: string, icon: string, label: string, repeat = false) => {
      const send = () => this.call("media_player", service, { entity_id: this.config.entity }, false);
      const k = this.pressable(send, "repeat");
      return repeat
        ? html`<button class="key" title=${label} @pointerdown=${k.down} @pointerup=${k.up} @pointerleave=${k.cancel} @pointercancel=${k.cancel} @contextmenu=${noMenu}>
            <ha-icon icon=${icon}></ha-icon>
          </button>`
        : html`<button class="key" title=${label} @click=${send}><ha-icon icon=${icon}></ha-icon></button>`;
    };
    const volume = this.hass.states[this.config.entity]?.attributes.volume_level;
    const hasVolume = typeof volume === "number";
    const shown = this.volumeDrag ?? (hasVolume ? Math.round(volume * 100) : 0);
    const onSlide = (event: Event) => {
      this.volumeDrag = Number((event.target as HTMLInputElement).value);
    };
    return html`
      <section>
        <h3>${t.media}</h3>
        <div class="media">
          ${media("media_play_pause", "mdi:play-pause", t.playPause)}
          <button class="key" title=${t.mute} @click=${() => this.toggleMute()}>
            <ha-icon icon="mdi:volume-off"></ha-icon>
          </button>
          <input
            class="volume"
            type="range"
            min="0"
            max="100"
            step="1"
            aria-label=${t.volume}
            .value=${String(shown)}
            ?disabled=${!hasVolume}
            @input=${onSlide}
            @change=${(event: Event) =>
              this.setVolume(Number((event.target as HTMLInputElement).value))}
          />
          <span class="level">${hasVolume || this.volumeDrag !== undefined ? shown : "–"}</span>
        </div>
      </section>
    `;
  }

  private setVolume(percent: number): void {
    this.volumeDrag = Math.min(100, Math.max(0, Math.round(percent)));
    this.call(
      "media_player",
      "volume_set",
      { entity_id: this.config.entity, volume_level: this.volumeDrag / 100 },
      false,
    );
  }

  private renderKeyboard(): TemplateResult {
    const t = this.text;
    const send = () => {
      const text = this.value("tv-text");
      if (!text) return;
      this.call("samstream", "send_text", { entity_id: this.config.entity, text });
      const field = this.renderRoot.querySelector<HTMLInputElement>("#tv-text");
      if (field) field.value = "";
    };
    return html`
      <section>
        <h3>${t.keyboard}</h3>
        <div class="row">
          <input
            id="tv-text"
            dir="auto"
            placeholder=${t.typeHere}
            @keydown=${(event: KeyboardEvent) => event.key === "Enter" && send()}
          />
          <button class="primary" @click=${send}><ha-icon icon="mdi:keyboard"></ha-icon>${t.send}</button>
        </div>
        <p class="hint">${t.keyboardNote}</p>
      </section>
    `;
  }

  private renderTouchpad(): TemplateResult {
    const t = this.text;
    return html`
      <section>
        <h3>${t.touchpad}</h3>
        <div
          class="touchpad"
          @pointerdown=${(event: PointerEvent) => this.touchStart(event)}
          @pointermove=${(event: PointerEvent) => this.touchMove(event)}
          @pointerup=${() => this.touchEnd()}
          @pointercancel=${() => (this.touch = undefined)}
          @contextmenu=${(event: Event) => event.preventDefault()}
        >
          <span>${t.touchpadHint}</span>
        </div>
        <div class="actions">
          <button @click=${() => this.pointer({ click: "left" })}>
            <ha-icon icon="mdi:cursor-default-click"></ha-icon>${t.leftClick}
          </button>
          <button @click=${() => this.pointer({ click: "right" })}>
            <ha-icon icon="mdi:mouse-right-click"></ha-icon>${t.rightClick}
          </button>
        </div>
        <p class="hint">${t.touchpadNote}</p>
      </section>
    `;
  }

  /**
   * Button press handling: `repeat` sends now and keeps sending while held;
   * `hold` sends a click on release, or a long press (`hold_key`) when held.
   */
  private pressable(send: () => void, mode: "repeat" | "hold", key?: string) {
    const stop = () => {
      clearTimeout(this.holdTimer);
      clearInterval(this.repeatTimer);
    };
    const down = (event: PointerEvent) => {
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
      stop();
      this.held = false;
      if (mode === "repeat") {
        send();
        this.holdTimer = setTimeout(() => {
          this.repeatTimer = setInterval(send, REPEAT_EVERY_MS);
        }, REPEAT_AFTER_MS);
      } else {
        this.holdTimer = setTimeout(() => {
          this.held = true;
          if (key) {
            this.call(
              "samstream",
              "hold_key",
              { entity_id: this.config.entity, key, seconds: LONG_PRESS_SECONDS },
              false,
            );
          }
        }, LONG_PRESS_MS);
      }
    };
    const up = () => {
      stop();
      if (mode === "hold" && !this.held) send();
      this.held = false;
    };
    const cancel = () => {
      stop();
      this.held = false;
    };
    return { down, up, cancel };
  }

  private touchStart(event: PointerEvent): void {
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    this.touch = { x: event.clientX, y: event.clientY, at: Date.now(), travel: 0 };
  }

  private touchMove(event: PointerEvent): void {
    const touch = this.touch;
    if (!touch) return;
    const dx = event.clientX - touch.x;
    const dy = event.clientY - touch.y;
    touch.x = event.clientX;
    touch.y = event.clientY;
    touch.travel += Math.abs(dx) + Math.abs(dy);
    // In RTL the pad is still a physical surface: no mirroring.
    this.pending.x += dx * POINTER_SCALE;
    this.pending.y += dy * POINTER_SCALE;
    if (!this.flushTimer && !this.pointerBusy) {
      this.flushTimer = setTimeout(() => this.flushPointer(), POINTER_FLUSH_MS);
    }
  }

  private touchEnd(): void {
    const touch = this.touch;
    this.touch = undefined;
    if (!touch) return;
    const gesture = touchGesture(touch.travel, Date.now() - touch.at);
    if (gesture === "click") this.pointer({ click: "left" });
    else if (gesture === "right") this.pointer({ click: "right" });
  }

  private flushPointer(): void {
    this.flushTimer = undefined;
    const move_x = Math.round(this.pending.x);
    const move_y = Math.round(this.pending.y);
    if (this.pointerBusy || (!move_x && !move_y)) return;
    this.pending = { x: this.pending.x - move_x, y: this.pending.y - move_y };
    this.pointerBusy = true;
    this.hass
      .callService("samstream", "pointer", { entity_id: this.config.entity, move_x, move_y })
      .catch(() => undefined)
      .finally(() => {
        this.pointerBusy = false;
        this.flushPointer();
      });
  }

  private pointer(data: Record<string, unknown>): void {
    this.call("samstream", "pointer", { entity_id: this.config.entity, ...data }, false);
  }

  private tile(app: TvApp, size: "small" | "large"): TemplateResult {
    if (app.logo) {
      return html`<div class="tile ${size}"><img src=${app.logo} alt="" loading="lazy" /></div>`;
    }
    return html`<div class="tile ${size} letter" style="background:${tileColor(app.name)}">
      ${initials(app.name)}
    </div>`;
  }

  private value(id: string): string {
    const field = this.renderRoot.querySelector<HTMLInputElement | HTMLTextAreaElement>(`#${id}`);
    return field?.value.trim() ?? "";
  }

  private duration(id: string): number | undefined {
    const seconds = Number(this.value(id));
    return seconds > 0 ? seconds : undefined;
  }

  private playCamera(camera: string): void {
    const message = this.value("camera-message");
    const duration = this.duration("camera-duration");
    const corner = this.renderRoot.querySelector<HTMLInputElement>("#camera-tv-corner")?.checked;
    this.call("samstream", "play_stream", {
      entity_id: this.config.entity,
      camera,
      ...(message ? { message } : {}),
      ...(duration ? { duration } : {}),
      // The corner from the TV app settings; HA skips it over a streaming app.
      ...(corner ? { tv_corner: "on" } : {}),
    });
  }

  private showNotice(): void {
    const title = this.value("notice-title");
    const message = this.value("notice-message");
    if (!title && !message) return;
    const duration = this.duration("notice-duration");
    this.call("samstream", "show_message", {
      entity_id: this.config.entity,
      title,
      message,
      severity: this.severity,
      ...(duration ? { duration } : {}),
    });
  }

  private updateText(): void {
    const message = this.value("notice-message") || this.value("camera-message");
    if (!message) return;
    this.call("samstream", "update_message", { entity_id: this.config.entity, message });
  }

  private selectSource(source: string): void {
    this.call("media_player", "select_source", { entity_id: this.config.entity, source });
  }

  private sendKey(command: string): void {
    this.call("samstream", "send_keys", { entity_id: this.config.entity, keys: [command] }, false);
  }

  private toggleMute(): void {
    const muted = this.hass.states[this.config.entity]?.attributes.is_volume_muted === true;
    this.call("media_player", "volume_mute", {
      entity_id: this.config.entity,
      is_volume_muted: !muted,
    });
  }

  private call(domain: string, service: string, data: Record<string, unknown>, announce = true): void {
    this.hass.callService(domain, service, data).then(
      () => announce && service !== "toggle" && this.flash(this.text.sent),
      (error: unknown) =>
        this.flash(`${this.text.failed}: ${(error as { message?: string })?.message ?? String(error)}`),
    );
  }

  private flash(text: string): void {
    this.feedback = text;
    clearTimeout(this.feedbackTimer);
    this.feedbackTimer = setTimeout(() => (this.feedback = ""), FEEDBACK_MS);
  }

  static styles = css`
    ha-card {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .empty {
      padding: 8px;
      color: var(--error-color);
    }
    .header {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .tv {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: var(--secondary-background-color);
      color: var(--primary-color);
    }
    .titles {
      flex: 1;
      min-width: 0;
    }
    .name {
      font-size: 1.15rem;
      font-weight: 500;
    }
    .sub {
      color: var(--secondary-text-color);
      font-size: 0.9rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    section {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .section:not(.first) {
      padding-top: 14px;
      border-top: 1px solid var(--divider-color);
    }
    .power-only {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--secondary-text-color);
    }
    .media {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .media .spacer {
      flex: 1;
    }
    .media .volume {
      flex: 1;
      min-width: 0;
      accent-color: var(--primary-color);
      cursor: pointer;
    }
    .media .volume:disabled {
      cursor: default;
      opacity: 0.4;
    }
    .media .level {
      min-width: 2.5em;
      text-align: center;
      font-variant-numeric: tabular-nums;
      color: var(--secondary-text-color);
    }
    h3 {
      margin: 0;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
    }
    button {
      font: inherit;
      color: inherit;
      cursor: pointer;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      border-radius: 10px;
      padding: 8px 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    button:hover {
      background: var(--secondary-background-color);
    }
    button.primary {
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    button.round {
      width: 44px;
      height: 44px;
      padding: 0;
      border-radius: 50%;
    }
    button.round.on {
      color: var(--primary-color);
    }
    ha-icon {
      --mdc-icon-size: 20px;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      border-radius: 999px;
      padding: 6px 12px;
    }
    .chip.selected {
      border-color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    }
    .chip.warning.selected {
      border-color: var(--warning-color);
      background: color-mix(in srgb, var(--warning-color) 16%, transparent);
    }
    .chip.alert.selected {
      border-color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 14%, transparent);
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > input,
    .row > .chips {
      flex: 1;
    }
    input,
    textarea {
      font: inherit;
      color: var(--primary-text-color);
      background: var(--secondary-background-color);
      border: 1px solid transparent;
      border-radius: 10px;
      padding: 9px 12px;
      box-sizing: border-box;
      width: 100%;
    }
    input:focus,
    textarea:focus {
      outline: none;
      border-color: var(--primary-color);
    }
    textarea {
      resize: vertical;
    }
    .duration {
      display: flex;
      align-items: center;
      gap: 4px;
      color: var(--secondary-text-color);
    }
    .duration input {
      width: 76px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .apps {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
      gap: 10px;
    }
    .app {
      flex-direction: column;
      border: none;
      background: none;
      padding: 6px 2px;
      gap: 6px;
      font-size: 0.78rem;
    }
    .app span {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .app.current .tile {
      box-shadow:
        0 0 0 2px var(--card-background-color),
        0 0 0 4px var(--primary-color);
    }
    .tile {
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-radius: 14px;
      background: var(--secondary-background-color);
      flex-shrink: 0;
    }
    .tile.large,
    .tile.home {
      width: 56px;
      height: 56px;
    }
    .tile.small {
      width: 44px;
      height: 44px;
      border-radius: 12px;
    }
    .tile img {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .tile.letter {
      color: #fff;
      font-weight: 600;
      font-size: 1.1rem;
    }
    .tile.home {
      color: var(--primary-color);
    }
    .remote {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 24px;
    }
    .pad {
      display: grid;
      grid-template-columns: repeat(3, 48px);
      grid-template-rows: repeat(3, 48px);
      gap: 6px;
    }
    .key {
      width: 48px;
      height: 48px;
      padding: 0;
      border-radius: 14px;
    }
    .key.ok {
      border-radius: 50%;
      font-weight: 600;
      background: var(--primary-color);
      border-color: var(--primary-color);
      color: var(--text-primary-color, #fff);
    }
    .side {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .touchpad {
      height: 180px;
      border-radius: 14px;
      background: var(--secondary-background-color);
      display: flex;
      align-items: flex-end;
      justify-content: center;
      padding: 10px;
      box-sizing: border-box;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
      cursor: crosshair;
    }
    .touchpad span {
      font-size: 0.78rem;
      color: var(--secondary-text-color);
      text-align: center;
    }
    .key {
      touch-action: manipulation;
      user-select: none;
      -webkit-user-select: none;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--secondary-text-color);
      cursor: pointer;
    }
    .check input {
      width: auto;
    }
    .hint {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .feedback {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
      text-align: center;
    }
  `;
}

function sourceIcon(source: string): string {
  if (source.startsWith("HDMI")) return "mdi:video-input-hdmi";
  if (source === "Input list") return "mdi:import";
  return "mdi:television-classic";
}

/** Label key of a section in the editor. */
function sectionKey(
  section: Section,
): "tv" | "cameras" | "message" | "apps" | "remote" | "media" | "keyboard" | "touchpad" | "art" {
  return section;
}

if (!customElements.get("samstream-card")) {
  customElements.define("samstream-card", SamstreamCard);
  const cards = ((window as unknown as { customCards?: unknown[] }).customCards ??= []);
  cards.push({
    type: "samstream-card",
    name: "Samstream",
    description: "Cameras, messages, apps and a remote for your Samsung TV.",
    preview: true,
    documentationURL: "https://github.com/Mrslimon/samstream",
  });
}
