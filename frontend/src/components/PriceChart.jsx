// frontend/src/components/PriceChart.jsx
import { useEffect, useRef } from "react";

/**
 * TradingView widget — timezone Asia/Ho_Chi_Minh (quy tắc 4).
 * Handle cleanup: loại bỏ script và innerHTML khi unmount.
 */
export default function PriceChart({ symbol }) {
  const containerRef = useRef(null);
  const scriptRef = useRef(null);
  const containerId = `tv_${(symbol || "btc").toLowerCase()}`;

  useEffect(() => {
    if (!symbol) return undefined;

    const mount = () => {
      if (!window.TradingView || !containerRef.current) return;
      containerRef.current.innerHTML = "";
      // eslint-disable-next-line no-new
      new window.TradingView.widget({
        container_id: containerId,
        width: "100%",
        height: 450,
        symbol: `BINANCE:${symbol.toUpperCase()}USDT`,
        interval: "60",
        timezone: "Asia/Ho_Chi_Minh",
        theme: "light",
        locale: "vi_VN",
        toolbar_bg: "#ffffff",
        enable_publishing: false,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        style: "1",
      });
    };

    if (window.TradingView) {
      mount();
    } else {
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/tv.js";
      script.async = true;
      script.onload = mount;
      scriptRef.current = script;
      document.head.appendChild(script);
    }

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = "";
      if (scriptRef.current) {
        try {
          scriptRef.current.remove();
        } catch {
          /* noop */
        }
        scriptRef.current = null;
      }
    };
  }, [symbol, containerId]);

  return (
    <div className="px-6 mt-6">
      <div className="bg-white border border-[#eaecef] rounded-lg p-5">
        <h2 className="text-[16px] font-semibold text-[#1e2329] mb-4">
          Biểu đồ giá
        </h2>
        <div id={containerId} ref={containerRef}></div>
        <div className="text-[#707a8a] text-[11px] mt-2 text-center">
          Dữ liệu từ Binance • Giờ hiển thị: Việt Nam (UTC+7)
        </div>
      </div>
    </div>
  );
}
