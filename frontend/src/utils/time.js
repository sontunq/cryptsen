// frontend/src/utils/time.js — CHUẨN DUY NHẤT
// Backend trả ISO 8601 UTC, React convert sang giờ VN tại đây.

export const formatVNTime = (isoString) => {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const formatVNTimeFull = (isoString) => {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};
