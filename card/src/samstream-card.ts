import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  SECTIONS,
  cameraList,
  friendlyName,
  initials,
  remoteEntity,
  sectionsOf,
  tileColor,
  type AppsAnswer,
  type Hass,
  type Section,
  type TvApp,
} from "./helpers";
import { languageOf, strings, type Strings } from "./strings";

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

/** custom:samstream-card: the TV, its cameras, messages, apps and a remote. */
export class SamstreamCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    config: { state: true },
    apps: { state: true },
    camera: { state: true },
    feedback: { state: true },
    severity: { state: true },
  };

  hass!: Hass;
  config!: CardConfig;
  apps: AppsAnswer | undefined;
  camera = "";
  feedback = "";
  severity: Severity = "info";
  private appsFor: string | null | undefined;
  private feedbackTimer: ReturnType<typeof setTimeout> | undefined;

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
    return { entity: tv?.entity_id ?? "", sections: [...SECTIONS] };
  }

  private get text(): Strings {
    return strings(languageOf(this.hass?.locale?.language ?? this.hass?.language));
  }

  private get rtl(): boolean {
    return languageOf(this.hass?.locale?.language ?? this.hass?.language) === "ar";
  }

  protected updated(changed: PropertyValues): void {
    if (!changed.has("hass") || !this.hass || !this.config) return;
    // Refresh the app list when the app on screen changes (logos may have been added).
    const appId = (this.hass.states[this.config.entity]?.attributes.app_id as string) ?? null;
    if (this.apps === undefined || appId !== this.appsFor) {
      this.appsFor = appId;
      this.loadApps();
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
    const shown = on ? sections : sections.includes("tv") ? ["tv" as Section] : [];
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
    const key = (code: string, icon: string, label: string, extra = "") =>
      html`<button class="key ${extra}" title=${label} @click=${() => this.sendKey(code)}>
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
    // Arrows keep their physical meaning; only the layout mirrors in RTL.
    return html`
      <section>
        <h3>${t.remote}</h3>
        <div class="remote">
          <div class="pad">
            <span></span>${key("KEY_UP", "mdi:chevron-up", "▲")}<span></span>
            ${key(this.rtl ? "KEY_RIGHT" : "KEY_LEFT", this.rtl ? "mdi:chevron-right" : "mdi:chevron-left", "◀")}
            <button class="key ok" @click=${() => this.sendKey("KEY_ENTER")}>${t.ok}</button>
            ${key(this.rtl ? "KEY_LEFT" : "KEY_RIGHT", this.rtl ? "mdi:chevron-left" : "mdi:chevron-right", "▶")}
            <span></span>${key("KEY_DOWN", "mdi:chevron-down", "▼")}<span></span>
          </div>
          <div class="side">
            ${key("KEY_RETURN", "mdi:arrow-u-left-top", t.back)}
            ${key("KEY_HOME", "mdi:home", t.home)}
            ${key("KEY_MENU", "mdi:menu", t.menu)}
          </div>
        </div>
      </section>
    `;
  }

  private renderMedia(): TemplateResult {
    const t = this.text;
    const media = (service: string, icon: string, label: string) =>
      html`<button class="key" title=${label} @click=${() =>
        this.call("media_player", service, { entity_id: this.config.entity }, false)}>
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
    const volume = this.hass.states[this.config.entity]?.attributes.volume_level;
    return html`
      <section>
        <h3>${t.media}</h3>
        <div class="media">
          ${media("media_play_pause", "mdi:play-pause", t.playPause)}
          <span class="spacer"></span>
          ${media("volume_down", "mdi:volume-minus", t.volumeDown)}
          <span class="level">${typeof volume === "number" ? Math.round(volume * 100) : "–"}</span>
          ${media("volume_up", "mdi:volume-plus", t.volumeUp)}
          <button class="key" title=${t.mute} @click=${() => this.toggleMute()}>
            <ha-icon icon="mdi:volume-off"></ha-icon>
          </button>
        </div>
      </section>
    `;
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
    this.call("samstream", "play_stream", {
      entity_id: this.config.entity,
      camera,
      ...(message ? { message } : {}),
      ...(duration ? { duration } : {}),
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
    const remote = remoteEntity(this.hass, this.config.entity);
    if (remote) this.call("remote", "send_command", { entity_id: remote, command }, false);
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

/** Label key of a section in the editor. */
function sectionKey(section: Section): "tv" | "cameras" | "message" | "apps" | "remote" | "media" {
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
    documentationURL: "https://github.com/islamahmady/samstream",
  });
}
