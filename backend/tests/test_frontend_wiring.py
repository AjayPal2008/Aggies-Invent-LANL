"""Static checks on the dashboards' JavaScript (no Node needed).

Catches the kind of bug that silently breaks every page: a helper exported from shared/api.js
that isn't defined, or a page importing something api.js doesn't export.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = (ROOT / "shared" / "api.js").read_text()


def _defined(src: str) -> set[str]:
    return set(re.findall(r"^(?:export\s+)?(?:async\s+)?function\s+([\w$]+)", src, re.M)) | \
        set(re.findall(r"^(?:export\s+)?(?:const|let|class)\s+([\w$]+)", src, re.M))


def test_api_object_only_uses_defined_helpers():
    body = re.search(r"export const api = \{(.*?)\n\};", API, re.S).group(1)
    shorthand = [m for m in re.findall(r"^\s*(\w+),\s*$", body, re.M)]
    missing = [name for name in shorthand if name not in _defined(API)]
    assert not missing, f"api.js exports undefined helpers: {missing}"


def test_pages_import_only_what_api_exports():
    exported = set(re.findall(r"^export\s+(?:async\s+)?(?:function|const|class)\s+([\w$]+)", API, re.M))
    for js in [*ROOT.glob("*-dashboard/*.js"), *ROOT.glob("shared/login/*.html")]:
        src = js.read_text()
        for names in re.findall(r"import\s*\{([^}]*)\}\s*from\s*\"/shared/api\.js\"", src, re.S):
            wanted = {n.strip() for n in names.split(",") if n.strip()}
            assert wanted <= exported, f"{js.name} imports missing names: {sorted(wanted - exported)}"


def test_local_imports_exist():
    for js in ROOT.glob("*-dashboard/*.js"):
        src = js.read_text()
        for names, mod in re.findall(r"import\s*\{([^}]*)\}\s*from\s*\"\./([\w-]+\.js)\"", src, re.S):
            other = (js.parent / mod).read_text()
            exported = set(re.findall(r"^export\s+(?:async\s+)?(?:function|const|class)\s+([\w$]+)", other, re.M))
            wanted = {n.strip() for n in names.split(",") if n.strip()}
            assert wanted <= exported, f"{js.name} imports {sorted(wanted - exported)} from {mod}"


SERVED = {"/hire/": "hire-dashboard", "/manager/": "manager-dashboard", "/shared/": "shared"}


def test_cross_page_imports_resolve():
    """Absolute imports like /hire/learning.js must point at a real file and exported names."""
    for js in ROOT.glob("*-dashboard/*.js"):
        src = js.read_text()
        for names, url in re.findall(r"import\s*\{([^}]*)\}\s*from\s*\"(/(?:hire|manager)/[\w-]+\.js)(?:\?[^\"]*)?\"", src, re.S):
            prefix = next(p for p in SERVED if url.startswith(p))
            target = ROOT / SERVED[prefix] / url[len(prefix):]
            assert target.exists(), f"{js.name} imports {url}, which isn't served"
            exported = set(re.findall(r"^export\s+(?:async\s+)?(?:function|const|class)\s+([\w$]+)", target.read_text(), re.M))
            wanted = {n.strip() for n in names.split(",") if n.strip()}
            assert wanted <= exported, f"{js.name} imports {sorted(wanted - exported)} from {url}"
        assert "../" not in "".join(re.findall(r"from\s*\"([^\"]+)\"", src)), f"{js.name} uses a relative path outside its folder"
