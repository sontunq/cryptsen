import asyncio
import sqlite3
import os

# Đường dẫn DB từ metadata hoặc logic dự án
DB_PATH = r"d:\Python_Project\backend\cryptsen.db"

async def cleanup():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Các từ khóa gây ra false-positive cho ASTER
    garbage_keywords = ['Mastercard', 'Faster', 'Smarter']
    
    deleted_total = 0
    
    for kw in garbage_keywords:
        # Xóa các bài gán cho ASTER mà tiêu đề chứa từ khóa rác (không phân biệt hoa thường trong LIKE)
        query = "DELETE FROM news_items WHERE coin_id = 'ASTER' AND title LIKE ?"
        cursor.execute(query, (f'%{kw}%',))
        deleted = cursor.rowcount
        deleted_total += deleted
        print(f"Deleted {deleted} records containing '{kw}' for ASTER")

    conn.commit()
    conn.close()
    print(f"Cleanup finished. Total deleted: {deleted_total}")

if __name__ == "__main__":
    asyncio.run(cleanup())
