/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Development only: JSON array of {label, url, type?} played from the home screen. */
  readonly VITE_SPIKE_STREAMS?: string;
}

/** From config.xml at build time (vite.config.ts). */
declare const __APP_VERSION__: string;
