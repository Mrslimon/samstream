import "@fontsource/readex-pro/arabic-400.css";
import "@fontsource/readex-pro/latin-400.css";
import "@fontsource/readex-pro/arabic-600.css";
import "@fontsource/readex-pro/latin-600.css";
import "./styles.css";
import { showOverlay } from "./overlay";
import { parseSpikeStreams, runSpike } from "./spike";

// Launch payload parsing and the Home Assistant channel land in milestones 8–10.
const overlay = document.getElementById("overlay");
const status = document.getElementById("status");
const help = document.getElementById("help");
const video = document.getElementById("mse-video");
const spikeStreams = parseSpikeStreams(import.meta.env.VITE_SPIKE_STREAMS);

if (overlay && status && help && video instanceof HTMLVideoElement && spikeStreams.length > 0) {
  runSpike(spikeStreams, { overlay, status, help, video });
} else if (overlay) {
  showOverlay(overlay, "Samstream جاهز");
}
