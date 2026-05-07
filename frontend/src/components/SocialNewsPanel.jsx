// frontend/src/components/SocialNewsPanel.jsx
import { useMemo, useState } from "react";
import { formatVNTime } from "../utils/time";

/**
 * SocialNewsPanel — Layout 2 cột.
 *  - Trái: "Bài đăng MXH" (Reddit + Telegram) + thống kê + progress bar + pill tabs.
 *  - Phải: "Tin tức mới nhất" (CoinDesk + Telegram coin) + Vĩ Mô (FRED + CoinDesk macro + Telegram macro).
 *
 * Props:
 *  - coin:       object coin (summary, symbol, name)
 *  - social:     Reddit items (source=reddit)
 *  - news:       CoinDesk + Telegram coin items
 *  - macroEvents: FRED events
 *  - macroNews:  CoinDesk macro + Telegram macro items
 */
export default function SocialNewsPanel({
  coin,
  social = [],
  news = [],
  macroEvents = [],
  macroNews = [],
}) {
  // Gộp Reddit vào cột trái
  const allSocialPosts = useMemo(() => {
    return (social || []).map((s) => ({ ...s, _src: "reddit" })).sort((a, b) => {
      const ta = new Date(a.published_at || 0).getTime();
      const tb = new Date(b.published_at || 0).getTime();
      return tb - ta;
    });
  }, [social]);

  const counts = (items) => {
    const c = { positive: 0, neutral: 0, negative: 0 };
    for (const it of items) if (it.sentiment_label in c) c[it.sentiment_label] += 1;
    return c;
  };

  // Tin coin (CoinDesk + Telegram coin)
  const coinNews = useMemo(() => {
    return (news || []).map((n) => ({ ...n, kind: "news" }));
  }, [news]);

  // Timeline vĩ mô: FRED events + macro news (CoinDesk + Telegram macro)
  const macroTimeline = useMemo(() => {
    const macroN = (macroNews || []).map((n) => ({
      ...n,
      kind: "macro-news",
      id: n.id ?? n.url,
    }));
    const macroE = (macroEvents || []).map((e) => ({
      ...e,
      kind: "macro-event",
      sentiment_label: e.sentiment_label || e.label,
      published_at:
        e.published_at ||
        e.event_date ||
        (e.date ? new Date(e.date).toISOString() : null),
    }));
    return [...macroN, ...macroE].sort((a, b) => {
      const ta = new Date(a.published_at || 0).getTime();
      const tb = new Date(b.published_at || 0).getTime();
      return tb - ta;
    });
  }, [macroNews, macroEvents]);

  const socialCounts = useMemo(() => counts(allSocialPosts), [allSocialPosts]);
  const newsCounts = useMemo(() => counts(coinNews), [coinNews]);

  const bullShare = (() => {
    const up = socialCounts.positive;
    const down = socialCounts.negative;
    const tot = up + down;
    if (tot === 0) return 50;
    return Math.round((up / tot) * 100);
  })();

  return (
    <div className="px-6 mt-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SocialColumn
          social={allSocialPosts}
          stats={{
            reddit: social.length,
            total: allSocialPosts.length,
          }}
          counts={socialCounts}
          bullShare={bullShare}
        />
        <NewsColumn
          coin={coin}
          news={coinNews}
          macroTimeline={macroTimeline}
          counts={newsCounts}
        />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Left: Social (Reddit)                                            */
/* -------------------------------------------------------------------------- */

function SocialColumn({ social, stats, counts, bullShare }) {
  const [tab, setTab] = useState("all");
  const filtered = useMemo(() => {
    if (tab === "all") return social;
    return social.filter((s) => s.sentiment_label === tab);
  }, [social, tab]);

  const bearShare = 100 - bullShare;

  const tabs = [
    { key: "all", label: `Tất cả(${social.length})`, cls: "bg-[#f5f5f5] text-[#1e2329]" },
    {
      key: "positive",
      label: `Tăng giá(${fmtShort(counts.positive)})`,
      cls: "bg-[#D7F5E5] text-[#0ECB81]",
    },
    {
      key: "neutral",
      label: `Bình thường(${fmtShort(counts.neutral)})`,
      cls: "bg-[#FDEFC4] text-[#B5840C]",
    },
    {
      key: "negative",
      label: `Giảm giá(${fmtShort(counts.negative)})`,
      cls: "bg-[#FCD3D8] text-[#F6465D]",
    },
  ];

  return (
    <div className="bg-white border border-[#eaecef] rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[16px] font-semibold text-[#1e2329]">
          Bài đăng trên MXH
        </h3>
        {/* Source badges */}
        <div className="flex gap-1.5">
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#FF4500]/10 text-[#FF4500] text-[11px] font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-[#FF4500] inline-block" />
            Reddit ({stats.reddit})
          </span>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <Stat label="Tổng bài 24h" value={fmtShort(stats.total)} />
        <Stat label="Tăng giá" value={fmtShort(counts.positive)} color="#0ECB81" />
        <Stat label="Giảm giá" value={fmtShort(counts.negative)} color="#F6465D" />
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-[11px] mb-1">
          <span className="text-[#0ECB81] font-medium">Tăng giá {bullShare}%</span>
          <span className="text-[#F6465D] font-medium">Giảm giá {bearShare}%</span>
        </div>
        <div className="flex h-1.5 rounded-full overflow-hidden bg-[#eaecef]">
          <div className="bg-[#0ECB81]" style={{ width: `${bullShare}%` }} />
          <div className="bg-[#F6465D]" style={{ width: `${bearShare}%` }} />
        </div>
      </div>

      {/* Pill tabs */}
      <div className="flex flex-wrap gap-2 mb-4">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={
              "px-3 py-1 rounded-full text-[12px] font-medium transition " +
              (tab === t.key
                ? t.cls
                : "text-[#707a8a] hover:bg-[#f5f5f5]")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div className="feed-scroll space-y-4 max-h-[540px] overflow-y-auto pr-1">
        {filtered.length === 0 && (
          <div className="py-10 text-center text-[#707a8a] text-[13px]">
            Không có bài đăng.
          </div>
        )}
        {filtered.map((item) =>
          <SocialPost key={`rd-${item.id ?? item.url}`} item={item} />
        )}
      </div>
    </div>
  );
}

function SocialPost({ item }) {
  const sub =
    item.subreddit || item.reason || extractSubreddit(item.url) || "reddit";
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-[#FF4500] text-white flex items-center justify-center text-[11px] font-semibold flex-shrink-0">
        r/
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-[12px] font-medium text-[#1e2329] mb-1">
          <span className="text-[#FF4500]">r/{sub}</span>
          <span className="text-[#707a8a] text-[11px]">
            {formatVNTime(item.published_at)}
          </span>
        </div>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-[13px] text-[#474d57] hover:text-[#f0b90b] leading-relaxed break-words line-clamp-3"
        >
          {item.title}
        </a>
        <div className="mt-1 flex items-center gap-3 text-[11px] text-[#707a8a]">
          {item.upvotes !== undefined && item.upvotes !== null && (
            <span>▲ {item.upvotes}</span>
          )}
          {item.num_comments !== undefined && item.num_comments !== null && (
            <span>💬 {item.num_comments}</span>
          )}
          {item.sentiment_label && (
            <span className={sentimentPillCls(item.sentiment_label)}>
              {sentimentLabelVN(item.sentiment_label)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}


function Stat({ label, value, color }) {
  return (
    <div>
      <div className="text-[11px] text-[#707a8a] mb-0.5">{label}</div>
      <div
        className="text-[18px] font-semibold"
        style={{ color: color || "#1e2329" }}
      >
        {value}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Right: News (Tin tức + Vĩ mô)                                              */
/* -------------------------------------------------------------------------- */

function NewsColumn({ coin, news, macroTimeline = [], counts }) {
  const [tab, setTab] = useState("all");
  const [summaryOpen, setSummaryOpen] = useState(false);

  // Lấy nhãn sentiment của 1 macro item (event hoặc news)
  const getMacroLabel = (item) =>
    item.kind === "macro-event" ? item.label : item.sentiment_label;

  const filtered = useMemo(() => {
    if (tab === "all") return news;
    return news.filter((n) => n.sentiment_label === tab);
  }, [news, tab]);

  const filteredMacro = useMemo(() => {
    if (tab === "all") return macroTimeline;
    return macroTimeline.filter((item) => getMacroLabel(item) === tab);
  }, [macroTimeline, tab]);

  const macroCounts = useMemo(() => ({
    positive: macroTimeline.filter((i) => getMacroLabel(i) === "positive").length,
    neutral:  macroTimeline.filter((i) => getMacroLabel(i) === "neutral").length,
    negative: macroTimeline.filter((i) => getMacroLabel(i) === "negative").length,
  }), [macroTimeline]);

  const tabs = [
    {
      key: "all",
      label: `Tất cả(${news.length + macroTimeline.length})`,
      cls: "bg-[#eaecef] text-[#1e2329]",
    },
    {
      key: "positive",
      label: `Tăng giá(${counts.positive + macroCounts.positive})`,
      cls: "bg-[#D7F5E5] text-[#0ECB81]",
    },
    {
      key: "neutral",
      label: `Bình thường(${counts.neutral + macroCounts.neutral})`,
      cls: "bg-[#FDEFC4] text-[#B5840C]",
    },
    {
      key: "negative",
      label: `Giảm giá(${counts.negative + macroCounts.negative})`,
      cls: "bg-[#FCD3D8] text-[#F6465D]",
    },
  ];

  const summary = coin?.summary || "";
  const isLongSummary = summary.length > 180;

  // Đếm bài telegram trong news feed
  const tgCount = useMemo(
    () => news.filter((n) => n.source === "telegram").length,
    [news]
  );

  return (
    <div className="bg-white border border-[#eaecef] rounded-lg p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[16px] font-semibold text-[#1e2329]">
          Tin tức mới nhất
        </h3>
        {tgCount > 0 && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#229ED9]/10 text-[#229ED9] text-[11px] font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-[#229ED9] inline-block" />
            +{tgCount} Telegram
          </span>
        )}
      </div>

      {summary && (
        <div className="mb-4">
          <p
            className={
              "text-[13px] text-[#707a8a] leading-relaxed " +
              (summaryOpen || !isLongSummary ? "" : "line-clamp-3")
            }
          >
            {summary}
          </p>
          {isLongSummary && (
            <button
              type="button"
              onClick={() => setSummaryOpen((v) => !v)}
              className="mt-1 text-[12px] font-medium text-[#f0b90b] hover:underline"
            >
              {summaryOpen ? "Thu gọn" : "Xem thêm"}
            </button>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={
              "px-3 py-1 rounded-full text-[12px] font-medium transition " +
              (tab === t.key
                ? t.cls
                : "text-[#707a8a] hover:bg-[#f5f5f5]")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tin tức — scroll riêng, không đẩy Vĩ mô xuống */}
      <div className="feed-scroll space-y-4 max-h-[320px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-[#707a8a] text-[13px]">
            Không có tin coin trong 24h.
          </div>
        ) : (
          filtered.map((item) => {
            const key = item.id ?? item.url ?? item.event;
            return <NewsRow key={`n-${key}`} item={item} />;
          })
        )}
      </div>

      {/* Bối cảnh vĩ mô — luôn hiển thị, scroll riêng, lọc theo tab */}
      {macroTimeline.length > 0 && (
        <div className="mt-4">
          {/* Header nổi bật với accent bar */}
          <div className="flex items-center justify-between px-3 py-2 mb-3 bg-[#fffbeb] border border-[#f0b90b]/30 rounded-lg">
            <div className="flex items-center gap-2">
              <div className="w-1 h-4 rounded-full bg-[#f0b90b]" />
              <span className="text-[13px] font-bold text-[#1e2329] tracking-wide">
                Bối cảnh vĩ mô
              </span>
              <span className="text-[11px] text-[#707a8a]">
                ({filteredMacro.length}/{macroTimeline.length})
              </span>
            </div>
            {(() => {
              const tgMacro = macroTimeline.filter(
                (it) => it.kind === "macro-news" && it.source?.startsWith("macro-telegram")
              ).length;
              return tgMacro > 0 ? (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#229ED9]/10 text-[#229ED9] text-[10px] font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#229ED9] inline-block" />
                  +{tgMacro} Telegram
                </span>
              ) : null;
            })()}
          </div>
          <div className="feed-scroll space-y-4 max-h-[280px] overflow-y-auto pr-1">
            {filteredMacro.length === 0 ? (
              <div className="py-6 text-center text-[#707a8a] text-[13px]">
                Không có tin vĩ mô phù hợp.
              </div>
            ) : (
              filteredMacro.map((item) => {
                const key = item.id ?? item.url ?? item.event;
                if (item.kind === "macro-event") {
                  return <MacroEventRow key={`e-${key}`} ev={item} />;
                }
                return <NewsRow key={`m-${key}`} item={item} />;
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MacroEventRow({ ev }) {
  const impactCls = {
    High: "bg-[#FCD3D8] text-[#F6465D]",
    Medium: "bg-[#FDEFC4] text-[#B5840C]",
    Low: "bg-[#eaecef] text-[#707a8a]",
  }[ev.impact] || "bg-[#eaecef] text-[#707a8a]";

  const verdictCls = {
    positive: "bg-[#D7F5E5] text-[#0ECB81]",
    negative: "bg-[#FCD3D8] text-[#F6465D]",
    neutral: "bg-[#FDEFC4] text-[#B5840C]",
  }[ev.label] || "bg-[#eaecef] text-[#707a8a]";

  const verdictText = {
    positive: "Tin tốt",
    negative: "Tin xấu",
    neutral: "Trung tính",
  }[ev.label] || "—";

  const changePct = ev.change_pct;
  const changeStr =
    changePct === undefined || changePct === null
      ? "—"
      : `${changePct > 0 ? "+" : ""}${changePct.toFixed(2)}%`;
  const changeCls =
    changePct > 0
      ? "text-[#0ECB81]"
      : changePct < 0
      ? "text-[#F6465D]"
      : "text-[#707a8a]";

  return (
    <div className="border-b border-[#f5f5f5] pb-3 last:border-0">
      <div className="flex items-center gap-2 mb-1">
        <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${impactCls}`}>
          {ev.impact || "—"}
        </span>
        <span className="text-[11px] text-[#707a8a]">{ev.currency || "USD"}</span>
        <span className="text-[11px] text-[#707a8a]">{ev.date}</span>
        <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-medium ${verdictCls}`}>
          {verdictText}
        </span>
      </div>
      <div className="text-[13px] font-medium text-[#1e2329] mb-1">
        {ev.event}
      </div>
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-1">
        <MacroCell label="Actual" value={ev.actual} />
        <MacroCell label="Forecast" value={ev.forecast || "—"} />
        <MacroCell label="Previous" value={ev.previous} />
      </div>
      <div className="text-[11px] text-[#707a8a]">
        Thay đổi: <span className={`font-medium ${changeCls}`}>{changeStr}</span>
      </div>
      {ev.consequence && (
        <div className="text-[12px] text-[#474d57] mt-1 leading-relaxed">
          <span className="text-[#707a8a]">Hệ quả: </span>
          {ev.consequence}
        </div>
      )}
    </div>
  );
}

function MacroCell({ label, value }) {
  return (
    <div className="bg-[#f8f9fa] rounded px-2 py-1">
      <div className="text-[10px] text-[#707a8a]">{label}</div>
      <div className="text-[12px] font-medium text-[#1e2329] truncate">
        {value || "—"}
      </div>
    </div>
  );
}

function NewsRow({ item }) {
  const isTelegram =
    item.source === "telegram" || item.source?.startsWith("macro-telegram");
  return (
    <div className="border-b border-[#f5f5f5] pb-3 last:border-0">
      <div className="flex items-center gap-2 text-[11px] text-[#707a8a] mb-1">
        <span>{formatVNTime(item.published_at)}</span>
        {item.source && (
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-medium ${
              isTelegram
                ? "bg-[#229ED9]/10 text-[#229ED9]"
                : "bg-[#f5f5f5] text-[#707a8a]"
            }`}
          >
            {prettySource(item.source)}
          </span>
        )}
        {item.kind === "macro-news" && (
          <span className="px-1.5 py-0.5 rounded bg-[#E6EEFB] text-[#1E62E0] text-[10px]">
            Vĩ mô
          </span>
        )}
        {item.sentiment_label && (
          <span className={sentimentPillCls(item.sentiment_label)}>
            {sentimentLabelVN(item.sentiment_label)}
          </span>
        )}
      </div>
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className={`block text-[13px] font-medium leading-snug break-words line-clamp-2 ${
          isTelegram
            ? "text-[#1e2329] hover:text-[#229ED9]"
            : "text-[#1e2329] hover:text-[#f0b90b]"
        }`}
      >
        {item.title}
      </a>
      {item.reason && item.source !== "reddit" && !isTelegram && (
        <p className="mt-1 text-[12px] text-[#707a8a] leading-relaxed line-clamp-2">
          <span className="font-medium text-[#474d57]">Phân tích: </span>
          {item.reason}
        </p>
      )}
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className={`inline-block mt-1 text-[12px] hover:underline ${
            isTelegram ? "text-[#229ED9]" : "text-[#f0b90b]"
          }`}
        >
          Xem thêm
        </a>
      )}
    </div>
  );
}

function prettySource(src) {
  if (!src) return "";
  const s = String(src).toLowerCase();
  if (s === "macro-coindesk" || s === "coindesk") return "CoinDesk";
  if (s === "macro-investing") return "Investing";
  if (s?.startsWith("macro-telegram") || s === "telegram") return "Telegram";
  return src;
}

/* utils */
function fmtShort(n) {
  if (n === undefined || n === null) return "0";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function extractSubreddit(url) {
  if (!url) return "";
  const m = url.match(/reddit\.com\/r\/([^/]+)/i);
  return m ? m[1] : "";
}

function sentimentLabelVN(lbl) {
  return (
    {
      positive: "Tăng giá",
      negative: "Giảm giá",
      neutral: "Trung tính",
    }[lbl] || lbl
  );
}

function sentimentPillCls(lbl) {
  const base = "px-1.5 py-0.5 rounded text-[10px] font-medium ";
  return (
    base +
    ({
      positive: "bg-[#D7F5E5] text-[#0ECB81]",
      negative: "bg-[#FCD3D8] text-[#F6465D]",
      neutral: "bg-[#FDEFC4] text-[#B5840C]",
    }[lbl] || "bg-[#eaecef] text-[#707a8a]")
  );
}
