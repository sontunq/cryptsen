// frontend/src/pages/PlaceholderPage.jsx
import Navbar from "../components/Navbar";

/**
 * PlaceholderPage — Dùng cho các trang chưa phát triển (Trang chủ, Thị trường,
 * Tin tức, Cộng đồng). Giữ navbar chung để user vẫn điều hướng được.
 */
export default function PlaceholderPage({ title, description }) {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />
      <div className="max-w-[900px] mx-auto px-6 py-20 text-center">
        <div className="inline-flex w-14 h-14 rounded-full bg-[#eef2ff] text-[#4f46e5] items-center justify-center mb-5">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" strokeLinecap="round" />
            <circle cx="12" cy="12" r="4" />
          </svg>
        </div>
        <h1 className="text-[24px] font-bold text-[#1e2329] mb-2">
          {title}
        </h1>
        <p className="text-[14px] text-[#707a8a] leading-relaxed">
          {description || "Trang này đang được phát triển. Vui lòng quay lại sau."}
        </p>
      </div>
    </div>
  );
}
