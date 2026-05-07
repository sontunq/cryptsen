// frontend/src/components/NewsFeed.jsx
import { useMemo, useState } from "react";
import NewsCard from "./NewsCard";

/**
 * NewsFeed — 3 tab sentiment + "Tất cả". Dùng chung cho CoinDesk & Reddit.
 */
export default function NewsFeed({ items = [], title = "📰 Tin tức" }) {
  const [activeTab, setActiveTab] = useState("all");

  const counts = useMemo(() => {
    const c = { positive: 0, neutral: 0, negative: 0 };
    for (const it of items) {
      if (it.sentiment_label in c) c[it.sentiment_label] += 1;
    }
    return c;
  }, [items]);

  const filtered = useMemo(() => {
    if (activeTab === "all") return items;
    return items.filter((i) => i.sentiment_label === activeTab);
  }, [items, activeTab]);

  const tabs = [
    {
      key: "all",
      label: `Tất cả (${items.length})`,
      active: "bg-yellow-600 text-white",
    },
    {
      key: "positive",
      label: `🟢 Tăng giá (${counts.positive})`,
      active: "bg-green-600 text-white",
    },
    {
      key: "neutral",
      label: `🟡 Bình thường (${counts.neutral})`,
      active: "bg-yellow-600 text-white",
    },
    {
      key: "negative",
      label: `🔴 Giảm giá (${counts.negative})`,
      active: "bg-red-600 text-white",
    },
  ];

  return (
    <div className="p-6 border-b border-slate-700">
      <h2 className="text-xl font-semibold text-white mb-4">{title}</h2>

      <div className="flex gap-2 mb-4 flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={
              "px-4 py-2 rounded text-sm transition " +
              (activeTab === t.key
                ? t.active
                : "bg-slate-700 text-slate-300 hover:bg-slate-600")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-4">
        {filtered.length === 0 && (
          <div className="text-slate-400 text-center py-8">
            Không có tin tức.
          </div>
        )}
        {filtered.map((item) => (
          <NewsCard key={item.id ?? item.url} item={item} />
        ))}
      </div>
    </div>
  );
}
