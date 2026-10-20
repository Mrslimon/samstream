/** Remote control cheat sheet; each line carries its own direction for mixed Arabic/English. */
export const HELP_LINES: readonly string[] = [
  "◀ ▶  البث السابق / التالي · Previous / next stream",
  "1–9  اختيار بث · Jump to stream",
  "▲ ▼  طريقة العرض · Fit: fit / fill (crop) / stretch",
  "OK  إعادة التشغيل · Restart stream",
  "INFO / الأخضر  إظهار المساعدة · Show this help",
  "BACK  خروج · Exit",
];

export function renderHelp(container: HTMLElement): void {
  container.textContent = "";
  for (const line of HELP_LINES) {
    const row = document.createElement("p");
    row.dir = "auto";
    row.textContent = line;
    container.appendChild(row);
  }
}
