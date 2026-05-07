// frontend/src/components/TopCoinCard.jsx
import { useNavigate } from "react-router-dom";
import CoinRadarChart from "./RadarChart";
import CoinIcon from "./CoinIcon";

const scoreToRowLabel = (score) => {
  const s = Number(score ?? 0);
  if (s <= 0) return { text: "—", color: "#707a8a" };
  if (s >= 6.5) return { text: "Tăng giá", color: "#0ECB81" };
  if (s >= 4.5) return { text: "Bình thường", color: "#707a8a" };
  return { text: "Giảm giá", color: "#F6465D" };
};

const formatPrice = (v) =>
  v >= 1
    ? v.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    : v.toLocaleString("en-US", { maximumFractionDigits: 6 });

/**
 * TopCoinCard — Card phân tích tâm lý cho Top 3 coin.
 * Header: logo + symbol + giá + %24h.
 * Middle: radar 4 trục + điểm tổng ở giữa.
 * Dưới: 4 trục chi tiết + nút "Xem chi tiết" điều hướng trang coin.
 */
export default function TopCoinCard({ coin, priceData }) {
  const navigate = useNavigate();
  const hasData = (coin.score_total ?? 0) > 0;
  const wsPrice = priceData?.[`${coin.symbol}USDT`];

  // Social: hiển thị SỐ LƯỢNG đề cập (text = "972") thay vì nhãn sentiment.
  const mentions = coin.social_mentions;
  const rows = [
    { label: "Tin tức", ...scoreToRowLabel(coin.score_news) },
    { label: "Vĩ mô", ...scoreToRowLabel(coin.score_macro) },
    { label: "Funding Rate", ...scoreToRowLabel(coin.score_funding) },
    {
      label: "Thảo luận trên mạng xã hội",
      text: mentions != null ? String(mentions) : "—",
      color: "#1e2329",
    },
  ];

  const go = () => navigate(`/coin/${coin.id}`);

  return (
    <div className="bg-white rounded-lg border border-[#eaecef] hover:border-[#d6d9df] transition overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center gap-2 px-4 pt-4 pb-3 cursor-pointer"
        onClick={go}
      >
        <CoinIcon
          symbol={coin.symbol}
          name={coin.name}
          imageUrl={coin.image_url}
          className="w-6 h-6 rounded-full flex-shrink-0"
        />
        <span className="text-[15px] font-semibold text-[#1e2329] truncate">
          {coin.symbol}
        </span>
        <span className="text-[12px] text-[#707a8a] truncate">
          · {coin.name}
        </span>
      </div>

      {/* Price */}
      <div className="px-4 pb-3 flex items-baseline gap-2 text-[13px]">
        <span className="font-mono font-semibold text-[#1e2329]">
          ${wsPrice ? formatPrice(wsPrice.price) : "—"}
        </span>
        {wsPrice && (
          <span
            className={
              wsPrice.change24h >= 0 ? "text-[#0ECB81]" : "text-[#F6465D]"
            }
          >
            {wsPrice.change24h >= 0 ? "+" : ""}
            {wsPrice.change24h.toFixed(2)}%
          </span>
        )}
      </div>

      {/* Radar + điểm tổng ở giữa */}
      <div className="px-3 cursor-pointer" onClick={go}>
        <CoinRadarChart
          coin={coin}
          size={240}
          centerScore={hasData ? Number(coin.score_total).toFixed(2) : "—"}
          centerLabel={coin.label}
        />
      </div>

      {/* 4 trục detail */}
      <div className="px-4 pt-3 pb-3 space-y-2 text-[13px] border-t border-[#f5f5f5]">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between">
            <span className="text-[#707a8a]">{r.label}</span>
            <span style={{ color: r.color }} className="font-medium">
              {r.text}
            </span>
          </div>
        ))}
      </div>

      {/* Footer: CTA duy nhất → trang chi tiết */}
      <div className="px-4 pb-4 pt-1 flex items-center justify-end">
        <button
          type="button"
          onClick={go}
          className="px-5 py-2 rounded-md bg-[#4F46E5] hover:bg-[#4338CA] text-white text-[13px] font-semibold transition"
        >
          Xem chi tiết →
        </button>
      </div>
    </div>
  );
}
