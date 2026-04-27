# PythonAnywhere redirector

Tiny Flask app that 301-redirects every URL on `lszoszk.pythonanywhere.com`
to the new home at `https://lszoszk.github.io/generalcomments/`,
translating legacy search-form parameters along the way.

Keep this running for **at least 6–12 months** so search engines transfer
indexing authority to the new domain and external links refresh.

## Deploy steps

1. **Upload** `app.py` to `/home/lszoszk/mysite/app_redirector.py` on
   PythonAnywhere (use the Files panel or `git pull` if mysite is a git
   working copy).

2. **Switch the WSGI import** in `/home/lszoszk/mysite/flask_app.py`:

   ```python
   # before
   from app import app as application

   # after
   from app_redirector import app as application
   ```

3. **Reload** the web app: PA dashboard → Web → click the green Reload
   button for `lszoszk.pythonanywhere.com`.

4. **Verify** the redirect from a terminal:

   ```bash
   curl -I https://lszoszk.pythonanywhere.com/
   curl -I "https://lszoszk.pythonanywhere.com/search?search_query=privacy&treatyBodies[]=CRC"
   ```

   Both should return:
   ```
   HTTP/1.1 301 MOVED PERMANENTLY
   Location: https://lszoszk.github.io/generalcomments/...
   ```

## Rollback (if anything breaks)

Revert step 2: change the import in `flask_app.py` back to `from app import …`
and reload. The legacy app.py is still on disk and untouched.

## After the redirect is live

1. **Verify** ownership of `https://lszoszk.github.io/generalcomments/` in
   [Google Search Console](https://search.google.com/search-console). Use
   the URL-prefix property type. Verification methods include adding a
   `<meta name="google-site-verification" …>` tag — paste it into
   `docs/index.html` head and push.

2. **Submit the new sitemap**: GSC → Sitemaps →
   `https://lszoszk.github.io/generalcomments/sitemap.xml`.

3. **Change of Address** (if you also own/verify the old PA property):
   GSC → Settings → Change of Address → confirm the move from old to new.
   This is the strongest signal you can give Google about the migration.

4. **Re-submit any high-traffic URLs** for indexing via GSC → URL
   Inspection. Especially the homepage and your most-linked search pages.

The redirect itself is the load-bearing piece; everything else just speeds
up Google's recognition of the move.
