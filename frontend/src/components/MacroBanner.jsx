// frontend/src/components/MacroBanner.jsx
import { useEffect, useState } from "react";
import { formatVNTime } from "../utils/time";

/**
 * Banner sự kiện vĩ mô — lọc top 3 sự kiện sắp tới trong 24h.
 * Backend `/api/macro-events` trả { events: [...] }.
 */
export default function MacroBanner() {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/macro-events")
      .then((r) => (r.ok ? r.json() : { events: [] }))
      .then((d) => {
        if (cancelled) return;
        const upcoming = (d.upcoming_events || [])
          .sort((a, b) => {
            const da = new Date(a.date).getTime();
            const db = new Date(b.date).getTime();
            return da - db;
          })
          .slice(0, 5);
        setEvents(upcoming);
      })
      .catch(() => {
        /* im lặng */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (events.length === 0) return null;

  return (
    <div className="bg-[#fff8e6] border border-[#f7d978] rounded-lg p-3 mb-4">
      <div className="flex items-start gap-2">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="#f0b90b" className="mt-0.5 flex-shrink-0">
          <path d="M12 2 1 22h22L12 2Zm0 5 7.5 13H4.5L12 7Zm-1 4v4h2v-4h-2Zm0 5v2h2v-2h-2Z" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="text-[#b5840c] font-semibold text-[13px] mb-1">
            📅 Sự kiện kinh tế sắp tới (30 ngày):
          </div>
          {events.map((e, i) => {
            const name = e.event_name || e.event || "Sự kiện";
            const when = e.event_date || e.date;
            const daysAway = when
              ? Math.ceil((new Date(when).getTime() - Date.now()) / 86400000)
              : null;
            const daysLabel =
              daysAway !== null
                ? daysAway <= 0
                  ? " — Hôm nay"
                  : daysAway === 1
                  ? " — Ngày mai"
                  : ` — ${daysAway} ngày nữa`
                : "";
            const impactColor =
              (e.impact || "").toLowerCase() === "high"
                ? "text-red-500"
                : "text-yellow-600";
            return (
              <div key={i} className="text-[#474d57] text-[13px] break-words">
                •{" "}
                <span className="font-medium text-[#1e2329]">{name}</span>
                <span className={`ml-1 text-[11px] font-semibold uppercase ${impactColor}`}>
                  {e.impact}
                </span>
                <span className="text-[#b5840c]">{daysLabel}</span>
                {e.forecast ? (
                  <span className="text-[#474d57]"> | Dự báo: {e.forecast}</span>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
