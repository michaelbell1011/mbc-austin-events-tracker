import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from monitor import NOTIFICATION, has_updates, parse_events, post_discussion_update, run


def make_feed(title="Breakfast speaker", date="Wed, 04 Nov 2026 13:00:00 GMT", description="<p>Join us.</p>"):
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>{title}</title>
      <pubDate>{date}</pubDate>
      <description><![CDATA[{description}]]></description>
      <link>https://mbcaustin.org/event-123</link>
      <guid>https://mbcaustin.org/event-123</guid>
    </item></channel></rss>""".encode()


class MonitorTests(unittest.TestCase):
    def test_run_logs_initial_baseline_result(self):
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "events.json"
            events = parse_events(make_feed())
            with patch("monitor.fetch_events", return_value=events), patch(
                "monitor.load_state", return_value=None
            ), patch("monitor.save_state") as save_state, self.assertLogs(
                "monitor", level="INFO"
            ) as logs:
                run(state_path)

            save_state.assert_called_once_with(state_path, events)
            self.assertIn("Saved initial baseline", " ".join(logs.output))

    def test_run_logs_unchanged_result(self):
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "events.json"
            events = parse_events(make_feed())
            with patch("monitor.fetch_events", return_value=events), patch(
                "monitor.load_state", return_value=events
            ), patch("monitor.save_state") as save_state, patch(
                "monitor.send_notification"
            ) as send_notification, self.assertLogs("monitor", level="INFO") as logs:
                run(state_path)

            save_state.assert_called_once_with(state_path, events)
            send_notification.assert_not_called()
            self.assertIn("No event updates detected", " ".join(logs.output))

    def test_run_logs_successful_update_result(self):
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "events.json"
            previous = {}
            events = parse_events(make_feed())
            with patch("monitor.fetch_events", return_value=events), patch(
                "monitor.load_state", return_value=previous
            ), patch("monitor.save_state") as save_state, patch(
                "monitor.send_notification"
            ) as send_notification, self.assertLogs("monitor", level="INFO") as logs:
                run(state_path)

            save_state.assert_called_once_with(state_path, events)
            send_notification.assert_called_once()
            self.assertIn("Discussion update posted", " ".join(logs.output))

    def test_parse_feed_uses_stable_event_id_and_normalizes_description(self):
        events = parse_events(make_feed(description="<p>Join <strong>us</strong>.</p>"))

        self.assertEqual(
            events,
            {
                "https://mbcaustin.org/event-123": {
                    "title": "Breakfast speaker",
                    "date": "Wed, 04 Nov 2026 13:00:00 GMT",
                    "description": "Join us.",
                }
            },
        )

    def test_detects_new_event(self):
        current = parse_events(make_feed())

        self.assertTrue(has_updates({}, current))

    def test_detects_event_revision(self):
        previous = parse_events(make_feed())
        revised = parse_events(make_feed(title="Updated speaker"))

        self.assertTrue(has_updates(previous, revised))

    def test_ignores_unchanged_events(self):
        events = parse_events(make_feed())

        self.assertFalse(has_updates(events, events))

    def test_creates_discussion_for_first_update(self):
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "discussion.json"
            with patch("monitor.github_graphql") as graphql:
                graphql.side_effect = [
                    {
                        "repository": {
                            "id": "repository-id",
                            "discussionCategories": {
                                "nodes": [{"id": "category-id", "name": "General"}]
                            },
                            "discussions": {"nodes": []},
                        }
                    },
                    {"createDiscussion": {"discussion": {"id": "discussion-id"}}},
                ]

                post_discussion_update(
                    "token", "owner/repo", "maintainer", "General", state_path
                )

            self.assertEqual(graphql.call_count, 2)
            create_variables = graphql.call_args_list[1].args[2]
            self.assertEqual(create_variables["title"], "MBC Events Updates")
            self.assertEqual(
                create_variables["body"], f"@maintainer\n\n{NOTIFICATION}"
            )
            self.assertEqual(state_path.read_text(), '{\n  "id": "discussion-id"\n}\n')

    def test_posts_followup_as_comment_on_same_discussion(self):
        with TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "discussion.json"
            state_path.write_text('{"id": "discussion-id"}')
            with patch("monitor.github_graphql") as graphql:
                post_discussion_update(
                    "token", "owner/repo", "maintainer", "General", state_path
                )

            graphql.assert_called_once()
            self.assertIn("addDiscussionComment", graphql.call_args.args[1])
            self.assertEqual(
                graphql.call_args.args[2],
                {
                    "discussionId": "discussion-id",
                    "body": f"@maintainer\n\n{NOTIFICATION}",
                },
            )


if __name__ == "__main__":
    unittest.main()