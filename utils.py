import datetime as dt
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://pypi.org/pypi"
DEPRECATED_PACKAGES = {
    "BeautifulSoup",
    "bs4",
    "distribute",
    "django-social-auth",
    "nose",
    "pep8",
    "pycrypto",
    "pypular",
    "sklearn",
    "y-py",
}
STABLE_ABI_TAGS = {"abi3", "abi3t"}
BATCH_SIZE = 64
MAX_WORKERS = 12
_thread_local = threading.local()


def get_json_url(package_name):
    return BASE_URL + "/" + package_name + "/json"


def _session():
    # A Session per worker avoids sharing mutable requests state across threads.
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        _thread_local.session = session
    return _thread_local.session


def stable_abi_tags(files):
    """Return stable ABI tags from the wheel filenames in a release's files."""
    tags = set()
    for file in files:
        filename = file.get("filename", "")
        if file.get("packagetype") != "bdist_wheel" or not filename.endswith(".whl"):
            continue
        # The final three hyphen-delimited fields are python, ABI and platform.
        parts = filename[:-4].rsplit("-", 3)
        if len(parts) == 4:
            tags.update(STABLE_ABI_TAGS.intersection(parts[-2].split(".")))
    return tags


def get_package_abi_tags(name):
    response = _session().get(get_json_url(name), timeout=20)
    if response.status_code == 404:
        return set()
    # Fail the build on other errors instead of silently changing the top 100.
    response.raise_for_status()
    return stable_abi_tags(response.json().get("urls", []))


def _normalized_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def annotate_wheels(packages, to_chart: int) -> list[dict]:
    """Find the most-downloaded projects with abi3 wheels in the latest release."""
    if to_chart < 1:
        raise ValueError("number of packages must be positive")

    deprecated = {_normalized_name(name) for name in DEPRECATED_PACKAGES}
    candidates = [
        package
        for package in sorted(packages, key=lambda p: p["downloads"], reverse=True)
        if _normalized_name(package["name"]) not in deprecated
    ]
    selected = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[start : start + BATCH_SIZE]
            # map preserves rank even when API requests finish out of order.
            for package, tags in zip(
                batch,
                executor.map(get_package_abi_tags, (p["name"] for p in batch)),
            ):
                if "abi3" not in tags:
                    continue
                has_abi3t = "abi3t" in tags
                selected.append(
                    {
                        **package,
                        "css_class": "abi3t" if has_abi3t else "abi3-only",
                        "icon": "🧵" if has_abi3t else "✗",
                        "has_abi3_wheel": True,
                        "has_abi3t_wheel": has_abi3t,
                        "stable_free_threaded_wheel": has_abi3t,
                        "title": (
                            "abi3 and abi3t wheels"
                            if has_abi3t
                            else "abi3 wheels, but no abi3t wheels"
                        ),
                    }
                )
                if len(selected) == to_chart:
                    return selected

    raise RuntimeError(
        f"Only {len(selected)} projects offering abi3 wheels found; "
        f"requested {to_chart}"
    )


def get_top_packages():
    print("Getting packages...")
    with open("top-pypi-packages.json", encoding="utf-8") as data_file:
        rows = json.load(data_file)["rows"]
    return sorted(
        (
            {"name": row["project"], "downloads": row["download_count"]}
            for row in rows
        ),
        key=lambda package: package["downloads"],
        reverse=True,
    )


def save_to_file(packages, file_name):
    now = dt.datetime.now(tz=dt.timezone.utc)
    with open(file_name, "w", encoding="utf-8") as output:
        json.dump(
            {
                "data": packages,
                "last_update": now.strftime("%A, %d %B %Y, %X %Z"),
            },
            output,
            indent=1,
        )
