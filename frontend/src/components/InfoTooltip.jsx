// frontend/src/components/InfoTooltip.jsx
// Tooltip CSS-only theo phong cách Binance: đen, bo góc nhẹ, mũi tên nhỏ.
// KHÔNG phụ thuộc JS ngoài → không re-render khi WebSocket giá cập nhật.
//
// Props:
//  - text: nội dung tooltip (string)
//  - children: phần tử trigger (thường là label hoặc icon ℹ)
//  - placement: "top" | "right" (mặc định "top")

export default function InfoTooltip({ text, children, placement = "top" }) {
  const posCls =
    placement === "right"
      ? "left-full top-1/2 -translate-y-1/2 ml-2"
      : "bottom-full left-1/2 -translate-x-1/2 mb-2";
  const arrowCls =
    placement === "right"
      ? "absolute top-1/2 -translate-y-1/2 -left-1 w-2 h-2 bg-[#1e2329] rotate-45"
      : "absolute left-1/2 -translate-x-1/2 -bottom-1 w-2 h-2 bg-[#1e2329] rotate-45";
  return (
    <span className="relative inline-flex items-center gap-1 group cursor-help">
      {children}
      <span
        role="tooltip"
        className={
          "pointer-events-none absolute z-20 whitespace-nowrap " +
          "rounded-md bg-[#1e2329] text-white text-[11px] font-medium " +
          "px-2.5 py-1.5 shadow-md opacity-0 group-hover:opacity-100 " +
          "transition-opacity duration-150 " +
          posCls
        }
      >
        {text}
        <span className={arrowCls} />
      </span>
    </span>
  );
}
