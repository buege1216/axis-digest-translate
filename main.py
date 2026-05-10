import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from scraper import Scraper
from commentator import Commentator
from mailer import build_email, send_email
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VOL_FILE = Path("vol_number.txt")

def get_vol():
    return int(VOL_FILE.read_text()) if VOL_FILE.exists() else 1

def next_vol():
    VOL_FILE.write_text(str(get_vol() + 1))

def get_total_site():
    try:
        total = 0
        for i in range(1, 20):
            sm_url = "https://www.axismag.jp/post_list-sitemap" + str(i) + ".xml"
            import requests
            r = requests.get(sm_url, timeout=10)
            if r.status_code == 404:
                break
            root = ET.fromstring(r.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            total += len(root.findall(".//sm:url", ns))
        return total
    except Exception:
        return 13779

def main():
    mode = os.environ.get("RUN_MODE", "process")

    logger.info("==================================================")
    logger.info("🚀 Axis Digest 開始執行，模式：" + mode)
    logger.info("==================================================")

    scraper = Scraper()
    commentator = Commentator()

    if mode == "process":
        logger.info("📰 Step 1：抓取新文章...")
        new_articles = scraper.run()
        logger.info("   新增 " + str(len(new_articles)) + " 篇")

        logger.info("🤖 Step 2：生成 AI 摘要與評論...")
        done = commentator.process_all(batch=50)
        logger.info("   完成 " + str(done) + " 篇")

        # 統計
        import sqlite3
        with sqlite3.connect("articles.db") as conn:
            total_db   = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            no_summary = conn.execute("SELECT COUNT(*) FROM articles WHERE summary IS NULL").fetchone()[0]
            pending    = conn.execute("SELECT COUNT(*) FROM articles WHERE summary IS NOT NULL AND sent=0").fetchone()[0]
            sent       = conn.execute("SELECT COUNT(*) FROM articles WHERE sent=1").fetchone()[0]
            pending_articles = conn.execute("""
                SELECT title, published FROM articles
                WHERE summary IS NULL AND content != ''
                ORDER BY published DESC LIMIT 10
            """).fetchall()

        total_site  = get_total_site()
        not_crawled = max(total_site - total_db, 0)

        logger.info("═" * 45)
        logger.info("📊 文章進銷存")
        logger.info("  🌐 網站總數：　　　" + str(total_site) + " 篇")
        logger.info("  ─────────────────")
        logger.info("  ① 未爬取：　　　　" + str(not_crawled) + " 篇")
        logger.info("  ② 已爬取待摘要：　" + str(no_summary) + " 篇")
        logger.info("  ③ 待閱讀庫存：　　" + str(pending) + " 篇")
        logger.info("  ④ 已閱讀：　　　　" + str(sent) + " 篇")
        logger.info("  ─────────────────")
        logger.info("  資料庫合計：　　　" + str(total_db) + " 篇")
        logger.info("═" * 45)

        if pending_articles:
            logger.info("  📋 待摘要文章（最新10篇）：")
            for row in pending_articles:
                logger.info("     - " + str(row[1]) + "　" + str(row[0])[:40])

        # 每日狀態通知信
        status_subject = "⚙️ 軸心週報 今日執行報告 " + datetime.now().strftime("%m/%d")
        status_html = (
            "<div style='font-family:Arial,sans-serif;padding:24px;max-width:480px'>"
            "<h2 style='color:#1a1a18'>今日執行完成</h2>"
            "<table style='margin-top:16px;width:100%'>"
            "<tr><td>🌐 未爬取</td><td><b>" + str(not_crawled) + "</b> 篇</td></tr>"
            "<tr><td>⏳ 待摘要</td><td><b>" + str(no_summary) + "</b> 篇</td></tr>"
            "<tr><td>📥 待閱讀</td><td><b>" + str(pending) + "</b> 篇</td></tr>"
            "<tr><td>✅ 已閱讀</td><td><b>" + str(sent) + "</b> 篇</td></tr>"
            "<tr><td>📊 總文章</td><td><b>" + str(total_site) + "</b> 篇</td></tr>"
            "</table>"
            "<p style='margin-top:16px;color:#888;font-size:12px'>執行時間：" + datetime.now().strftime("%Y-%m-%d %H:%M") + " UTC</p>"
            "</div>"
        )
        send_email(status_subject, status_html)

    elif mode == "send":
        logger.info("📬 寄信模式：從庫存取文章寄出...")
        articles = scraper.get_unsent(limit=1)

        if not articles:
            logger.info("   庫存是空的，請先等系統累積更多文章")
            return

        vol = get_vol()
        subject, html = build_email(articles, vol=vol)
        success = send_email(subject, html)

        if success:
            scraper.mark_sent([a["id"] for a in articles])
            next_vol()
            logger.info("✅ 已寄出 " + str(len(articles)) + " 篇，庫存剩 " + str(scraper.get_unsent_count()) + " 篇")
        else:
            logger.error("❌ 寄信失敗")

if __name__ == "__main__":
    main()
