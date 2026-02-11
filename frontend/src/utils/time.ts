export function formatTime(ts: number) {
  return new Date(ts).toLocaleString("ar", { hour12: false });
}
