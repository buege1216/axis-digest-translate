import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path("articles.db")
OUTPUT_PATH = Path("docs/data.json")

def export():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        data = {"articles": [], "stats": {}, "updated_at": ""}
        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT id, url, title, published, category, summary, commentary,
                   translation, sent, fetched_at
            FROM articles
            ORDER BY published DESC
        """).fetchall()

        total_db   = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        no_summary = conn.execute("SELECT COUNT(*) FROM articles WHERE summary IS NULL").fetchone()[0]
        pending    = conn.execute("SELECT COUNT(*) FROM articles WHERE summary IS NOT NULL AND sent=0").fetchone()[0]
        sent       = conn.execute("SELECT COUNT(*) FROM articles WHERE sent=1").fetchone()[0]

    articles = []
    for r in rows:
        articles.append({
            "id":          r["id"],
            "url":         r["url"],
            "title":       r["title"],
            "published":   r["published"],
            "category":    r["category"] or "",
            "summary":     r["summary"] or "",
            "commentary":  r["commentary"] or "",
            "translation": r["translation"] or "",
            "sent":        r["sent"],
        })

    data = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "stats": {
            "total_site":  13779,
            "total_db":    total_db,
            "no_summary":  no_summary,
            "pending":     pending,
            "sent":        sent,
        },
        "articles": articles,
    }

    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print("匯出完成：" + str(len(articles)) + " 篇文章")

if __name__ == "__main__":
    export()
