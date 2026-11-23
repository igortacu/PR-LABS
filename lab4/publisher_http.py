"""Interactive HTTP publisher."""

import argparse
import json
import urllib.error
import urllib.request
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("broker", help="HTTP broker URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("topic")
    parser.add_argument("name")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    url = args.broker.rstrip("/") + "/topics/" + quote(args.topic, safe="") + "/messages"
    try:
        while True:
            line = input()
            request = urllib.request.Request(url,
                data=json.dumps({"sender": args.name, "body": line}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + args.token},
                method="POST")
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    print(f"accepted id={json.load(response)['id']}")
            except urllib.error.HTTPError as error:
                print(f"error {error.code}: {error.read().decode('utf-8')}")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
