# Kasumi report service

A small Cloudflare Worker that receives diagnostic reports from Kasumi. A report
is only sent when a player chooses **Settings > System > Send diagnostic report**
and confirms; it is kept for 30 days and read back with the code Kasumi shows.

What a report contains: the diagnostic log of the current and the previous run
(IP addresses shortened to their first two numbers; no login tokens or
passwords, which the log never contains), `settings.json`, and the newest Luma
crash dump from the last 3 days, if there is one.

## Deploy (browser only, free plan)

1. Create a free account at <https://dash.cloudflare.com>.
2. **Storage & Databases > KV > Create namespace**, name it `kasumi-reports`.
3. **Workers & Pages > Create > Create Worker**, name it `kasumi-reports`,
   **Deploy**, then **Edit code**: replace everything with `worker.js` from
   this folder and **Deploy** again.
4. In the Worker: **Settings > Bindings > Add > KV namespace**: variable name
   `REPORTS`, namespace `kasumi-reports`.
5. **Settings > Variables and Secrets > Add**, type **Secret**:
   - `ADMIN_KEY`: a long random password (this is what lets you read reports).
   - `DISCORD_WEBHOOK` (optional): a Discord channel webhook URL, to get a
     message for every new report.
6. Your Worker's address is shown at the top, like
   `https://kasumi-reports.<your-name>.workers.dev`. Kasumi's
   `REPORT_URL` (in `include/app_paths.h`) points there.

## Dashboard

Open `dashboard.html` from this folder in a browser (double-click it), paste
`ADMIN_KEY`, and press **Load**: headline numbers, charts, a breakdown by
version / connection / server / bitrate / game, recent sessions, and the
reports with their logs and crash dumps. The key is sent only to the report
service (as a header, not in the address), and is remembered on that PC only
if you tick the box.

## Reading reports

- Performance page (averages by version, connection type, bitrate and server,
  plus recent sessions): `.../stats?key=ADMIN_KEY` (add `&days=7` or `&days=90`)
- All reports: `https://kasumi-reports.<your-name>.workers.dev/reports?key=ADMIN_KEY`
- One report: `.../report/K7F2QX?key=ADMIN_KEY` (dash optional)
- Its crash dump: `.../report/K7F2QX/dump?key=ADMIN_KEY`

Keep `ADMIN_KEY` private; anyone with it can read reports.

## Limits

1.5 MB per upload (reports are gzip-compressed, usually 30-80 KB), 6 reports
per hour per sender address. The free plan allows 1,000 new reports a day.
