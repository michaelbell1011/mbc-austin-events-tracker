import unittest

from monitor import has_updates, parse_events


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


if __name__ == "__main__":
    unittest.main()