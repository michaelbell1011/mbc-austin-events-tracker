import argparse
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET


EVENTS_URL = "https://mbcaustin.org/events"
FEED_URL = f"{EVENTS_URL}/RSS"
NOTIFICATION = f"new updates found on the MBC events page {EVENTS_URL}"
DISCUSSION_TITLE = "MBC Events Updates"
STATE_PATH = Path("state/events.json")
DISCUSSION_STATE_PATH = Path("state/discussion.json")
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
LOGGER = logging.getLogger(__name__)


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
    added, updated = classify_changes(previous, current)
    return bool(added or updated)


def classify_changes(previous, current):
    added = []
    updated = []
    for event_id, record in current.items():
        if event_id not in previous:
            added.append(record["title"])
        elif previous[event_id] != record:
            updated.append(record["title"])
    return added, updated


def describe_changes(added, updated):
    sections = []
    if added:
        sections.append("New events added:\n" + "\n".join(f"- {title}" for title in added))
    if updated:
        sections.append(
            "Existing events updated:\n" + "\n".join(f"- {title}" for title in updated)
        )
    return f"{NOTIFICATION}\n\n" + "\n\n".join(sections)


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


def github_graphql(token, query, variables):
    request = urllib.request.Request(
        GITHUB_GRAPHQL_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "mbc-austin-events-tracker/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL request failed: {result['errors']}")
    return result["data"]


def load_discussion_id(state_path):
    if not state_path.exists():
        return None
    with state_path.open(encoding="utf-8") as state_file:
        state = json.load(state_file)
    discussion_id = state.get("id") if isinstance(state, dict) else None
    if not discussion_id:
        raise ValueError("Saved discussion state must contain an id")
    return discussion_id


def save_discussion_id(state_path, discussion_id):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as state_file:
        json.dump({"id": discussion_id}, state_file, indent=2)
        state_file.write("\n")
    temporary_path.replace(state_path)


def post_discussion_update(
    token, repository, username, category_name, state_path, notification=NOTIFICATION
):
    discussion_id = load_discussion_id(state_path)
    if discussion_id is None:
        owner, name = repository.split("/", 1)
        repository_query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            id
            discussionCategories(first: 100) { nodes { id name } }
            discussions(first: 100) { nodes { id title } }
          }
        }
        """
        data = github_graphql(token, repository_query, {"owner": owner, "name": name})
        repository_data = data.get("repository")
        if repository_data is None:
            raise RuntimeError(f"Could not access GitHub repository {repository}")

        discussion = next(
            (
                item
                for item in repository_data["discussions"]["nodes"]
                if item["title"] == DISCUSSION_TITLE
            ),
            None,
        )
        if discussion is not None:
            discussion_id = discussion["id"]
        else:
            category = next(
                (
                    item
                    for item in repository_data["discussionCategories"]["nodes"]
                    if item["name"].lower() == category_name.lower()
                ),
                None,
            )
            if category is None:
                raise RuntimeError(
                    f"Discussion category '{category_name}' was not found in {repository}"
                )
            create_mutation = """
            mutation($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
              createDiscussion(input: {
                repositoryId: $repositoryId,
                categoryId: $categoryId,
                title: $title,
                body: $body
              }) { discussion { id } }
            }
            """
            data = github_graphql(
                token,
                create_mutation,
                {
                    "repositoryId": repository_data["id"],
                    "categoryId": category["id"],
                    "title": DISCUSSION_TITLE,
                    "body": f"@{username}\n\n{notification}",
                },
            )
            discussion_id = data["createDiscussion"]["discussion"]["id"]
            save_discussion_id(state_path, discussion_id)
            return

    comment_mutation = """
    mutation($discussionId: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
        comment { id }
      }
    }
    """
    github_graphql(
        token,
        comment_mutation,
        {
            "discussionId": discussion_id,
            "body": f"@{username}\n\n{notification}",
        },
    )
    save_discussion_id(state_path, discussion_id)


def send_notification(discussion_state_path, notification=NOTIFICATION):
    required = ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "NOTIFY_GITHUB_USERNAME")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required GitHub settings: {', '.join(missing)}")

    post_discussion_update(
        token=os.environ["GITHUB_TOKEN"],
        repository=os.environ["GITHUB_REPOSITORY"],
        username=os.environ["NOTIFY_GITHUB_USERNAME"].lstrip("@"),
        category_name=os.environ.get("DISCUSSION_CATEGORY_NAME") or "General",
        state_path=discussion_state_path,
        notification=notification,
    )


def run(state_path, discussion_state_path=DISCUSSION_STATE_PATH):
    LOGGER.info("Starting MBC events check")
    current = fetch_events()
    previous = load_state(state_path)
    LOGGER.info("Fetched %d events", len(current))

    if previous is None:
        save_state(state_path, current)
        LOGGER.info("Saved initial baseline with %d events; no Discussion posted", len(current))
        return

    added, updated = classify_changes(previous, current)
    if added or updated:
        notification = describe_changes(added, updated)
        LOGGER.info("Event updates detected; posting Discussion update")
        send_notification(discussion_state_path, notification)
        LOGGER.info("Discussion update posted: %s", NOTIFICATION)
    else:
        LOGGER.info("No event updates detected")

    save_state(state_path, current)
    LOGGER.info("Saved event state to %s", state_path)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Monitor MBC Austin event updates")
    parser.add_argument("--state-file", type=Path, default=STATE_PATH)
    parser.add_argument("--discussion-state-file", type=Path, default=DISCUSSION_STATE_PATH)
    args = parser.parse_args()
    try:
        run(args.state_file, args.discussion_state_file)
    except Exception:
        LOGGER.exception("MBC events check failed")
        raise


if __name__ == "__main__":
    main()