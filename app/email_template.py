"""Builds the HTML and plain-text bodies for the meeting summary email."""

import html
import re

from markdown import markdown

COMPANY_NAME = "Meridian Solutions Pvt. Ltd."
BRAND_COLOR = "#1b3a6b"
ACCENT_COLOR = "#2f6fb5"
TEXT_COLOR = "#2b2b2b"
MUTED_COLOR = "#6b7280"
BORDER_COLOR = "#e2e8f0"

FONT_STACK = "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# Email clients ignore most stylesheets, so every tag carries its own inline style.
TAG_STYLES = {
    "h1": f"margin:0 0 12px;font-size:20px;line-height:1.3;color:{BRAND_COLOR};font-weight:600;",
    "h2": (
        f"margin:24px 0 10px;font-size:16px;line-height:1.3;color:{BRAND_COLOR};"
        f"font-weight:600;border-bottom:2px solid {BORDER_COLOR};padding-bottom:6px;"
    ),
    "h3": f"margin:18px 0 8px;font-size:14px;line-height:1.3;color:{BRAND_COLOR};font-weight:600;",
    "p": f"margin:0 0 12px;font-size:14px;line-height:1.6;color:{TEXT_COLOR};",
    "ul": "margin:0 0 14px;padding-left:20px;",
    "ol": "margin:0 0 14px;padding-left:20px;",
    "li": f"margin:0 0 6px;font-size:14px;line-height:1.6;color:{TEXT_COLOR};",
    "table": (
        "width:100%;border-collapse:collapse;margin:0 0 16px;"
        f"font-size:13px;color:{TEXT_COLOR};border:1px solid {BORDER_COLOR};"
    ),
    "th": (
        f"background-color:#f1f5f9;color:{BRAND_COLOR};text-align:left;font-weight:600;"
        f"padding:9px 12px;border:1px solid {BORDER_COLOR};"
    ),
    "td": f"padding:9px 12px;border:1px solid {BORDER_COLOR};vertical-align:top;",
    "blockquote": (
        f"margin:0 0 14px;padding:8px 14px;border-left:3px solid {ACCENT_COLOR};"
        f"background-color:#f8fafc;color:{MUTED_COLOR};font-size:13px;"
    ),
    "code": "background-color:#f1f5f9;padding:1px 5px;border-radius:3px;font-size:13px;",
    "hr": f"border:0;border-top:1px solid {BORDER_COLOR};margin:20px 0;",
}

CODE_FENCE_PATTERN = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
LEADING_H1_PATTERN = re.compile(r"^#\s+.*?\n+")


def strip_code_fence(text: str) -> str:
    """LLMs often wrap the whole answer in a ```markdown block; unwrap it."""
    match = CODE_FENCE_PATTERN.match(text.strip())
    return match.group(1) if match else text.strip()


def _strip_leading_title(text: str) -> str:
    """The email header already shows the meeting title, so drop a duplicate H1."""
    return LEADING_H1_PATTERN.sub("", text, count=1)


def _apply_inline_styles(rendered: str) -> str:
    for tag, style in TAG_STYLES.items():
        rendered = rendered.replace(f"<{tag}>", f'<{tag} style="{style}">')
    return rendered


def markdown_to_html(summary_markdown: str) -> str:
    rendered = markdown(
        _strip_leading_title(strip_code_fence(summary_markdown)),
        extensions=["tables", "sane_lists", "nl2br"],
    )
    return _apply_inline_styles(rendered)


def build_plain_text(meeting_title: str, summary_markdown: str, generated_at: str) -> str:
    return (
        f"Meeting Summary: {meeting_title}\n"
        f"Generated on {generated_at}\n"
        f"{'-' * 60}\n\n"
        f"{_strip_leading_title(strip_code_fence(summary_markdown))}\n\n"
        f"{'-' * 60}\n"
        "This summary was generated automatically from the Microsoft Teams meeting transcript.\n"
        f"{COMPANY_NAME}\n"
    )


def build_html(meeting_title: str, summary_markdown: str, generated_at: str, recipient_count: int) -> str:
    safe_title = html.escape(meeting_title)
    safe_generated_at = html.escape(generated_at)
    body = markdown_to_html(summary_markdown)
    attendee_note = (
        f"Shared with {recipient_count} participant{'s' if recipient_count != 1 else ''}"
        if recipient_count
        else "Shared with meeting participants"
    )

    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Meeting Summary</title>
  </head>
  <body style="margin:0;padding:0;background-color:#f4f6f9;font-family:{FONT_STACK};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background-color:#f4f6f9;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:680px;background-color:#ffffff;border:1px solid {BORDER_COLOR};
                        border-radius:8px;overflow:hidden;">
            <tr>
              <td style="background-color:{BRAND_COLOR};padding:22px 28px;">
                <div style="color:#ffffff;font-size:18px;font-weight:600;line-height:1.3;">
                  Meeting Summary
                </div>
                <div style="color:#c7d7ef;font-size:13px;margin-top:4px;">
                  {COMPANY_NAME}
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px 8px;">
                <div style="font-size:17px;font-weight:600;color:{TEXT_COLOR};line-height:1.4;">
                  {safe_title}
                </div>
                <div style="font-size:12px;color:{MUTED_COLOR};margin-top:6px;">
                  Generated on {safe_generated_at} &nbsp;&middot;&nbsp; {attendee_note}
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 28px 4px;">
                <div style="height:1px;background-color:{BORDER_COLOR};"></div>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 28px 24px;font-size:14px;color:{TEXT_COLOR};line-height:1.6;">
                {body}
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 24px;">
                <div style="border-top:1px solid {BORDER_COLOR};padding-top:16px;font-size:13px;
                            color:{TEXT_COLOR};line-height:1.6;">
                  Regards,<br />
                  <strong style="color:{BRAND_COLOR};">Meeting Intelligence Agent</strong><br />
                  <span style="color:{MUTED_COLOR};">{COMPANY_NAME}</span>
                </div>
              </td>
            </tr>
            <tr>
              <td style="background-color:#f8fafc;padding:14px 28px;border-top:1px solid {BORDER_COLOR};">
                <div style="font-size:11px;color:{MUTED_COLOR};line-height:1.5;">
                  This summary was generated automatically from the Microsoft Teams meeting transcript
                  and may not capture every detail. This email and any attachments are confidential and
                  intended solely for the meeting participants.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
