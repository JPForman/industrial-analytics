"""Print the third-party dependencies of one or more pyproject.toml files, one per line.

Used in Dockerfiles to install dependencies in their own layer, before the source is copied, so
a code change doesn't reinstall every package. Monorepo siblings (sparkplug, industrial-api) are
skipped here and installed from source with --no-deps afterwards.
"""

import re
import sys
import tomllib

LOCAL = {"sparkplug", "industrial-api"}

seen: set[str] = set()
for path in sys.argv[1:]:
    with open(path, "rb") as f:
        for dep in tomllib.load(f)["project"].get("dependencies", []):
            name = re.split(r"[\[<>=!~ ;]", dep, maxsplit=1)[0].lower()
            if name not in LOCAL and dep not in seen:
                seen.add(dep)
                print(dep)
