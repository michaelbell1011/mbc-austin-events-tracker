# mbc-austin-events-tracker

This monitors the MBC Austin events webpage (https://mbcaustin.org/events) for new event listings and revisions to existing events. When it finds an update, it posts to one ongoing GitHub Discussion titled **MBC Events Updates** with this message:

> new updates found on the MBC events page https://mbcaustin.org/events

The monitor reads the events RSS feed, compares event IDs, dates, titles, and descriptions with the last saved snapshot, and stores its state in `state/events.json`. The first run creates a baseline and does not send an email.

## GitHub Actions setup

The workflow runs daily and can also be started manually from the Actions tab. Scheduled workflow times use UTC and can be delayed by GitHub.

Enable Discussions for the repository and make sure it has a category named `General` (or configure a different category name). Add these repository Actions variables under **Settings > Secrets and variables > Actions**:

- `NOTIFY_GITHUB_USERNAME`: your GitHub username; each Discussion post mentions this account to generate a notification
- `DISCUSSION_CATEGORY_NAME`: optional; defaults to `General`

The workflow uses its `GITHUB_TOKEN` with `contents: write` to commit the event snapshot and Discussion ID, and `discussions: write` to post updates. On the first scheduled or manually triggered run, it saves the event baseline without creating a discussion. The first subsequent update creates the discussion; later updates are added as comments to that same discussion.

## Local checks

Run the test suite with:

```sh
python3 -m unittest discover -s tests
```

To run the monitor locally, set `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and `NOTIFY_GITHUB_USERNAME`, then run `python3 monitor.py`. It will create `state/events.json` on its first run.