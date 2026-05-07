import { useEffect, useState } from "react";
import { NavLink, Link } from "react-router-dom";

/**
 * Navbar — Cryptsen (sản phẩm phân tích tâm lý crypto, KHÔNG phải sàn giao dịch).
 * Logo riêng (icon radar) + 5 tab: Trang chủ / Thị trường / Phân tích tâm lý /
 * Tin Tức / Cộng đồng. Click logo → "/".
 */
const TABS = [
  { to: "/cryptosentiment", label: "Phân tích tâm lý" },
];

/** Logo riêng: hình radar 4 cạnh trong vòng tròn, tông xanh-indigo để KHÔNG
 *  trùng với bộ nhận diện Binance (vàng). */
function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="cs-logo" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#4F46E5" />
          <stop offset="1" stopColor="#06B6D4" />
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" r="14" stroke="url(#cs-logo)" strokeWidth="2" />
      <path
        d="M16 5 27 16 16 27 5 16 16 5Z"
        stroke="url(#cs-logo)"
        strokeWidth="1.3"
        fill="url(#cs-logo)"
        fillOpacity="0.15"
      />
      <circle cx="16" cy="16" r="2.4" fill="url(#cs-logo)" />
    </svg>
  );
}

export default function Navbar() {
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleString("vi-VN", {
          timeZone: "Asia/Ho_Chi_Minh",
          hour: "2-digit",
          minute: "2-digit",
          day: "2-digit",
          month: "2-digit",
        })
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const tabCls = ({ isActive }) =>
    "px-3 py-1.5 rounded-md text-[13px] font-medium transition " +
    (isActive
      ? "text-[#4F46E5]"
      : "text-[#475569] hover:text-[#1e2329]");

  return (
    <nav className="sticky top-0 z-30 bg-white border-b border-[#eaecef]">
      <div className="max-w-[1400px] mx-auto flex items-center justify-between px-6 h-14">
        <div className="flex items-center gap-8">
          <Link
            to="/"
            className="flex items-center gap-2 select-none hover:opacity-80 transition"
            aria-label="Cryptsen — Trang chủ"
          >
            <Logo />
            <span className="text-[16px] font-bold tracking-tight text-[#1e2329]">
              Cryptsen
            </span>
          </Link>
          <ul className="hidden lg:flex items-center gap-1">
            {TABS.map((t) => (
              <li key={t.to}>
                <NavLink to={t.to} end={t.exact} className={tabCls}>
                  {t.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>

        <span className="hidden md:inline text-[12px] text-[#707a8a] tabular-nums">
          {clock}
        </span>
      </div>
    </nav>
  );
}
