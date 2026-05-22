import requests
import sqlite3
import hashlib
import time
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")
PROGRESS_FILE = Path("sitemap_progress.txt")
REQUEST_DELAY = 3.0

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AxisDigestBot/1.0)"}
JINA_PREFIX = "https://r.jina.ai/"
SITEMAP_INDEX_URL = "https://www.axismag.jp/sitemap.xml"
MAX_ARTICLES_PER_RUN = 50


class AxisScraper:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT UNIQUE NOT NULL,
                    url_hash    TEXT UNIQUE NOT NULL,
                    title       TEXT,
                    author      TEXT,
                    published   TEXT,
                    category    TEXT,
                    content     TEXT,
                    summary     TEXT,
                    commentary  TEXT,
                    translation TEXT,
                    zh_title    TEXT,
                    fetched_at  TEXT NOT NULL,
                    sent        INTEGER DEFAULT 0
                )
            """)
            existing = [row[1] for row in conn.execute("PRAGMA table_info(articles)")]
            for col, definition in [
                ("category",    "TEXT"),
                ("translation", "TEXT"),
                ("zh_title",    "TEXT"),
            ]:
                if col not in existing:
                    conn.execute("ALTER TABLE articles ADD COLUMN " + col + " " + definition)
                    conn.commit()
                    logger.info("已自動新增欄位：" + col)
            conn.commit()

    def _url_hash(self, url):
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _is_seen(self, url):
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT 1 FROM articles WHERE url_hash = ?",
                (self._url_hash(url),)
            ).fetchone()
        return row is not None

    def _get_progress(self):
        if PROGRESS_FILE.exists():
            parts = PROGRESS_FILE.read_text().strip().split(",")
            return int(parts[0]), int(parts[1])
        return 0, 0

    def _save_progress(self, sitemap_idx, url_idx):
        PROGRESS_FILE.write_text(str(sitemap_idx) + "," + str(url_idx))

    def _save_article(self, article):
        with sqlite3.connect(DB_PATH) as conn:
            try:
                conn.execute("""
                    INSERT INTO articles
                        (url, url_hash, title, author, published, category, content, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    article["url"],
                    self._url_hash(article["url"]),
                    article.get("title", ""),
                    article.get("author", ""),
                    article.get("published", ""),
                    article.get("category", ""),
                    article.get("content", ""),
                    datetime.utcnow().isoformat(),
                ))
                conn.commit()
                logger.info("已儲存：" + article["title"][:50])
            except sqlite3.IntegrityError:
                pass

    def _fetch_all_sitemap_urls(self):
        try:
            resp = requests.get(SITEMAP_INDEX_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("主 Sitemap 讀取失敗：" + str(e))
            return []

        urls = []
        try:
            root = ET.fromstring(resp.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//sm:loc", ns):
                url = loc.text.strip()
                if "post_list-sitemap" in url:
                    urls.append(url)
        except Exception as e:
            logger.error("主 Sitemap 解析失敗：" + str(e))

        urls.sort(
            key=lambda u: int(re.search(r"sitemap(\d+)", u).group(1))
            if re.search(r"sitemap(\d+)", u) else 0,
            reverse=True
        )
        logger.info("找到 " + str(len(urls)) + " 個 sitemap")
        return urls

    def _fetch_sitemap_urls(self, sitemap_url):
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.error("Sitemap 讀取失敗：" + str(e))
            return []

        urls = []
        try:
            root = ET.fromstring(resp.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for url_el in root.findall(".//sm:url", ns):
                loc = url_el.find("sm:loc", ns)
                lastmod = url_el.find("sm:lastmod", ns)
                if loc is None:
                    continue
                url = loc.text.strip()
                if not re.search(r"/posts/\d{4}/\d{2}/\d+\.html", url):
                    continue
                published = ""
                if lastmod is not None and lastmod.text:
                    raw = lastmod.text.strip()
                    try:
                        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                        tw_tz = timezone(timedelta(hours=8))
                        dt_tw = dt.astimezone(tw_tz)
                        published = dt_tw.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        published = raw[:10]
                urls.append((url, published))
        except Exception as e:
            logger.error("Sitemap 解析失敗：" + str(e))

        # 按 published 從新到舊排序
        urls.sort(key=lambda x: x[1], reverse=True)
        return urls

    def _fetch_article(self, url, published=""):
        jina_url = JINA_PREFIX + url
        try:
            resp = requests.get(jina_url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                logger.info("  跳過（狀態碼 " + str(resp.status_code) + "）")
                return None
        except Exception as e:
            logger.debug("抓取失敗：" + str(e))
            return None

        text = resp.text.strip()
        if len(text) < 100:
            logger.info("  內容太短跳過")
            return None

        lines = text.split("\n")
        title = ""
        content_lines = []
        article_started = False
        date_pattern = re.compile(r"\d{4}\.\d{2}\.\d{2}")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("# ") and not title:
                candidate = stripped.lstrip("#").strip()
                if "AXIS WEB" not in candidate and "axismag" not in candidate.lower():
                    title = candidate
                continue

            if not article_started and date_pattern.search(stripped):
                article_started = True
                continue

            if article_started:
                if any(skip in stripped for skip in [
                    "FOLLOW US", "Facebook", "Twitter",
                    "Instagram", "YouTube", "LINE", "Spotify",
                    "プライバシー", "お問い合わせ", "運営会社",
                    "広告掲載", "採用情報", "関連する記事",
                    "### [NEWS", "#### [", "AXIS WEB"
                ]):
                    continue
                if stripped.startswith("*   [") or stripped.startswith("- ["):
                    continue
                content_lines.append(stripped)

        if not title or len(title) < 5:
            logger.info("  無標題跳過")
            return None

        content = "\n\n".join(content_lines)
        if len(content) < 50:
            logger.info("  內文太短跳過：" + title[:30])
            return None

        # 從網址取年月當發布日期
        if not published:
            m = re.search(r"/posts/(\d{4})/(\d{2})/", url)
            published = (m.group(1) + "-" + m.group(2)) if m else ""

        # 從「類型 ｜ 分類」格式抓分類
        # 日文分類名稱對照
        JP_CAT_MAP = {
            "プロダクト":   "product",
            "ビジネス":     "business",
            "テクノロジー": "technology",
            "アート":       "art",
            "グラフィック": "graphic",
            "工芸":         "craft",
            "カルチャー":   "culture",
            "建築":         "architecture",
            "インテリア":   "interior",
            "ファッション": "fashion",
            "ソーシャル":   "social",
            "フード・食":   "food",
            "サイエンス":   "science",
            "サウンド":     "sound",
        }

        category = ""
        # 找「NEWS ｜ プロダクト」或「REPORT ｜ 建築 / 展覧会」這種格式
        cat_line_match = re.search(
            r"(?:NEWS|REPORT|INTERVIEW|FEATURE|SERIAL|INSIGHT|TALK|INFO)[^\n]*｜[^\n]*",
            text
        )
        if cat_line_match:
            cat_line = cat_line_match.group(0)
            for jp, en in JP_CAT_MAP.items():
                if jp in cat_line:
                    category = en
                    break

        # 備用：從 URL 抓 category
        if not category:
            cat_url_match = re.search(r"axismag\.jp/(?:posts/)?category/([a-z\-]+)", text)
            if cat_url_match:
                # 只取第一個非側邊欄的分類（排除建築排第一的問題）
                # 改用找到日期附近的 category 連結
                pass

        logger.info("  ✓ " + title[:45] + "（" + str(len(content)) + " 字）")
        return {
            "url":       url,
            "title":     title,
            "author":    "",
            "published": published,
            "category":  category,
            "content":   content[:4000],
        }

    def run(self):
        sitemap_idx, url_idx = self._get_progress()
        logger.info("從 sitemap 進度：第 " + str(sitemap_idx) + " 個，第 " + str(url_idx) + " 筆")

        all_sitemaps = self._fetch_all_sitemap_urls()
        if not all_sitemaps:
            logger.error("無法取得 sitemap 清單")
            return []

        new_articles = []

        while len(new_articles) < MAX_ARTICLES_PER_RUN:
            if sitemap_idx >= len(all_sitemaps):
                logger.info("所有 sitemap 已讀完！")
                break

            sitemap_url = all_sitemaps[sitemap_idx]
            logger.info("讀取：" + sitemap_url)
            urls = self._fetch_sitemap_urls(sitemap_url)

            if not urls:
                sitemap_idx += 1
                url_idx = 0
                self._save_progress(sitemap_idx, url_idx)
                continue

            logger.info("  共 " + str(len(urls)) + " 篇，從第 " + str(url_idx) + " 筆繼續")

            while url_idx < len(urls):
                if len(new_articles) >= MAX_ARTICLES_PER_RUN:
                    break

                url, published = urls[url_idx]
                url_idx += 1

                if self._is_seen(url):
                    continue

                time.sleep(REQUEST_DELAY)
                article = self._fetch_article(url, published)
                if article:
                    self._save_article(article)
                    new_articles.append(article)

            if url_idx >= len(urls):
                sitemap_idx += 1
                url_idx = 0

            self._save_progress(sitemap_idx, url_idx)

        self._save_progress(sitemap_idx, url_idx)
        logger.info("共新增 " + str(len(new_articles)) + " 篇文章")
        return new_articles

    def get_unsent(self, limit=1):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM articles
                WHERE sent = 0 AND summary IS NOT NULL
                ORDER BY published DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, ids):
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "UPDATE articles SET sent = 1 WHERE id = ?",
                [(i,) for i in ids]
            )
            conn.commit()

    def get_unsent_count(self):
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("""
                SELECT COUNT(*) FROM articles
                WHERE sent = 0 AND summary IS NOT NULL
            """).fetchone()
        return row[0] if row else 0
