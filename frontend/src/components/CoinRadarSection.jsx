// frontend/src/components/CoinRadarSection.jsx
import { useEffect, useState } from "react";
import CoinRadarChart from "./RadarChart";
import InfoTooltip from "./InfoTooltip";
import { formatVNTime } from "../utils/time";

// Ghi chú giải thích từng trục — hiện khi hover tên tiêu chí.
const AXIS_TOOLTIPS = {
  "Tin tức":
    "Điểm cảm xúc FinBERT từ tiêu đề tin CoinDesk trong 24H",
  "Vĩ mô":
    "Điểm tác động của các sự kiện kinh tế vĩ mô sắp tới",
  "Funding Rate":
    "Tỷ lệ tài trợ (Funding Rate) trên Binance Futures",
  "Thảo luận trên mạng xã hội":
    "Khối lượng đề cập coin trên MXH trong 24H",
};

const scoreToRowLabel = (score) => {
  const s = Number(score ?? 0);
  if (s <= 0) return { text: "—", color: "#707a8a" };
  if (s >= 6.5) return { text: "Tăng giá", color: "#0ECB81" };
  if (s >= 4.5) return { text: "Bình thường", color: "#707a8a" };
  return { text: "Giảm giá", color: "#F6465D" };
};

const eventLabelColor = (label) =>
  label === "positive"
    ? "#0ECB81"
    : label === "negative"
    ? "#F6465D"
    : "#F0B90B";

const eventLabelText = (label) =>
  label === "positive"
    ? "Tích cực"
    : label === "negative"
    ? "Tiêu cực"
    : "Chờ kết quả";

export default function CoinRadarSection({ coin }) {
  const [macroEvents, setMacroEvents] = useState([]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/macro-events")
      .then((r) => (r.ok ? r.json() : { events: [] }))
      .then((d) => {
        if (cancelled) return;
        const now = Date.now();
        const upcoming = (d.events || [])
          .filter((e) => {
            const raw = e.event_date || e.date;
            if (!raw) return false;
            const t = new Date(raw).getTime();
            return !Number.isNaN(t) && t > now;
          })
          .sort((a, b) => {
            const da = new Date(a.event_date || a.date).getTime();
            const db = new Date(b.event_date || b.date).getTime();
            return da - db;
          })
          .slice(0, 3);
        setMacroEvents(upcoming);
      })
      .catch(() => {
        /* im lặng — không block UI */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hasData = (coin.score_total ?? 0) > 0;
  const rows = [
    { name: "Tin tức", score: coin.score_news },
    { name: "Vĩ mô", score: coin.score_macro },
    { name: "Funding Rate", score: coin.score_funding },
    {
      name: "Thảo luận trên mạng xã hội",
      score: coin.score_social,
      // Hiển thị KHỐI LƯỢNG đề cập thay vì nhãn Tăng giá / Bình thường.
      mentions: coin.social_mentions,
    },
  ];

  return (
    <div className="px-6 mt-6">
      <div className="bg-white border border-[#eaecef] rounded-lg p-6">
        <h2 className="text-[16px] font-semibold text-[#1e2329] mb-5">
          Xếp hạng của AI
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
          <div className="flex flex-col items-center">
            <CoinRadarChart
              coin={coin}
              size={320}
              centerScore={hasData ? Number(coin.score_total).toFixed(2) : "—"}
              centerLabel={coin.label}
            />
          </div>

          <div className="divide-y divide-[#f5f5f5]">
            <Row name="Xếp hạng" value={`No. ${coin.rank}`} />
            {rows.map((r) => {
              const isSocial = r.mentions !== undefined;
              // Social → hiển thị số lượng đề cập (có thể = 0 / null).
              // Các trục khác → nhãn sentiment (Tăng giá / Giảm giá / ...).
              const value = isSocial ? (
                <span className="text-[#1e2329] font-medium tabular-nums">
                  {r.mentions != null ? r.mentions : "—"}
                </span>
              ) : (
                (() => {
                  const lbl = scoreToRowLabel(r.score);
                  return (
                    <span
                      className="font-medium"
                      style={{ color: lbl.color }}
                    >
                      {lbl.text}
                    </span>
                  );
                })()
              );
              const tip = AXIS_TOOLTIPS[r.name];
              return (
                <Row
                  key={r.name}
                  name={
                    tip ? (
                      <InfoTooltip text={tip}>
                        <span className="underline decoration-dotted decoration-[#c7cbd4] underline-offset-4">
                          {r.name}
                        </span>
                      </InfoTooltip>
                    ) : (
                      r.name
                    )
                  }
                  value={value}
                  hint={
                    Number(r.score ?? 0) > 0
                      ? `${Number(r.score).toFixed(2)}/10`
                      : null
                  }
                />
              );
            })}
          </div>
        </div>
      </div>

      <FundingRateExplainer score={coin.score_funding} symbol={coin.symbol} />

      {macroEvents.length > 0 && (
        <div className="mt-4 bg-white border border-[#eaecef] rounded-lg p-5">
          <div className="text-[14px] font-semibold text-[#1e2329] mb-3 break-words">
            Sự kiện kinh tế sắp tới ảnh hưởng đến {coin.symbol}
          </div>
          <div className="space-y-2">
            {macroEvents.map((e, i) => {
              const name = e.event_name || e.event || "Sự kiện";
              const when = e.event_date || e.date;
              const lab = e.sentiment_label || e.label;
              return (
                <div
                  key={i}
                  className="text-[13px] text-[#707a8a] flex items-start gap-2 break-words"
                >
                  <span className="text-[#c7cbd4]">•</span>
                  <div className="flex-1">
                    <span className="font-medium text-[#1e2329]">{name}</span>{" "}
                    ({e.currency || "USD"}) — {formatVNTime(when)}
                    {e.forecast ? ` — Dự báo: ${e.forecast}` : ""}
                    <span
                      className="ml-2 font-medium"
                      style={{ color: eventLabelColor(lab) }}
                    >
                      {eventLabelText(lab)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Panel giải thích Funding Rate — hiển thị ý nghĩa điểm số, vị trí
 * hiện tại trên thang [0, 10] và cách tính.
 */
function FundingRateExplainer({ score, symbol }) {
  const s = Number(score ?? 0);
  const hasData = s > 0;
  // Quy đổi ngược về funding rate:
  // score = 5 + (funding_rate * 2500) ⇒ funding_rate = (score - 5) / 2500
  const fundingRate = hasData ? (s - 5) / 2500 : null;

  let tone;
  if (!hasData) tone = { text: "Chưa có dữ liệu", color: "#707a8a" };
  else if (s >= 6.5) tone = { text: "Hưng phấn (Long áp đảo)", color: "#0ECB81" };
  else if (s >= 5.5) tone = { text: "Tích cực (Nghiêng về Long)", color: "#0ECB81" };
  else if (s > 4.5) tone = { text: "Cân bằng", color: "#707a8a" };
  else if (s > 3.5) tone = { text: "Tiêu cực (Nghiêng về Short)", color: "#F6465D" };
  else tone = { text: "Bi quan (Short áp đảo)", color: "#F6465D" };

  // Vị trí kim chỉ trên thang 0–10 (%).
  const markerPct = hasData ? (s / 10) * 100 : 50;

  return (
    <div className="mt-4 bg-white border border-[#eaecef] rounded-lg p-5">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="text-[14px] font-semibold text-[#1e2329]">
          Funding Rate của {symbol} là gì?
        </div>
        <div className="flex items-center gap-2 text-[12px]">
          <span className="text-[#707a8a]">Điểm hiện tại:</span>
          <span
            className="font-semibold tabular-nums"
            style={{ color: tone.color }}
          >
            {hasData ? `${s.toFixed(2)}/10` : "—"}
          </span>
          <span
            className="px-2 py-0.5 rounded text-[11px] font-medium"
            style={{
              color: tone.color,
              backgroundColor: `${tone.color}1A`,
            }}
          >
            {tone.text}
          </span>
        </div>
      </div>

      {/* Thang đo 0–10 với 3 vùng: Bán (đỏ) – Cân bằng (xám) – Mua (xanh) */}
      <div className="relative h-2 rounded-full overflow-hidden bg-[#f5f5f5] mb-1">
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: "100%",
            background:
              "linear-gradient(to right, #F6465D 0%, #F6465D 35%, #EAECEF 45%, #EAECEF 55%, #0ECB81 65%, #0ECB81 100%)",
          }}
        />
        {hasData && (
          <div
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2 border-white shadow"
            style={{
              left: `${markerPct}%`,
              backgroundColor: tone.color,
            }}
          />
        )}
      </div>
      <div className="flex justify-between text-[11px] text-[#707a8a] mb-4">
        <span>0 · Short áp đảo (Bi quan)</span>
        <span>5 · Cân bằng</span>
        <span>10 · Long áp đảo (Hưng phấn)</span>
      </div>

      <div className="text-[13px] text-[#474d57] leading-relaxed space-y-2">
        <p>
          <b>Funding Rate</b> (Tỉ lệ tài trợ) là khoản phí mà phe Long phải trả cho phe Short (hoặc ngược lại) để giữ giá phái sinh bám sát giá Spot trên hợp đồng perpetual{" "}
          <span className="font-mono">{symbol}USDT</span> của Binance Futures. Đây là chỉ báo thể hiện mức độ hưng phấn hay bi quan của đám đông sử dụng đòn bẩy.
        </p>
        <p>
          Funding dương cao (phe Long áp đảo) phản ánh thị trường đang <b>hưng phấn, kỳ vọng tăng giá</b> — điểm cảm xúc cao.
          Funding âm sâu (phe Short áp đảo) phản ánh thị trường đang <b>bi quan, lo ngại giảm giá</b> — điểm cảm xúc thấp.
        </p>
        {hasData && fundingRate !== null && (
          <p className="text-[#707a8a]">
            Ở điểm hiện tại, Funding Rate ước tính ≈{" "}
            <span
              className="font-semibold tabular-nums"
              style={{ color: fundingRate >= 0 ? "#0ECB81" : "#F6465D" }}
            >
              {fundingRate >= 0 ? "+" : ""}
              {(fundingRate * 100).toFixed(4)}%
            </span>{" "}
            mỗi 8 giờ.
          </p>
        )}
      </div>
    </div>
  );
}

function Row({ name, value, hint }) {
  return (
    <div className="flex items-center justify-between py-3 text-[14px]">
      <span className="text-[#707a8a]">{name}</span>
      <div className="flex items-center gap-3">
        {hint && (
          <span className="text-[12px] font-medium text-[#707a8a] tabular-nums">
            {hint}
          </span>
        )}
        <span className="text-[#1e2329]">{value}</span>
      </div>
    </div>
  );
}
