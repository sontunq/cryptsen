import { useMemo, useState, useEffect } from "react";

// Màu avatar fallback dựa trên ký tự đầu của symbol để mỗi coin
// trông khác nhau thay vì tất cả cùng màu indigo.
const AVATAR_PALETTES = [
  { bg: "#eef2ff", text: "#4F46E5" }, // indigo
  { bg: "#fef3c7", text: "#D97706" }, // amber
  { bg: "#d1fae5", text: "#059669" }, // emerald
  { bg: "#fee2e2", text: "#DC2626" }, // red
  { bg: "#e0f2fe", text: "#0284C7" }, // sky
  { bg: "#f3e8ff", text: "#7C3AED" }, // violet
  { bg: "#fce7f3", text: "#DB2777" }, // pink
  { bg: "#f0fdf4", text: "#16A34A" }, // green
  { bg: "#fff7ed", text: "#EA580C" }, // orange
  { bg: "#ecfeff", text: "#0891B2" }, // cyan
];

function avatarPalette(symbol) {
  const code = String(symbol || "").charCodeAt(0) || 0;
  return AVATAR_PALETTES[code % AVATAR_PALETTES.length];
}

function buildCandidates(symbol, imageUrl) {
  const sym = String(symbol || "").trim().toLowerCase();
  const out = [];
  if (imageUrl) out.push(String(imageUrl).trim());
  if (sym) {
    // CDN 1: spothq — có ~400 coin phổ biến
    out.push(
      `https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/${sym}.png`
    );
    // CDN 2: TrustWallet assets (rộng hơn, hàng ngàn token)
    out.push(
      `https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/smartchain/assets/${sym}/logo.png`
    );
    // CDN 3: cryptoicons.org
    out.push(`https://cryptoicons.org/api/icon/${sym}/200`);
  }
  return Array.from(new Set(out.filter(Boolean)));
}

export default function CoinIcon({ symbol, name, imageUrl, className }) {
  const candidates = useMemo(
    () => buildCandidates(symbol, imageUrl),
    [symbol, imageUrl]
  );
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    setIdx(0);
  }, [candidates]);

  const palette = avatarPalette(symbol);

  if (idx >= candidates.length) {
    // Fallback: avatar chữ cái với màu riêng mỗi coin
    return (
      <span
        className={
          (className || "") +
          " inline-flex items-center justify-center font-bold text-[11px] select-none"
        }
        style={{ backgroundColor: palette.bg, color: palette.text }}
        aria-label={name || symbol}
        title={name || symbol}
      >
        {String(symbol || "?").slice(0, 1).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      src={candidates[idx]}
      alt={name || symbol || "coin"}
      className={className}
      loading="lazy"
      onError={() => setIdx((v) => v + 1)}
    />
  );
}
