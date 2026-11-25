"""Public privacy-policy and data-deletion pages required by Meta App Review."""

import html
import os

_STYLE = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:40px auto;
padding:0 20px;line-height:1.6;color:#111827}h1{font-size:28px}h2{font-size:19px;margin-top:28px}
.muted{color:#6b7280;font-size:14px}
"""


def _handle():
    raw = (os.getenv("BRAND_HANDLE") or "@tech_job_finder").strip()
    return html.escape(raw if raw.startswith("@") else "@" + raw)


def _page(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{_STYLE}</style></head><body>{body}</body></html>")


def privacy_policy():
    h = _handle()
    return _page("Privacy Policy", f"""
<h1>Privacy Policy</h1>
<p class="muted">Applies to the {h} Instagram account and its automated job-alert service (“we”).</p>

<h2>What this service does</h2>
<p>We post job openings on Instagram. When you comment on one of our posts, we may send you a single
private message (DM) on Instagram containing the application link for that job, and may reply publicly
to your comment.</p>

<h2>Information we process</h2>
<ul>
<li>Your Instagram user ID and username, the ID and text of your comment, and the post you commented on,
as provided to us by Instagram when you comment.</li>
</ul>
<p>We do not collect your password, email address, phone number, contacts or location, and we do not
read your other messages.</p>

<h2>How we use it</h2>
<ul>
<li>To send you the application link you asked for by commenting.</li>
<li>To avoid sending you the same message more than once.</li>
</ul>
<p>We do not sell, rent or share your information with third parties, and we do not use it for
advertising.</p>

<h2>Retention</h2>
<p>Records of which comments we have answered are deleted automatically after 30 days.</p>

<h2>Third parties</h2>
<p>Messages are sent through Meta's Instagram API. Application links point to employers' careers
pages and may pass through a link shortener; those sites have their own privacy policies. Always
verify a job on the employer's official careers page. We never charge any fee for jobs.</p>

<h2>Your choices and data deletion</h2>
<p>You can delete your comment at any time, and you can ask us to delete any data about you.
See <a href="/data-deletion">Data deletion instructions</a>.</p>

<h2>Contact</h2>
<p>Send a direct message to {h} on Instagram.</p>
<p class="muted">Last updated: November 2026</p>
""")


def data_deletion():
    h = _handle()
    return _page("Data Deletion Instructions", f"""
<h1>Data Deletion Instructions</h1>
<p>We keep only minimal records (your Instagram user ID and the ID of the comment we answered), and
they are deleted automatically after 30 days.</p>
<h2>To delete your data now</h2>
<ol>
<li>Send a direct message to {h} on Instagram with the text <b>DELETE MY DATA</b>.</li>
<li>We delete all records linked to your Instagram account within 7 days and confirm by DM.</li>
</ol>
<p>You can also remove this app's access at any time in Instagram:
<b>Settings → Website permissions → Apps and websites</b>.</p>
""")
