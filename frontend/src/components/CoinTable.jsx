// frontend/src/components/CoinTable.jsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getLabelColor } from "./RadarChart";
import CoinIcon from "./CoinIcon";
import { formatPrice } from "../utils/format";

const axisScore = (score) => {
  const s = Number(score ?? 0);
  if (s <= 0) return { display: "—", color: "#c7cbd4", arrow: null };
  if (s >= 6.5) return { display: s.toFixed(1), color: "#0ECB81", arrow: "↑" };
  if (s >= 4.5) return { display: s.toFixed(1), color: "#707a8a", arrow: null };
  return { display: s.toFixed(1), color: "#F6465D", arrow: "↓" };
};

const LabelDropdown = ({ label, value, onChange, options }) => (
  <div className="flex flex-col gap-1 min-w-[180px]">
    <span className="text-[12px] text-[#707a8a] flex items-center gap-1">
      {label}
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="opacity-60">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
        <path d="M12 8v5M12 16h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </span>
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-white border border-[#eaecef] rounded-md px-3 py-2 pr-8 text-[13px] text-[#1e2329] hover:border-[#d6d9df] focus:outline-none focus:border-[#f0b90b]"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <svg
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[#707a8a]"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
      >
        <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  </div>
);

/**
 * CoinTable — Phong cách Binance AI Select (ảnh 2).
 * Header trắng, không viền dọc, dropdown filter, icon sao.
 */
const PAGE_SIZE = 10;

export default function CoinTable({ coins, prices }) {
  const navigate = useNavigate();
  const [filterTier, setFilterTier] = useState("all");
  const [filterSentiment, setFilterSentiment] = useState("all");
  const [filterNews, setFilterNews] = useState("all");
  const [filterSocial, setFilterSocial] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [sortCol, setSortCol] = useState("ai_rank");
  const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(1);

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir(col === "name" ? "asc" : "asc");
    }
  };

  const SortIcon = ({ col }) => {
    if (sortCol !== col) return <span className="ml-1 opacity-30">↕</span>;
    return <span className="ml-1 text-[#4F46E5]">{sortDir === "asc" ? "↑" : "↓"}</span>;
  };

  const tierOpts = [
    { value: "all", label: "Chọn giá trị" },
    { value: "top10", label: "Top 10" },
    { value: "top20", label: "Top 20" },
    { value: "top50", label: "Top 50" },
  ];
  const sentimentOpts = [
    { value: "all", label: "Chọn giá trị" },
    { value: "positive", label: "Tích cực" },
    { value: "neutral", label: "Bình thường" },
    { value: "negative", label: "Tiêu cực" },
    { value: "none", label: "Không có dữ liệu" },
  ];
  const axisOpts = [
    { value: "all", label: "Chọn giá trị" },
    { value: "up", label: "Tăng giá" },
    { value: "neutral", label: "Bình thường" },
    { value: "down", label: "Giảm giá" },
  ];

  const matchAxis = (score, key) => {
    const s = Number(score ?? 0);
    if (key === "all") return true;
    if (key === "up") return s >= 6.5;
    if (key === "neutral") return s >= 4.5 && s < 6.5;
    if (key === "down") return s > 0 && s < 4.5;
    return true;
  };

  const filtered = useMemo(() => {
    let out = coins;
    const search = searchText.trim().toLowerCase();
    if (search) {
      out = out.filter((c) => {
        const sym = String(c.symbol || "").toLowerCase();
        const name = String(c.name || "").toLowerCase();
        return sym.includes(search) || name.includes(search);
      });
    }
    if (filterTier === "top10") out = out.filter((c) => c.rank <= 10);
    if (filterTier === "top20") out = out.filter((c) => c.rank <= 20);
    if (filterTier === "top50") out = out.filter((c) => c.rank <= 50);
    if (filterSentiment === "positive")
      out = out.filter((c) => (c.label || "").toLowerCase().includes("tích cực"));
    if (filterSentiment === "neutral")
      out = out.filter((c) => c.label === "Bình thường");
    if (filterSentiment === "negative")
      out = out.filter((c) => (c.label || "").toLowerCase().includes("tiêu cực"));
    if (filterSentiment === "none")
      out = out.filter((c) => c.label === "Không có dữ liệu");
    if (filterNews !== "all")
      out = out.filter((c) => matchAxis(c.score_news, filterNews));
    if (filterSocial !== "all")
      out = out.filter((c) => matchAxis(c.score_social, filterSocial));

    // Sort
    out = [...out].sort((a, b) => {
      let valA, valB;
      const wsA = prices?.[`${a.symbol}USDT`];
      const wsB = prices?.[`${b.symbol}USDT`];
      switch (sortCol) {
        case "name":
          valA = (a.symbol || "").toLowerCase();
          valB = (b.symbol || "").toLowerCase();
          return sortDir === "asc" ? valA.localeCompare(valB) : valB.localeCompare(valA);
        case "rank":
          valA = Number(a.rank ?? 9999);
          valB = Number(b.rank ?? 9999);
          break;
        case "ai_rank":
          valA = Number(a.score_total ?? 0);
          valB = Number(b.score_total ?? 0);
          return sortDir === "asc" ? valB - valA : valA - valB;
        case "price":
          valA = wsA?.price ?? 0;
          valB = wsB?.price ?? 0;
          break;
        case "change24h":
          valA = wsA?.change24h ?? -999;
          valB = wsB?.change24h ?? -999;
          break;
        case "social": valA = Number(a.score_social ?? 0); valB = Number(b.score_social ?? 0); break;
        case "news":   valA = Number(a.score_news ?? 0);   valB = Number(b.score_news ?? 0);   break;
        case "macro":  valA = Number(a.score_macro ?? 0);  valB = Number(b.score_macro ?? 0);  break;
        case "funding":valA = Number(a.score_funding ?? 0);valB = Number(b.score_funding ?? 0);break;
        default:
          valA = 0; valB = 0;
      }
      return sortDir === "asc" ? valA - valB : valB - valA;
    });

    return out;
  }, [coins, prices, searchText, filterTier, filterSentiment, filterNews, filterSocial, sortCol, sortDir]);

  useEffect(() => { setPage(1); }, [searchText, filterTier, filterSentiment, filterNews, filterSocial, sortCol, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const goTo = (p) => setPage(Math.max(1, Math.min(p, totalPages)));

  const reset = () => {
    setSearchText("");
    setFilterTier("all");
    setFilterSentiment("all");
    setFilterNews("all");
    setFilterSocial("all");
    setSortCol("ai_rank");
    setSortDir("asc");
    setPage(1);
  };

  const anyFilter =
    searchText.trim().length > 0 ||
    filterTier !== "all" ||
    filterSentiment !== "all" ||
    filterNews !== "all" ||
    filterSocial !== "all" ||
    sortCol !== "ai_rank" ||
    sortDir !== "asc";

  const thCls = "py-3 px-3 font-normal cursor-pointer select-none hover:text-[#1e2329] whitespace-nowrap";

  return (
    <div className="bg-white">
      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 mb-6">
        <LabelDropdown
          label="Loại coin"
          value={filterTier}
          onChange={setFilterTier}
          options={tierOpts}
        />
        <LabelDropdown
          label="Tâm lý tổng thể"
          value={filterSentiment}
          onChange={setFilterSentiment}
          options={sentimentOpts}
        />
        <LabelDropdown
          label="Tâm lý đối với tin tức"
          value={filterNews}
          onChange={setFilterNews}
          options={axisOpts}
        />
        <LabelDropdown
          label="Tâm lý mạng xã hội"
          value={filterSocial}
          onChange={setFilterSocial}
          options={axisOpts}
        />
        <div className="flex flex-col gap-1 min-w-[220px] flex-1 max-w-[360px]">
          <span className="text-[12px] text-[#707a8a]">Tìm kiếm coin</span>
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[#9aa4b2]"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Ví dụ: BTC, ETH, Solana..."
              className="w-full bg-white border border-[#eaecef] rounded-md pl-9 pr-3 py-2 text-[13px] text-[#1e2329] hover:border-[#d6d9df] focus:outline-none focus:border-[#f0b90b]"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={reset}
          disabled={!anyFilter}
          className={
            "ml-auto px-4 py-2 rounded-md text-[13px] font-medium border transition " +
            (anyFilter
              ? "border-[#eaecef] text-[#1e2329] hover:bg-[#f5f5f5]"
              : "border-[#eaecef] text-[#c7cbd4] cursor-not-allowed")
          }
        >
          Thiết lập lại
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px] text-left border-collapse">
          <thead className="text-[#707a8a]">
            <tr className="border-b border-[#eaecef]">
              <th className={thCls} onClick={() => handleSort("name")}>Tên<SortIcon col="name" /></th>
              <th className={thCls} onClick={() => handleSort("rank")}>Xếp hạng<SortIcon col="rank" /></th>
              <th className={thCls} onClick={() => handleSort("ai_rank")}>Xếp hạng AI<SortIcon col="ai_rank" /></th>
              <th className={thCls + " text-right"} onClick={() => handleSort("price")}>Giá<SortIcon col="price" /></th>
              <th className={thCls + " text-right"} onClick={() => handleSort("change24h")}>24h %<SortIcon col="change24h" /></th>
              <th className={thCls} onClick={() => handleSort("social")}>Mạng xã hội<SortIcon col="social" /></th>
              <th className={thCls} onClick={() => handleSort("news")}>Tin tức<SortIcon col="news" /></th>
              <th className={thCls} onClick={() => handleSort("macro")}>Vĩ mô<SortIcon col="macro" /></th>
              <th className={thCls} onClick={() => handleSort("funding")}>Funding<SortIcon col="funding" /></th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((coin) => {
              const wsPrice = prices?.[`${coin.symbol}USDT`];
              const labelColor = getLabelColor(coin.label);
              const hasData = (coin.score_total ?? 0) > 0;
              const news = axisScore(coin.score_news);
              const social = axisScore(coin.score_social);
              const macro = axisScore(coin.score_macro);
              const funding = axisScore(coin.score_funding);
              return (
                <tr
                  key={coin.id}
                  className="border-b border-[#f5f5f5] hover:bg-[#fafafa] cursor-pointer"
                  onClick={() => navigate(`/coin/${coin.id}`)}
                >
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <CoinIcon
                        symbol={coin.symbol}
                        name={coin.name}
                        imageUrl={coin.image_url}
                        className="w-5 h-5 rounded-full flex-shrink-0"
                      />
                      <span className="font-medium text-[#1e2329]">
                        {coin.symbol}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-[#1e2329]">{coin.rank}</td>
                  <td className="py-3 px-3">
                    {hasData ? (
                      <span
                        className="font-medium flex items-center gap-1"
                        style={{ color: labelColor }}
                      >
                        {coin.sentiment_rank != null && (
                          <span className="text-[#707a8a] font-normal text-[12px] mr-0.5 tabular-nums">
                            #{coin.sentiment_rank}
                          </span>
                        )}
                        {labelColor === "#0ECB81" && (
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                            <path d="M5 1 1 6h3v3h2V6h3L5 1Z" />
                          </svg>
                        )}
                        {labelColor === "#F6465D" && (
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                            <path d="M5 9 1 4h3V1h2v3h3L5 9Z" />
                          </svg>
                        )}
                        {coin.label}
                      </span>
                    ) : (
                      <span className="text-[#c7cbd4]">—</span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-right text-[#1e2329] font-mono tabular-nums">
                    {wsPrice ? `$${formatPrice(wsPrice.price)}` : "—"}
                  </td>
                  <td className="py-3 px-3 text-right tabular-nums">
                    {wsPrice ? (
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
                    ) : (
                      <span className="text-[#c7cbd4]">—</span>
                    )}
                  </td>
                  <td className="py-3 px-3 tabular-nums" style={{ color: social.color }}>
                    {social.arrow && <span className="mr-0.5">{social.arrow}</span>}{social.display}
                  </td>
                  <td className="py-3 px-3 tabular-nums" style={{ color: news.color }}>
                    {news.arrow && <span className="mr-0.5">{news.arrow}</span>}{news.display}
                  </td>
                  <td className="py-3 px-3 tabular-nums" style={{ color: macro.color }}>
                    {macro.arrow && <span className="mr-0.5">{macro.arrow}</span>}{macro.display}
                  </td>
                  <td className="py-3 px-3 tabular-nums" style={{ color: funding.color }}>
                    {funding.arrow && <span className="mr-0.5">{funding.arrow}</span>}{funding.display}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="py-12 text-center text-[#707a8a]">
                  Không có coin phù hợp với bộ lọc.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 mt-6 pb-2">
          <button
            onClick={() => goTo(safePage - 1)}
            disabled={safePage === 1}
            className="w-8 h-8 flex items-center justify-center rounded text-[#707a8a] hover:bg-[#f5f5f5] disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="m15 18-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          {(() => {
            const pages = [];
            const delta = 2;
            const left = Math.max(2, safePage - delta);
            const right = Math.min(totalPages - 1, safePage + delta);

            pages.push(1);
            if (left > 2) pages.push("...");
            for (let i = left; i <= right; i++) pages.push(i);
            if (right < totalPages - 1) pages.push("...");
            if (totalPages > 1) pages.push(totalPages);

            return pages.map((p, idx) =>
              p === "..." ? (
                <span key={`ellipsis-${idx}`} className="w-8 h-8 flex items-center justify-center text-[#707a8a] text-[13px]">
                  …
                </span>
              ) : (
                <button
                  key={p}
                  onClick={() => goTo(p)}
                  className={`w-8 h-8 flex items-center justify-center rounded text-[13px] font-medium transition ${
                    safePage === p
                      ? "bg-[#4F46E5] text-white"
                      : "text-[#1e2329] hover:bg-[#f5f5f5]"
                  }`}
                >
                  {p}
                </button>
              )
            );
          })()}

          <button
            onClick={() => goTo(safePage + 1)}
            disabled={safePage === totalPages}
            className="w-8 h-8 flex items-center justify-center rounded text-[#707a8a] hover:bg-[#f5f5f5] disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}
