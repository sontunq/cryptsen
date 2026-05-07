// frontend/src/pages/SentimentPage.jsx
import { useEffect, useMemo, useState } from "react";
import Navbar from "../components/Navbar";
import TopCoinCard from "../components/TopCoinCard";
import CoinTable from "../components/CoinTable";
import MacroBanner from "../components/MacroBanner";
import { useBinanceWS } from "../hooks/useBinanceWS";
import { formatVNTime } from "../utils/time";

export default function SentimentPage() {
  const [coins, setCoins] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/coins")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (cancelled) return;
        setCoins(d.coins || []);
        setLastUpdated(d.last_updated || null);
        setError(null);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  // useMemo để `symbols` tham chiếu ổn định — tránh reconnect WS mỗi render.
  const symbols = useMemo(
    () => coins.map((c) => c.symbol?.toLowerCase()).filter(Boolean),
    [coins]
  );
  const prices = useBinanceWS(symbols);

  const rankedByScore = useMemo(() => {
    return [...coins]
      .sort((a, b) => {
        const scoreA = Number(a?.score_total ?? 0);
        const scoreB = Number(b?.score_total ?? 0);
        if (scoreB !== scoreA) return scoreB - scoreA;
        const rankA = Number(a?.rank ?? Number.MAX_SAFE_INTEGER);
        const rankB = Number(b?.rank ?? Number.MAX_SAFE_INTEGER);
        if (rankA !== rankB) return rankA - rankB;
        return (a?.symbol || "").localeCompare(b?.symbol || "");
      })
      .map((coin, i) => ({ ...coin, sentiment_rank: i + 1 }));
  }, [coins]);

  const top3 = rankedByScore.slice(0, 3);
  const rest = rankedByScore.slice(3);

  return (
    <div className="min-h-screen bg-white">
      <Navbar />
      <div className="max-w-[1400px] mx-auto px-6 py-8">
        <h1 className="text-[26px] font-bold text-[#1e2329] mb-1">
          Phân tích tâm lý thị trường Crypto
        </h1>
        <p className="text-[13px] text-[#707a8a] mb-1 flex items-center gap-2 flex-wrap">
          Tổng hợp tâm lý từ tin tức, mạng xã hội, sự kiện vĩ mô và dòng tiền
          Funding. Cập nhật lúc: {formatVNTime(lastUpdated)}
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-[#eaecef] text-[12px] text-[#4F46E5] hover:bg-[#f5f5f5] disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={loading ? "animate-spin" : ""}>
              <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
            Làm mới
          </button>
        </p>
        <p className="text-[12px] text-[#707a8a] mb-6">
          Nội dung do Cryptsen AI tổng hợp, không phải lời khuyên đầu tư.
        </p>

        <MacroBanner />

        {error && (
          <div className="mb-4 p-3 rounded-md bg-[#fff1f2] border border-[#f6465d] text-[#b11b30] text-[13px] break-words">
            Lỗi gọi backend: {error} — kiểm tra uvicorn còn chạy không.
          </div>
        )}

        {loading && coins.length === 0 && (
          <div className="text-[#707a8a] text-center py-16 text-[13px]">
            Đang tải dữ liệu…
          </div>
        )}

        {top3.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
            {top3.map((coin) => (
              <TopCoinCard key={coin.id} coin={coin} priceData={prices} />
            ))}
          </div>
        )}

        {rest.length > 0 && <CoinTable coins={rest} prices={prices} />}
      </div>
    </div>
  );
}
