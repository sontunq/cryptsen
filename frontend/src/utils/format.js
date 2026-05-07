export const formatPrice = (v) =>
  v >= 1
    ? v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : v.toLocaleString("en-US", { maximumFractionDigits: 8 });
