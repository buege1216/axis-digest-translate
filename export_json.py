import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH = Path("articles.db")
DOCS_PATH = Path("docs")
DATA_PATH = DOCS_PATH / "data"

CATEGORY_MAP = {
    "product":    "產品 Product",
    "business":   "商業 Business",
    "technology": "科技 Technology",
    "art":        "藝術 Art",
    "graphic":    "圖像 Graphic",
    "craft":      "工藝 Craft",
    "culture":    "文化 Culture",
    "architecture": "建築 Architecture",
    "interior":   "室內 Interior",
    "fashion":    "時尚 Fashion",
    "social":     "社會 Social",
    "food":       "食物 Food",
    "science":    "科學 Science",
    "sound":      "聲音 Sound",
}

def export():
    DATA_PATH.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        print("資料庫不存在")
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, url, title, published, category, translation, sent
            FROM articles
            WHERE translation IS NOT NULL AND translation != ''
            ORDER BY published DESC
        """).fetchall()

    articles = [dict(r) for r in rows]
    print("共 " + str(len(articles)) + " 篇有翻譯的文章")

    # ── 建立索引（只有標題、日期、類別，不含全文）──
    index = []
    for a in articles:
        pub = a.get("published", "") or ""
        ym = pub[:7] if len(pub) >= 7 else "unknown"
        cat = a.get("category", "") or ""
        index.append({
            "id":        a["id"],
            "url":       a["url"],
            "title":     a["title"] or "",
            "published": pub,
            "ym":        ym,
            "category":  cat,
            "cat_label": CATEGORY_MAP.get(cat, cat),
        })

    (DATA_PATH / "index.json").write_text(
        json.dumps({
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "total": len(index),
            "articles": index,
        }, ensure_ascii=False),
        encoding="utf-8"
    )
    print("索引匯出完成")

    # ── 按年月分檔，包含全文 ──
    by_ym = defaultdict(list)
    article_map = {a["id"]: a for a in articles}
    for item in index:
        by_ym[item["ym"]].append(item["id"])

    for ym, ids in by_ym.items():
        month_articles = []
        for aid in ids:
            a = article_map[aid]
            month_articles.append({
                "id":          a["id"],
                "url":         a["url"],
                "title":       a["title"] or "",
                "published":   a.get("published", ""),
                "category":    a.get("category", ""),
                "cat_label":   CATEGORY_MAP.get(a.get("category", ""), a.get("category", "")),
                "translation": a.get("translation", ""),
            })
        (DATA_PATH / (ym + ".json")).write_text(
            json.dumps(month_articles, ensure_ascii=False),
            encoding="utf-8"
        )

    print("月份檔案匯出完成，共 " + str(len(by_ym)) + " 個月份")

if __name__ == "__main__":
    export()
