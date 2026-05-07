// frontend/src/components/RadarChart.jsx
import { memo, useMemo } from "react";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";

/**
 * Mapping nhãn Cryptsen → (stroke, fill) phong cách Binance Light.
 * Tông chủ đạo: mint xanh cho "tích cực", vàng cho "bình thường",
 * đỏ-hồng cho "tiêu cực".
 */
const PALETTE = {
  "Hoàn toàn tích cực": { stroke: "#0ECB81", fill: "#BFF0D9" },
  "Tích cực": { stroke: "#0ECB81", fill: "#D7F5E5" },
  "Bình thường": { stroke: "#F0B90B", fill: "#FDEFC4" },
  "Tiêu cực": { stroke: "#F6465D", fill: "#FCD3D8" },
  "Hoàn toàn tiêu cực": { stroke: "#F6465D", fill: "#F8B6BE" },
  "Không có dữ liệu": { stroke: "#C7CBD4", fill: "#ECEEF2" },
};

const LABEL_COLOR = {
  "Hoàn toàn tích cực": "#0ECB81",
  "Tích cực": "#0ECB81",
  "Bình thường": "#F0B90B",
  "Tiêu cực": "#F6465D",
  "Hoàn toàn tiêu cực": "#F6465D",
  "Không có dữ liệu": "#707a8a",
};

export const getLabelColor = (label) => LABEL_COLOR[label] ?? "#707a8a";

/**
 * Factory tạo tick renderer: nhận map { axisName: scoreText } qua closure,
 * trả về component hợp lệ cho Recharts. Tránh truyền object làm giá trị
 * dataKey (Recharts không tính được góc + React cảnh báo).
 */
const makeAxisTick = (scoreMap) => (props) => {
  const { x, y, cx, cy, payload } = props;
  const name = payload?.value;
  const score = scoreMap[name] ?? "—";
  const dy = y < cy ? -14 : 20;
  return (
    <g transform={`translate(${x}, ${y + dy})`}>
      <text textAnchor="middle" fill="#707a8a" fontSize={11} fontWeight={500}>
        {name}
      </text>
      <text
        x={0}
        y={13}
        textAnchor="middle"
        fill="#1e2329"
        fontSize={11}
        fontWeight={600}
      >
        {score}
      </text>
    </g>
  );
};

/**
 * CoinRadarChart — 4 trục Cryptsen: Mạng xã hội (top), Funding (right),
 * Tâm lý xã hội/Vĩ mô (bottom), Tin tức (left). Hiển thị mini-card Binance.
 *
 * Props:
 *  - coin: { label, score_*, ... }
 *  - size: chiều cao vùng vẽ
 *  - centerScore, centerLabel: text chồng giữa diamond (tùy chọn)
 */
function CoinRadarChart({ coin, size = 220, centerScore, centerLabel }) {
  const { stroke, fill } = PALETTE[coin.label] ?? PALETTE["Không có dữ liệu"];
  const hasData = (coin.score_total ?? 0) > 0;
  const color = getLabelColor(coin.label);
  const showCenter = centerScore !== undefined || centerLabel !== undefined;

  // Memo theo điểm 4 trục → identity ổn định dù parent re-render do WebSocket giá.
  const { data, AxisTick } = useMemo(() => {
    const fmt = (v) => (Number(v ?? 0) > 0 ? Number(v).toFixed(2) : "—");
    const map = {
      "Mạng xã hội": fmt(coin.score_social),
      "Funding Rate": fmt(coin.score_funding),
      "Vĩ mô": fmt(coin.score_macro),
      "Tin tức": fmt(coin.score_news),
    };
    return {
      data: [
        { axis: "Mạng xã hội", value: Number(coin.score_social ?? 0) },
        { axis: "Funding Rate", value: Number(coin.score_funding ?? 0) },
        { axis: "Vĩ mô", value: Number(coin.score_macro ?? 0) },
        { axis: "Tin tức", value: Number(coin.score_news ?? 0) },
      ],
      AxisTick: makeAxisTick(map),
    };
  }, [
    coin.score_social,
    coin.score_funding,
    coin.score_macro,
    coin.score_news,
  ]);

  return (
    <div className="relative w-full" style={{ height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} outerRadius="60%" cx="50%" cy="50%">
          <PolarGrid stroke="#EAECEF" strokeDasharray="0" gridType="polygon" />
          <PolarAngleAxis dataKey="axis" tick={AxisTick} tickLine={false} />
          <PolarRadiusAxis
            domain={[0, 10]}
            tick={false}
            axisLine={false}
            stroke="#EAECEF"
          />
          <Radar
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.5}
            fill={fill}
            fillOpacity={hasData ? 0.85 : 0.35}
            isAnimationActive={false}
          />
        </RadarChart>
      </ResponsiveContainer>

      {showCenter && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div
            className="text-[26px] font-bold leading-none"
            style={{ color: "#1e2329" }}
          >
            {centerScore}
          </div>
          {centerLabel && (
            <div
              className="text-[11px] mt-1 font-medium"
              style={{ color }}
            >
              {centerLabel}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// memo → tránh re-render khi parent cập nhật do WebSocket giá,
// nguyên nhân chính gây nhấp nháy Recharts.
export default memo(CoinRadarChart, (prev, next) => {
  return (
    prev.size === next.size &&
    prev.centerScore === next.centerScore &&
    prev.centerLabel === next.centerLabel &&
    prev.coin.label === next.coin.label &&
    prev.coin.score_total === next.coin.score_total &&
    prev.coin.score_news === next.coin.score_news &&
    prev.coin.score_macro === next.coin.score_macro &&
    prev.coin.score_funding === next.coin.score_funding &&
    prev.coin.score_social === next.coin.score_social
  );
});
