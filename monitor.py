import argparse
from email.message import EmailMessage
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import urllib.request
import xml.etree.ElementTree as ET


EVENTS_URL = "https://mbcaustin.org/events"
FEED_URL = f"{EVENTS_URL}/RSS"
NOTIFICATION = f"new updates found on the MBC events page {EVENTS_URL}"
STATE_PATH = Path("state/events.json")


class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "style"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "a" and attributes.get("href"):
            self.parts.append(f" link {attributes['href']} ")
        elif tag == "img":
            if attributes.get("alt"):
                self.parts.append(f" {attributes['alt']} ")
            source = attributes.get("src", "")
            if source and not source.lower().startswith("data:"):
                self.parts.append(f" image {source} ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def normalize_description(description):
    parser = _DescriptionParser()
    parser.feed(description or "")
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def parse_events(feed_content):
    root = ET.fromstring(feed_content)
    events = {}
    for item in root.findall("./channel/item"):
        get_text = lambda tag: (item.findtext(tag) or "").strip()
        event_id = get_text("guid") or get_text("link")
        title = get_text("title")
        if not event_id or not title:
            raise ValueError("An RSS event is missing its ID or title")
        if event_id in events:
            raise ValueError(f"Duplicate event ID in RSS feed: {event_id}")
        events[event_id] = {
            "title": title,
            "date": get_text("pubDate"),
            "description": normalize_description(get_text("description")),
        }
    return events


def fetch_events():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "mbc-austin-events-tracker/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return parse_events(response.read())


def has_updates(previous, current):
    return any(
        event_id not in previous or previous[event_id] != record
        for event_id, record in current.items()
    )


def load_state(state_path):
    if not state_path.exists():
        return None
    with state_path.open(encoding="utf-8") as state_file:
        state = json.load(state_file)
    if not isinstance(state, dict):
        raise ValueError("Saved event state must be a JSON object")
    return state


def save_state(state_path, events):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as state_file:
        json.dump(events, state_file, ensure_ascii=False, indent=2, sort_keys=True)
        state_file.write("\n")
    temporary_path.replace(state_path)


def send_notification():
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required email settings: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = "MBC events page update"
    message["From"] = os.environ["MAIL_FROM"]
    message["To"] = os.environ["MAIL_TO"]
    message.set_content(NOTIFICATION)

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        server.send_message(message)


def run(state_path):
    current = fetch_events()
    previous = load_state(state_path)

    if previous is None:
        save_state(state_path, current)
        print(f"Saved initial baseline with {len(current)} events; no email sent.")
        return

    if has_updates(previous, current):
        send_notification()
        print(NOTIFICATION)

    save_state(state_path, current)


def main():
    parser = argparse.ArgumentParser(description="Monitor MBC Austin event updates")
    parser.add_argument("--state-file", type=Path, default=STATE_PATH)
    args = parser.parse_args()
    run(args.state_file)


if __name__ == "__main__":
    main()