// frontend/src/pages/CoinDetailPage.jsx
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import Navbar from "../components/Navbar";
import CoinHeader from "../components/CoinHeader";
import CoinRadarSection from "../components/CoinRadarSection";
import PriceChart from "../components/PriceChart";
import SocialNewsPanel from "../components/SocialNewsPanel";
import { useBinanceWS } from "../hooks/useBinanceWS";

export default function CoinDetailPage() {
  const { coinId } = useParams();
  const [coinData, setCoinData] = useState(null);
  const [newsData, setNewsData] = useState([]);       // CoinDesk + Telegram coin
  const [redditData, setRedditData] = useState([]);   // Reddit social posts
  const [macroEvents, setMacroEvents] = useState([]);
  const [macroNews, setMacroNews] = useState([]);     // CoinDesk macro + Telegram macro
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [scoreFlash, setScoreFlash] = useState(false);

  // Helper: fetch tất cả feeds (news CoinDesk + Telegram coin + Reddit social + Telegram social)
  const fetchFeeds = (cid) => [
    // Tin tức coin: CoinDesk
    fetch(`/api/news?coin_id=${cid}&source=coindesk&hours=168&limit=100`).then((r) =>
      r.ok ? r.json() : { items: [] }
    ),
    // Tin tức coin: Telegram (coin-specific, không phải macro)
    fetch(`/api/news?coin_id=${cid}&source=telegram&hours=24&limit=50`).then((r) =>
      r.ok ? r.json() : { items: [] }
    ),
    // Social: Reddit
    fetch(`/api/news?coin_id=${cid}&source=reddit&hours=24&limit=100`).then((r) =>
      r.ok ? r.json() : { items: [] }
    ),
  ];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    // PHASE 1 — Load snapshot CACHE + feeds cũ để render nhanh (<1s).
    Promise.allSettled([
      fetch(`/api/coins/${coinId}`).then((r) => {
        if (!r.ok) throw new Error(`coins ${r.status}`);
        return r.json();
      }),
      ...fetchFeeds(coinId),
      fetch(`/api/macro-events`).then((r) =>
        r.ok ? r.json() : { events: [], news: [] }
      ),
    ]).then(([coinRes, coindeskRes, tgCoinRes, redditRes, macroRes]) => {
      if (cancelled) return;

      if (coinRes.status === "fulfilled") {
        setCoinData(coinRes.value);
      } else {
        setError(coinRes.reason?.message || "Không tải được dữ liệu coin");
      }

      // Gộp CoinDesk + Telegram coin vào news feed (cột phải)
      const coindeskItems = coindeskRes.status === "fulfilled" ? coindeskRes.value?.items || [] : [];
      const tgCoinItems = tgCoinRes.status === "fulfilled" ? tgCoinRes.value?.items || [] : [];
      setNewsData([...coindeskItems, ...tgCoinItems].sort((a, b) =>
        new Date(b.published_at || 0) - new Date(a.published_at || 0)
      ));

      // Reddit posts → cột trái
      setRedditData(redditRes.status === "fulfilled" ? redditRes.value?.items || [] : []);

      if (macroRes.status === "fulfilled") {
        setMacroEvents(macroRes.value?.events || []);
        setMacroNews(macroRes.value?.news || []); // CoinDesk + Investing + Telegram macro
      }
      setLoading(false);

      // PHASE 2 — Kích analyze FRESH nền
      setAnalyzing(true);
      fetch(`/api/coins/${coinId}/analyze`, { method: "POST" })
        .then((r) => r.ok ? r.json() : null)
        .then(async (fresh) => {
          if (cancelled || !fresh) return;
          setCoinData(fresh);
          setScoreFlash(true);
          setTimeout(() => setScoreFlash(false), 1600);

          // Refetch feeds sau analyze
          const [coindeskRes2, tgCoinRes2, redditRes2] = await Promise.allSettled(fetchFeeds(coinId));
          if (cancelled) return;

          const cdItems = coindeskRes2.status === "fulfilled" ? coindeskRes2.value?.items || [] : [];
          const tgItems = tgCoinRes2.status === "fulfilled" ? tgCoinRes2.value?.items || [] : [];
          setNewsData([...cdItems, ...tgItems].sort((a, b) =>
            new Date(b.published_at || 0) - new Date(a.published_at || 0)
          ));

          if (redditRes2.status === "fulfilled") {
            setRedditData(redditRes2.value?.items || []);
          }
        })
        .catch(() => {})
        .finally(() => !cancelled && setAnalyzing(false));
    });

    return () => {
      cancelled = true;
    };
  }, [coinId]);

  const wsSymbols = useMemo(
    () => (coinData?.symbol ? [coinData.symbol.toLowerCase()] : []),
    [coinData?.symbol]
  );
  const priceData = useBinanceWS(wsSymbols);

  if (loading && !coinData) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <div className="max-w-[1100px] mx-auto p-6 text-[#707a8a] text-[13px]">
          Đang tải…
        </div>
      </div>
    );
  }

  if (!coinData) {
    return (
      <div className="min-h-screen bg-white">
        <Navbar />
        <div className="max-w-[1100px] mx-auto p-6">
          <div className="p-4 rounded-md bg-[#fff1f2] border border-[#f6465d] text-[#b11b30] text-[13px]">
            {error || "Không tìm thấy coin."}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      <Navbar />
      <div className="max-w-[1100px] mx-auto pb-10">
        {analyzing && (
          <div className="mx-6 mt-4 px-3 py-2 rounded-md bg-[#eef2ff] border border-[#c7d2fe] text-[#4338ca] text-[12px]">
            Đang phân tích fresh (tin tức + mạng xã hội 24h)… điểm sẽ cập nhật khi xong.
          </div>
        )}
        {/* 1. Header + Khuyến nghị AI */}
        <CoinHeader coin={coinData} priceData={priceData} />

        {/* 2. Radar + bảng điểm chi tiết */}
        <div className={scoreFlash ? "score-updated" : ""}>
          <CoinRadarSection coin={coinData} />
        </div>

        {/* 3. Biểu đồ giá TradingView */}
        <PriceChart symbol={coinData.symbol} />

        {/* 4. 2-col: MXH (Reddit) + Tin tức (CoinDesk + Telegram) + Vĩ mô */}
        <SocialNewsPanel
          coin={coinData}
          social={redditData}
          news={newsData}
          macroEvents={macroEvents}
          macroNews={macroNews}
        />

        <div className="px-6 pt-6 text-[#c7cbd4] text-[11px] text-center">
          Nội dung do AI tạo ra. Không phải lời khuyên đầu tư.
        </div>
      </div>
    </div>
  );
}
