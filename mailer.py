import smtplib
import os
import re
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def render_content(text):
    if not text:
        return ""
    def replace_img(m):
        alt = m.group(1).strip()
        url = m.group(2)
        if "wp-content/uploads" in url:
            result = '<img src="' + url + '" style="max-width:100%;height:auto;margin:12px 0;display:block;border-radius:2px;">'
            if alt and alt not in ["", "Image"] and not alt.startswith("Image "):
                result += '<p style="font-size:12px;color:#888780;font-family:Arial,sans-serif;margin:4px 0 12px;">' + alt + '</p>'
            return result
        return ""
    text = re.sub(r'!\[([^\]]*)\]\((https?://[^\)]+)\)', replace_img, text)
    text = re.sub(r'!\[.*?\]', '', text)
    text = text.replace("\n", "<br>")
    return text


def make_card(i, art):
    url         = art.get("url", "#")
    title       = art.get("title", "（無標題）")
    translation = art.get("translation", "")
    meta        = art.get("author", "") or "Axis"
    if art.get("published"):
        meta += "　·　" + art["published"]

    return (
        '<div class="card">'
        '<div class="card-header">'
        '<p class="kicker">文章 ' + f"{i:02d}" + '</p>'
        '<h2 class="card-title"><a href="' + url + '">' + title + '</a></h2>'
        '<p class="card-meta">' + meta + '</p>'
        '</div>'
        + (
            '<div class="section">'
            '<p class="label">繁體中文全文</p>'
            '<p class="body-text">' + render_content(translation) + '</p>'
            '</div>'
            if translation else
            '<div class="section"><p class="body-text" style="color:#b4b2a9">翻譯生成中...</p></div>'
        ) +
        '<div class="read-more">'
        '<a href="' + url + '">閱讀原文 →</a>'
        '</div>'
        '</div>'
    )

    return (
        '<div class="card">'
        '<div class="card-header">'
        '<p class="kicker">文章 ' + f"{i:02d}" + '</p>'
        '<h2 class="card-title"><a href="' + url + '">' + title + '</a></h2>'
        '<p class="card-meta">' + meta + '</p>'
        '</div>'
        '<div class="section">'
        '<p class="label">編輯摘要</p>'
        '<p class="body-text">' + render_content(summary) + '</p>'
        '</div>'
        '<div class="section section-alt">'
        '<span class="badge">軸心評論 · AI 評論員</span>'
        '<p class="commentary">' + render_content(commentary) + '</p>'
        '</div>'
        + translation_block +
        '<div class="read-more">'
        '<a href="' + url + '">閱讀原文 →</a>'
        '</div>'
        '</div>'
    )


def build_email(articles, vol=1):
    now      = datetime.now()
    date_str = now.strftime("%Y 年 %m 月 %d 日")
    n        = len(articles)
    cards    = "".join(make_card(i, art) for i, art in enumerate(articles, 1))

    css = """
<style>
body{margin:0;padding:0;background:#f5f4f0;font-family:Georgia,serif;color:#2c2c2a}
.wrap{max-width:640px;margin:0 auto;padding:24px 16px}
.hd{background:#1a1a18;padding:36px 32px 28px;border-radius:4px 4px 0 0}
.hd-kicker{font-family:Arial,sans-serif;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#888780;margin:0 0 10px}
.hd-title{font-size:32px;font-weight:400;color:#f1efe8;margin:0 0 8px;line-height:1.15}
.hd-sub{font-size:14px;color:#888780;margin:0;font-style:italic}
.hd-meta{margin-top:20px;padding-top:16px;border-top:1px solid #333330;font-family:Arial,sans-serif;font-size:12px;color:#5f5e5a}
.intro{background:#2c2c2a;padding:18px 32px}
.intro p{margin:0;font-size:15px;color:#b4b2a9;line-height:1.7;font-style:italic}
.intro strong{color:#f1efe8;font-style:normal}
.card{background:#fff;margin:16px 0;border-radius:2px;border-left:3px solid #1a1a18}
.card-header{padding:22px 28px 14px;border-bottom:1px solid #f1efe8}
.kicker{font-family:Arial,sans-serif;font-size:11px;letter-spacing:.15em;text-transform:uppercase;color:#b4b2a9;margin:0 0 8px}
.card-title{font-size:19px;font-weight:400;margin:0 0 8px;line-height:1.3}
.card-title a{color:#1a1a18;text-decoration:none;border-bottom:1px solid #d3d1c7}
.card-meta{font-family:Arial,sans-serif;font-size:12px;color:#888780;margin:0}
.section{padding:18px 28px;border-bottom:1px solid #f1efe8}
.section-alt{padding:18px 28px;background:#fafaf8;border-bottom:1px solid #f1efe8}
.label{font-family:Arial,sans-serif;font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:#b4b2a9;margin:0 0 10px}
.body-text{font-size:14px;line-height:1.8;color:#444441;margin:0}
.badge{display:inline-block;background:#1a1a18;color:#f1efe8;font-family:Arial,sans-serif;font-size:10px;letter-spacing:.15em;text-transform:uppercase;padding:3px 9px;border-radius:2px;margin-bottom:10px}
.commentary{font-size:14px;line-height:1.85;color:#2c2c2a;margin:0;}
.read-more{padding:14px 28px 22px}
.read-more a{font-family:Arial,sans-serif;font-size:12px;color:#1a1a18;text-decoration:none;border-bottom:1px solid #1a1a18}
.ft{background:#1a1a18;padding:24px 32px;border-radius:0 0 4px 4px}
.ft p{font-family:Arial,sans-serif;font-size:11px;color:#5f5e5a;margin:0 0 4px;line-height:1.6}
</style>
"""

    html = (
        "<!DOCTYPE html><html lang='zh-TW'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        + css +
        "</head><body>"
        "<div class='wrap'>"
        "<div class='hd'>"
        "<p class='hd-kicker'>Axis Digest · 軸心週報</p>"
        "<h1 class='hd-title'>本週藝術與設計<br>精選摘要</h1>"
        "<p class='hd-sub'>由 AI 評論員「軸心評論」精讀，為你萃取洞見</p>"
        "<div class='hd-meta'>Vol. " + str(vol) + " &nbsp;·&nbsp; " + date_str + " &nbsp;·&nbsp; 共 " + str(n) + " 篇文章</div>"
        "</div>"
        "<div class='intro'><p>本週 <strong>Axis Digest</strong> 精選了 " + str(n) + " 篇文章，由 AI 評論員為你萃取重點與洞見。</p></div>"
        + cards +
        "<div class='ft'>"
        "<p>文章來源：axismag.jp　·　AI 摘要由 MiniMax 生成，僅供參考</p>"
        "<p>© " + str(now.year) + " Axis Digest</p>"
        "</div>"
        "</div></body></html>"
    )

    subject = "🎨 軸心週報 Vol." + str(vol) + "｜" + (articles[0]["title"][:20] if articles else "") + "..."
    return subject, html


def send_email(subject, html):
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    to_email  = os.environ.get("TO_EMAIL", smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr(("軸心週報 Axis Digest", smtp_user))
    msg["To"]      = to_email
    msg.attach(MIMEText("請使用支援 HTML 的郵件客戶端查看。", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        logger.info("✅ Email 已寄出至 " + to_email)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("❌ Gmail 認證失敗")
    except Exception as e:
        logger.error("❌ 寄信失敗：" + str(e))
    return False
