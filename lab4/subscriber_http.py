"""Interactive HTTP stream subscriber."""

import argparse
import json
import urllib.request
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("broker", help="HTTP broker URL")
    parser.add_argument("topic")
    args = parser.parse_args()
    url = args.broker.rstrip("/") + "/topics/" + quote(args.topic, safe="") + "/stream"
    try:
        with urllib.request.urlopen(url) as response:
            for line in response:
                if line.strip():
                    item = json.loads(line)
                    print(f"[{item['topic']}] {item['sender']}: {item['body']}", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
