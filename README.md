# Bayleaf
A self-hosted web app that indexes local EPUB and PDF cookbooks, extracts recipes on a best-effort basis, and lets a user search by recipe name or ingredient and read books in a high-quality embedded reader.


## Next steps
- Add dev reload via docker-compose volume mounts
- Improve library UI and empty states
- Confirm external access setup (Cloudflare Tun)

## Recipe extraction tasks (next session)
- Verify recipe extraction is actually running during /admin/reindex (capture logs + counts)
- Add a debug report endpoint to sample extracted recipe titles for a specific book
- Fix Crumbs & Doilies extractor if it yields zero recipes (validate class names + section boundaries)
- Ensure recipe records are inserted with correct href + image href
- Add a manual "re-extract recipes for this book" action in the UI
