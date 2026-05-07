import { useEffect, useRef, useState } from "react";

/**
 * useBinanceWS — kết nối THẲNG Binance WebSocket từ browser.
 * Backend KHÔNG làm proxy giá.
 *
 * BẮT BUỘC (AGENTS.md quy tắc 4):
 *   - Throttle re-render xuống 1Hz qua useRef + setInterval (tránh
 *     250 setState/s khi có 50 coin).
 *   - Auto-reconnect với exponential backoff (Binance tự close
 *     connection sau 24h).
 *
 * @param {string[]} symbols — ví dụ ["btc","eth","sol"]
 * @returns {Object.<string, {price:number, change24h:number}>}
 */
export function useBinanceWS(symbols) {
  const [prices, setPrices] = useState({});
  const bufferRef = useRef({}); // ghi nhanh, không trigger render
  const wsRef = useRef(null);
  const reconnectRef = useRef({ attempts: 0, timer: null });
  const tickRef = useRef(null);

  const symbolsKey = symbols?.join(",") || "";

  useEffect(() => {
    if (!symbols?.length) return;

    let closedByEffect = false;

    const connect = () => {
      const streams = symbols
        .map((s) => `${s.toLowerCase()}usdt@ticker`)
        .join("/");
      const url = `wss://stream.binance.com:9443/stream?streams=${streams}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectRef.current.attempts = 0;
      };

      ws.onmessage = ({ data }) => {
        try {
          const parsed = JSON.parse(data);
          const d = parsed?.data;
          if (!d) return;
          // Ghi vào buffer — KHÔNG setState (throttle 1Hz dưới).
          bufferRef.current[d.s] = {
            price: parseFloat(d.c),
            change24h: parseFloat(d.P),
          };
        } catch {
          /* ignore malformed frame */
        }
      };

      ws.onclose = () => {
        if (closedByEffect) return;
        // Exponential backoff: 1s, 2s, 4s, 8s, ... tối đa 30s.
        const attempt = reconnectRef.current.attempts + 1;
        reconnectRef.current.attempts = attempt;
        const delay = Math.min(30000, 1000 * 2 ** (attempt - 1));
        reconnectRef.current.timer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // onclose sẽ được gọi sau onerror — để onclose xử lý reconnect.
        try {
          ws.close();
        } catch {
          /* noop */
        }
      };
    };

    // Flush buffer → state mỗi 1000ms (1Hz).
    tickRef.current = setInterval(() => {
      const buf = bufferRef.current;
      if (Object.keys(buf).length === 0) return;
      setPrices((prev) => ({ ...prev, ...buf }));
      bufferRef.current = {};
    }, 1000);

    connect();

    return () => {
      closedByEffect = true;
      if (reconnectRef.current.timer) {
        clearTimeout(reconnectRef.current.timer);
        reconnectRef.current.timer = null;
      }
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* noop */
        }
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey]);

  return prices;
}
