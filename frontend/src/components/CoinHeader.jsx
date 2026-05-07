// frontend/src/components/CoinHeader.jsx
import { useNavigate } from "react-router-dom";
import { getLabelColor } from "./RadarChart";
import CoinIcon from "./CoinIcon";
import { formatPrice } from "../utils/format";

/**
 * CoinHeader — Box "Khuyến nghị của AI" (ảnh 3) với gradient border.
 * Trái: coin icon + tên + giá. Phải: sao + nút "Giao dịch" vàng.
 * Dưới: nhãn khuyến nghị + summary Gemini.
 */
export default function CoinHeader({ coin, priceData }) {
  const navigate = useNavigate();
  const labelColor = getLabelColor(coin.label);
  const wsPrice = priceData?.[`${coin.symbol}USDT`];

  return (
    <div className="px-6 pt-6">
      <button
        onClick={() => navigate("/cryptosentiment")}
        className="text-[13px] text-[#707a8a] hover:text-[#4F46E5] mb-4"
      >
        ← Quay lại danh sách
      </button>

      <div className="gradient-border">
        <div className="p-6">
          <div className="flex items-start gap-4 flex-wrap">
            <CoinIcon
              symbol={coin.symbol}
              name={coin.name}
              imageUrl={coin.image_url}
              className="w-12 h-12 rounded-full flex-shrink-0"
            />
            <div className="min-w-0 flex-1">
              <h1 className="text-[22px] font-bold text-[#1e2329] leading-tight break-words">
                Phân tích {coin.name} ({coin.symbol})
              </h1>
              <div className="mt-1 flex items-baseline gap-3 text-[14px]">
                <span className="font-mono font-semibold text-[#1e2329]">
                  ${wsPrice ? formatPrice(wsPrice.price) : "—"}
                </span>
                {wsPrice && (
                  <span
                    className={
                      wsPrice.change24h >= 0
                        ? "text-[#0ECB81]"
                        : "text-[#F6465D]"
                    }
                  >
                    {wsPrice.change24h >= 0 ? "+" : ""}
                    {wsPrice.change24h.toFixed(2)}%
                  </span>
                )}
                <span className="text-[#707a8a] text-[12px]">
                  Rank #{coin.rank}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-5">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[15px] font-semibold text-[#1e2329]">
                Nhận định của AI:
              </span>
              <span
                className="text-[15px] font-semibold"
                style={{ color: labelColor }}
              >
                {coin.label}
              </span>
            </div>
            {coin.summary && (
              <p className="mt-2 text-[13px] leading-relaxed text-[#475569] break-words">
                {coin.summary}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
