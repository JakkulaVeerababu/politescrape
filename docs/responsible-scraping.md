# Scraping responsibly

politescrape handles the technical side of being a good guest: it reads robots.txt, paces its requests and backs off when asked. Whether you should scrape a site at all is up to you. These are the questions worth asking first. This page is general guidance, not legal advice.

## Before you start

1. **Is there an API or a data download?** Many sites publish their data on purpose. An official API is more reliable than scraping and is clearly allowed.
2. **What do the terms of service say?** Some sites forbid automated access or commercial reuse of their content. robots.txt allowing a page does not override the terms.
3. **Is the data personal?** Names, email addresses, phone numbers and profiles are personal data. Laws such as the EU's GDPR and India's Digital Personal Data Protection Act 2023 limit what you may collect and keep. Collect only what you need, and do not build profiles of people.
4. **Is the content copyrighted?** Facts are generally free to use. Articles, photos and reviews usually belong to someone. Link to the source instead of republishing it.
5. **Is it behind a login, a paywall or a bot check?** Then the owner has said "not for automated access". politescrape will not get around these, and you should not either.

## While you scrape

- **Identify yourself.** Set `user_agent` to your project's name with a URL or email address, so a site owner can contact you instead of blocking you.
- **Go slowly.** The default of one request per second per site suits most sites. Raise `delay` for small sites. Run large crawls at night in the site's time zone.
- **Cache.** Use `cache_dir` while you develop, so you do not download the same pages again each time you change your code.
- **Fetch only what you need.** Use `max_pages`, `max_depth`, `include` and `exclude` to keep crawls focused.
- **Stop when asked.** If a site answers 429 or 503, politescrape slows down by itself. If it keeps happening, or the owner asks you to stop, stop.

## After you scrape

- Keep the source address with every record, so others can check it.
- Store data securely and delete what you no longer need.
- If you publish a dataset, say where it came from and when it was collected.
