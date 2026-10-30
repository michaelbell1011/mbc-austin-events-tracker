# mbc-austin-events-tracker

This monitors the MBC Austin events webpage (https://mbcaustin.org/events) for new event listings and revisions to existing events. When it finds an update, it sends an email with this message:

> new updates found on the MBC events page https://mbcaustin.org/events

The monitor reads the events RSS feed, compares event IDs, dates, titles, and descriptions with the last saved snapshot, and stores its state in `state/events.json`. The first run creates a baseline and does not send an email.

## GitHub Actions setup

The workflow runs daily and can also be started manually from the Actions tab. Scheduled workflow times use UTC and can be delayed by GitHub.

Add these repository Actions secrets under **Settings > Secrets and variables > Actions**:

- `SMTP_HOST`: your email provider's SMTP server
- `SMTP_PORT`: usually `587`
- `SMTP_USERNAME`: SMTP account username
- `SMTP_PASSWORD`: SMTP password or app password
- `MAIL_FROM`: sender email address
- `MAIL_TO`: notification recipient email address

The workflow needs `contents: write` permission to commit the updated event snapshot. On the first scheduled or manually triggered run, it saves the baseline; subsequent new or revised event records trigger the email.

## Local checks

Run the test suite with:

```sh
python3 -m unittest discover -s tests
```

To run the monitor locally, set the SMTP environment variables above and run `python3 monitor.py`. It will create `state/events.json` on its first run.