// frontend/src/components/NewsCard.jsx
import { formatVNTime } from "../utils/time";

const BORDER = {
  positive: "#16a34a",
  neutral: "#eab308",
  negative: "#dc2626",
};

const LABEL = {
  positive: "Tăng giá",
  neutral: "Bình thường",
  negative: "Giảm giá",
};

const SOURCE = {
  coindesk: { text: "CoinDesk", color: "#2563eb" },
  forexfactory: { text: "📅 Lịch kinh tế", color: "#7c3aed" },
  reddit: { text: "Reddit", color: "#ea580c" },
};

export default function NewsCard({ item }) {
  const borderColor = BORDER[item.sentiment_label] ?? "#6b7280";
  const sourceInfo =
    SOURCE[item.source] ?? { text: item.source || "Nguồn", color: "#6b7280" };
  const score = Number(item.sentiment_score ?? 5);
  const barWidth = Math.max(0, Math.min(100, score * 10));

  return (
    <div
      className="bg-slate-800 rounded-lg p-4"
      style={{ borderLeft: `4px solid ${borderColor}` }}
    >
      {/* Badges */}
      <div className="flex gap-2 mb-2 flex-wrap items-center">
        <span
          className="px-2 py-1 rounded text-xs font-medium text-white"
          style={{ backgroundColor: borderColor }}
        >
          {LABEL[item.sentiment_label] ?? "—"}
        </span>
        <span
          className="px-2 py-1 rounded text-xs font-medium text-white"
          style={{ backgroundColor: sourceInfo.color }}
        >
          {sourceInfo.text}
        </span>
        <span className="text-slate-400 text-xs">
          {formatVNTime(item.published_at)}
        </span>
      </div>

      {/* Title */}
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-slate-100 font-semibold hover:text-yellow-400 transition block mb-2 break-words line-clamp-2"
      >
        {item.title}
      </a>

      {/* Score bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{
              width: `${barWidth}%`,
              backgroundColor: borderColor,
            }}
          ></div>
        </div>
        <span className="text-slate-400 text-xs tabular-nums">
          {score.toFixed(1)}/10
        </span>
      </div>

      {/* Reason (chỉ hiển thị khi có) */}
      {item.reason && (
        <p className="text-slate-300 text-sm mt-2 break-words">
          💡 {item.reason}
        </p>
      )}

      {/* Reddit: upvote + comment */}
      {item.source === "reddit" && (
        <div className="flex gap-4 text-slate-400 text-xs mt-2">
          <span>👍 {item.upvotes ?? 0}</span>
          <span>💬 {item.num_comments ?? 0}</span>
        </div>
      )}

      {/* ForexFactory: forecast/actual nếu có */}
      {item.source === "forexfactory" &&
        (item.forecast || item.actual) && (
          <div className="flex gap-4 text-slate-400 text-xs mt-2">
            {item.forecast && <span>Dự báo: {item.forecast}</span>}
            {item.actual && <span>Thực tế: {item.actual}</span>}
          </div>
        )}
    </div>
  );
}
