"""Validate and bundle the colleague's static UI; no npm or transpilation needed.

Run: python scripts/build_frontend.py
Uses Node (or VS Code's bundled Node runtime) ONLY for --check syntax parsing.
Copies an explicit static-directory allowlist; never the backend or resources.
"""
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MOUNTS = {"hire": "hire-dashboard", "manager": "manager-dashboard", "shared": "shared", "login": "shared/login"}


def resolve(url, origin):
    url = url.split("?")[0].split("#")[0]
    if not url or url.startswith(("http:", "https:", "data:", "mailto:")):
        return None
    if url.startswith("/"):
        parts = url.lstrip("/").split("/", 1)
        if parts[0] not in MOUNTS:
            return None
        return ROOT / MOUNTS[parts[0]] / (parts[1] if len(parts) > 1 else "")
    return origin.parent / url


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path, self.module, self.inline = path, False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in ("src", "href"):
            if attr in attrs:
                target = resolve(attrs[attr], self.path)
                if target is not None and not target.exists():
                    raise ValueError(f"Missing static asset: {self.path.relative_to(ROOT)} -> {attrs[attr]}")
        if tag == "script":
            self.module = attrs.get("type") == "module" and "src" not in attrs

    def handle_endtag(self, tag):
        if tag == "script":
            self.module = False

    def handle_data(self, text):
        if self.module:
            self.inline.append(text)


def node_runtime():
    node = shutil.which("node")
    if node:
        return node, False
    code = shutil.which("code")
    if code:
        exe = Path(code).resolve().parent.parent / "Code.exe"
        if exe.exists():
            return str(exe), True
    raise SystemExit("Install Node.js or make VS Code's code command available to validate JavaScript syntax.")


def main():
    runtime, electron = node_runtime()
    env = os.environ.copy()
    if electron:
        env["ELECTRON_RUN_AS_NODE"] = "1"
    files = []
    count = 0
    for folder in ("hire-dashboard", "manager-dashboard", "shared"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in (".html", ".js", ".css", ".svg", ".png", ".ico"):
                continue
            files.append(path)
            if path.suffix not in (".js", ".html"):
                continue
            text = path.read_text(encoding="utf-8")
            scripts = [text] if path.suffix == ".js" else []
            if path.suffix == ".html":
                page = Page(path)
                page.feed(text)
                scripts.extend(page.inline)
            for script in scripts:
                for url in re.findall(r'''(?:from\s*|import\s*)["']([^"']+)["']''', script):
                    target = resolve(url, path)
                    if target is not None and not target.exists():
                        raise ValueError(f"Missing module: {path.name} -> {url}")
                result = subprocess.run([runtime, "--input-type=module", "--check"], input=script,
                                        text=True, encoding="utf-8", env=env, capture_output=True)
                if result.returncode:
                    raise ValueError(f"JavaScript syntax error in {path.relative_to(ROOT)}:\n{result.stderr}")
                count += 1
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    for path in files:
        target = output / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    print(f"Frontend build passed: {count} JavaScript modules/inline scripts checked; {len(files)} static files bundled to dist/.")


if __name__ == "__main__":
    main()
