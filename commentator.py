import sqlite3
import logging
import time
import os
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("articles.db")

SYSTEM_PROMPT = (
    "你是「軸心評論」首席評論員，融合藝術史學者、策展人與文化批評家三重身份，將原文翻譯成繁體中文，寫給適合台灣本土商業背景的30歲創業家。\n"
    "【重要】所有輸出必須使用繁體中文（Traditional Chinese），絕對不能使用簡體中文、日文或英文。\n"
    "繁體中文用字範例：的、與、為、這、來、時、說、國、會、學、體、當、個、從、對。\n"
    "口吻：自信但不傲慢，學術但不艱澀。"
)

PROMPT_TEMPLATE = (
    "請將以下日文文章翻譯成繁體中文。\n"
    "輸出格式如下，直接輸出內容不要加任何說明：\n\n"
    "===標題===\n"
    "（翻譯後的標題）\n\n"
    "===內文===\n"
    "（翻譯後的內文，保留段落結構，保留圖片語法 ![說明](網址) 並翻譯說明文字）\n\n"
    "以下是文章內容：\n"
    "標題：{title}\n"
    "內容：{content}"
)


class Commentator:
    def __init__(self):
        self.provider = os.environ.get("AI_PROVIDER", "gemini").lower()
        self._last_error_is_quota = False
        self._init_client()

    def _init_client(self):
        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            logger.info("使用 OpenAI，模型：" + self.model)

        elif self.provider == "minimax":
            from openai import OpenAI
            self.client = OpenAI(
                api_key=os.environ.get("MINIMAX_API_KEY", ""),
                base_url="https://api.minimax.chat/v1",
            )
            self.model = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
            logger.info("使用 MiniMax，模型：" + self.model)

        else:
            from google import genai
            self.genai_client = genai.Client(
                api_key=os.environ.get("GEMINI_API_KEY", "")
            )
            self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            logger.info("使用 Gemini，模型：" + self.model)

    def _ask(self, prompt, max_tokens=5000):
        self._last_error_is_quota = False
        for attempt in range(3):
            try:
                if self.provider == "gemini":
                    from google.genai import types
                    resp = self.genai_client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            max_output_tokens=max_tokens,
                        )
                    )
                    return resp.text.strip()
                else:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": prompt},
                        ],
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content.strip()

            except Exception as e:
                msg = str(e)
                logger.warning("第 " + str(attempt + 1) + " 次失敗：" + msg)
                if "503" in msg or "UNAVAILABLE" in msg:
                    time.sleep(90)
                elif "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate_limit" in msg.lower():
                    self._last_error_is_quota = True
                    time.sleep(90)
                else:
                    time.sleep(60)
        return ""

    def _clean(self, text):
        """清除 AI 自言自語的說明文字"""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if any(skip in stripped for skip in [
                "從文章挑選", "翻譯成繁體中文", "以下是翻譯",
                "以下是摘要", "以下是評論", "我需要", "我注意到",
                "現在我", "讓我來", "接下來我將", "根據文章",
                "根據以上", "以下為", "犀利開篇", "引用案例",
                "點出盲點", "金句結尾", "直接輸出",
                "要點一", "要點二", "要點三",
                "核心主題：（", "延伸思考：（",
                "The user wants", "Let me", "I need to",
                "I will", "I'll", "I should", "Here is",
                "Here's", "Let's", "This is", "Please note",
            ]):

                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def process_article(self, article):
        content = article.get("content", "")[:3000]
        title = article.get("title", "")
        prompt = PROMPT_TEMPLATE.format(title=title, content=content)

        result = self._ask(prompt, max_tokens=2500)
        if not result:
            return "", "", ""

        # 解析標題和內文
        title_match   = re.search(r"===標題===(.*?)===內文===", result, re.DOTALL)
        content_match = re.search(r"===內文===(.*?)$", result, re.DOTALL)

        zh_title   = self._clean(title_match.group(1).strip())   if title_match   else ""
        zh_content = self._clean(content_match.group(1).strip()) if content_match else ""

        # 把翻譯標題存進 summary，翻譯內文存進 translation
        summary = zh_title if zh_title else "翻譯完成"
        return summary, "", zh_content


    def process_all(self, batch=50):
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, title, content FROM articles
                WHERE summary IS NULL AND content != ''
                ORDER BY published DESC LIMIT ?
            """, (batch,)).fetchall()

        articles = [dict(r) for r in rows]
        if not articles:
            logger.info("沒有待處理文章")
            return 0

        done = 0
        for art in articles:
            logger.info("處理：" + art["title"][:50])
            summary, commentary, translation = self.process_article(art)

            def _is_valid(text, min_len=50, must_contain=None):
                if not text or len(text) < min_len:
                    return False
                if must_contain:
                    return any(k in text for k in must_contain)
                return True

            summary_ok    = len(translation) > 50
            commentary_ok = True

            if summary_ok and commentary_ok:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE articles SET summary=?, commentary=?, translation=? WHERE id=?",
                        (summary, commentary, translation, art["id"])
                    )
                    conn.commit()
                done += 1
                logger.info("  ✓ 完成（摘要 " + str(len(summary)) + " 字，評論 " + str(len(commentary)) + " 字，翻譯 " + str(len(translation)) + " 字）")
            elif self._last_error_is_quota:
                logger.warning("  配額已用盡，今天剩下的留給明天處理")
                break
            else:
                logger.warning("  ✗ 品質不合格（摘要:" + str(len(summary)) + "字，評論:" + str(len(commentary)) + "字），標記重試")
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE articles SET summary=NULL, commentary=NULL, translation=NULL WHERE id=?",
                        (art["id"],)
                    )
                    conn.commit()

            time.sleep(2)

        logger.info("完成 " + str(done) + " 篇")
        return done
