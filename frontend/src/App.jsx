import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import SentimentPage from "./pages/SentimentPage";
import CoinDetailPage from "./pages/CoinDetailPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import ChatWidget from "./components/ChatWidget";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <PlaceholderPage
              title="Trang chủ Cryptsen"
              description="Trang chủ sẽ sớm ra mắt. Để trải nghiệm phân tích tâm lý thị trường crypto, truy cập /cryptosentiment."
            />
          }
        />
        <Route
          path="/market"
          element={
            <PlaceholderPage
              title="Thị trường"
              description="Module dữ liệu thị trường đang được phát triển."
            />
          }
        />
        <Route path="/cryptosentiment" element={<SentimentPage />} />
        <Route
          path="/news"
          element={
            <PlaceholderPage
              title="Tin Tức"
              description="Module tin tức tổng hợp đang được phát triển."
            />
          }
        />
        <Route
          path="/community"
          element={
            <PlaceholderPage
              title="Cộng đồng"
              description="Trang cộng đồng đang được phát triển."
            />
          }
        />
        <Route path="/coin/:coinId" element={<CoinDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ChatWidget />
    </BrowserRouter>
  );
}
