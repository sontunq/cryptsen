import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./ChatWidget.css";

const MAX_HISTORY = 20;

const SUGGESTED_QUESTIONS = [
  { icon: "📊", text: "Tổng quan tâm lý thị trường crypto hiện tại là như thế nào?" },
  { icon: "🌍", text: "Các chỉ số kinh tế vĩ mô (CPI, lãi suất Fed, DXY) đang tác động ra sao đến crypto?" },
  { icon: "📰", text: "Những tin tức nào có tác động lớn nhất đến thị trường trong 24 giờ qua?" },
  { icon: "🔍", text: "So sánh điểm tâm lý của các đồng coin vốn hóa lớn hiện nay" },
  { icon: "📅", text: "Có sự kiện kinh tế quan trọng nào sắp diễn ra ảnh hưởng đến thị trường không?" },
];

function TypingIndicator() {
  return (
    <div className="chat-message bot-message typing-indicator-wrapper">
      <div className="bot-avatar">
        <span>AI</span>
      </div>
      <div className="message-bubble typing-bubble">
        <span></span>
        <span></span>
        <span></span>
      </div>
    </div>
  );
}

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`chat-message ${isUser ? "user-message" : "bot-message"}`}>
      {!isUser && (
        <div className="bot-avatar">
          <span>AI</span>
        </div>
      )}
      <div className={`message-bubble ${isUser ? "user-bubble" : "ai-bubble"}`}>
        {isUser ? (
          <p>{msg.content}</p>
        ) : (
          <div className="markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {msg.content}
            </ReactMarkdown>
          </div>
        )}
        {msg.timestamp && (
          <span className="message-time">
            {new Date(msg.timestamp).toLocaleTimeString("vi-VN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        )}
      </div>
      {isUser && <div className="user-avatar">👤</div>}
    </div>
  );
}

export default function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "model",
      content:
        "Xin chào! Tôi là **Cryptsen AI** — trợ lý phân tích thị trường crypto.\n\n" +
        "Tôi được trang bị dữ liệu thời gian thực từ nhiều nguồn:\n" +
        "- 📊 **Tâm lý đa chiều**: tin tức, vĩ mô, mạng xã hội, funding rate\n" +
        "- 📰 **Tin tức**: CoinDesk, Reddit, Telegram\n" +
        "- 🌍 **Kinh tế vĩ mô**: CPI, lãi suất Fed, DXY (FRED)\n\n" +
        "Hãy đặt câu hỏi phân tích — tôi sẽ trả lời dựa trên dữ liệu thực tế.",
      timestamp: Date.now(),
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [hasNewMessage, setHasNewMessage] = useState(false);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const abortControllerRef = useRef(null);

  const autoResizeTextarea = useCallback((el) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    return () => abortControllerRef.current?.abort();
  }, []);

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
      setHasNewMessage(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen, scrollToBottom]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const getGeminiHistory = useCallback(() => {
    return messages
      .slice(-MAX_HISTORY)
      .filter((m) => m.role === "user" || m.role === "model")
      .map((m) => ({ role: m.role, content: m.content }));
  }, [messages]);

  const sendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return;

      const userMsgId = Date.now();
      const streamId = userMsgId + 1; // đảm bảo khác nhau dù gọi cùng ms
      const userMsg = { role: "user", content: trimmed, timestamp: userMsgId };
      const history = getGeminiHistory();

      setMessages((prev) => [...prev, userMsg]);
      setInputValue("");
      if (inputRef.current) { inputRef.current.style.height = "auto"; }
      setIsLoading(true);
      setIsStreaming(true);
      setMessages((prev) => [
        ...prev,
        { role: "model", content: "", timestamp: streamId, streaming: true },
      ]);

      abortControllerRef.current = new AbortController();

      try {
        const response = await fetch(`/api/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, history }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullText = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6).trim();
              if (data === "[DONE]") break;
              try {
                const parsed = JSON.parse(data);
                if (parsed.chunk) {
                  fullText += parsed.chunk;
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.timestamp === streamId
                        ? { ...m, content: fullText }
                        : m
                    )
                  );
                }
              } catch (_) {}
            }
          }
        }

        setMessages((prev) =>
          prev.map((m) =>
            m.timestamp === streamId ? { ...m, streaming: false } : m
          )
        );

        if (!isOpen) setHasNewMessage(true);
      } catch (err) {
        if (err.name === "AbortError") {
          setMessages((prev) => prev.filter((m) => m.timestamp !== streamId));
        } else {
          const errMsg = err.message || "";
          const isNetwork = errMsg.includes("fetch") || errMsg.includes("network") || errMsg.includes("Failed");
          setMessages((prev) =>
            prev.map((m) =>
              m.timestamp === streamId
                ? {
                    ...m,
                    content: isNetwork
                      ? "⚠️ **Lỗi kết nối mạng.** Không thể liên lạc với máy chủ. Vui lòng kiểm tra kết nối và thử lại."
                      : "⚠️ **Đã xảy ra lỗi.** Không thể nhận phản hồi từ AI. Vui lòng thử lại sau giây lát.",
                    streaming: false,
                  }
                : m
            )
          );
        }
      } finally {
        setIsLoading(false);
        setIsStreaming(false);
      }
    },
    [isLoading, getGeminiHistory, isOpen]
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    sendMessage(inputValue);
  };

  const handleSuggestion = (q) => {
    sendMessage(q);
  };

  const handleClearHistory = () => {
    setMessages([
      {
        role: "model",
        content:
          "Cuộc trò chuyện đã được làm mới. Tôi sẵn sàng hỗ trợ phân tích thị trường crypto với dữ liệu mới nhất.",
        timestamp: Date.now(),
      },
    ]);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputValue);
    }
  };

  const showSuggestions =
    messages.length === 1 && messages[0].role === "model";

  return (
    <>
      {/* Floating Toggle Button */}
      <button
        id="chat-widget-toggle"
        className={`chat-fab ${isOpen ? "chat-fab-open" : ""} ${hasNewMessage ? "has-notification" : ""}`}
        onClick={() => setIsOpen((v) => !v)}
        aria-label="Mở chatbot"
      >
        {isOpen ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z" />
          </svg>
        )}
        {hasNewMessage && <span className="notification-dot" />}
      </button>

      {/* Chat Panel */}
      <div className={`chat-panel ${isOpen ? "chat-panel-open" : ""} ${isMaximized ? "chat-panel-maximized" : ""}`}>
        {/* Header */}
        <div className="chat-header">
          <div className="chat-header-info">
            <div className="chat-header-avatar">
              <span>AI</span>
              <div className="online-dot" />
            </div>
            <div>
              <h3>Cryptsen AI</h3>
              <p>Phân tích thị trường · RAG · Gemini</p>
            </div>
          </div>
          <div className="chat-header-actions">
            <button
              id="chat-clear-btn"
              className="icon-btn"
              onClick={handleClearHistory}
              title="Xóa lịch sử"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6h18M19 6l-1 14H6L5 6m5 0V4h4v2" />
              </svg>
            </button>
            <button
              className="icon-btn"
              onClick={() => setIsMaximized((v) => !v)}
              title={isMaximized ? "Thu nhỏ" : "Phóng to"}
            >
              {isMaximized ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 8V5a2 2 0 012-2h3m13 8V5a2 2 0 00-2-2h-3M3 16v3a2 2 0 002 2h3m13-8v3a2 2 0 01-2 2h-3" />
                </svg>
              )}
            </button>
            <button
              className="icon-btn"
              onClick={() => setIsOpen(false)}
              title="Đóng"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="chat-messages">
          {messages.map((msg) => (
            <MessageBubble key={msg.timestamp} msg={msg} />
          ))}
          {isLoading && !isStreaming && <TypingIndicator />}

          {/* Suggestions */}
          {showSuggestions && (
            <div className="suggestions-container">
              <p className="suggestions-label">Câu hỏi phân tích gợi ý</p>
              <div className="suggestions-grid">
                {SUGGESTED_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    className="suggestion-chip"
                    onClick={() => handleSuggestion(q.text)}
                    id={`suggestion-${i}`}
                  >
                    <span className="suggestion-icon">{q.icon}</span>
                    <span className="suggestion-text">{q.text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form className="chat-input-form" onSubmit={handleSubmit}>
          <div className="chat-input-wrapper">
            <textarea
              ref={inputRef}
              id="chat-input"
              className="chat-input"
              value={inputValue}
              onChange={(e) => { setInputValue(e.target.value); autoResizeTextarea(e.target); }}
              onKeyDown={handleKeyDown}
              placeholder="Đặt câu hỏi phân tích thị trường crypto..."
              rows={1}
              disabled={isLoading}
            />
            <button
              id="chat-send-btn"
              type="submit"
              className="send-btn"
              disabled={isLoading || !inputValue.trim()}
            >
              {isLoading ? (
                <svg className="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                </svg>
              )}
            </button>
          </div>
          <p className="input-hint">Enter để gửi · Shift+Enter xuống dòng</p>
        </form>
      </div>
    </>
  );
}
