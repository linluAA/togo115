from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
JS_SRC = STATIC / "src" / "js"
CSS_SRC = STATIC / "src" / "css"

JS_FILES = [
    "00_state.js",
    "10_shell.js",
    "15_dashboard.js",
    "20_tmdb_home.js",
    "21_tmdb_cards.js",
    "22_tmdb_detail.js",
    "30_emby.js",
    "40_subscriptions_view.js",
    "41_subscription_cards.js",
    "42_subscription_resources.js",
    "50_logs.js",
    "60_settings_view.js",
    "61_settings_sources_model.js",
    "62_settings_sources_view.js",
    "63_settings_sources_actions.js",
    "64_settings_actions.js",
    "70_integrations.js",
]

CSS_FILES = [
    "00_tokens.css",
    "01_base_layout.css",
    "02_components.css",
    "03_pages.css",
    "10_desktop_shell.css",
    "20_tablet.css",
    "30_mobile.css",
    "40_small_mobile.css",
    "50_desktop_enhancements.css",
    "51_wide_desktop.css",
]


def _minify_css(text):
    """String-aware CSS compression (comments + whitespace runs outside strings).

    Quoted strings are copied byte-for-byte, so content/url() values never
    change. Whitespace runs collapse to a single space, which CSS treats as
    equivalent anywhere outside strings.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            if out and not out[-1].isspace():
                out.append(" ")
            continue
        ch = text[i]
        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if out and not out[-1].isspace():
                out.append(" ")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip()


REGEX_PREFIX_WORDS = {
    "return", "typeof", "instanceof", "in", "of", "case", "delete", "void",
    "new", "do", "else", "yield", "await",
}
_REGEX_PREFIX_CHARS = set("(,=:[!&|?{};<>+-*%^~")
_COMPOSITE_OPS = {
    "++", "--", "**", "&&", "||", "<<", ">>", ">>>", ">=", "<=", "==", "!=",
    "===", "!==", "+=", "-=", "*=", "/=", "%=", "**=", "<<=", ">>=", ">>>=",
    "&&=", "||=", "??=", "??", "?.", "=>",
}


def _minify_js(text: str) -> str:
    """String/regex/comment-aware JS compression.

    Comments are dropped and whitespace runs collapse outside strings; a single
    newline is kept where one existed so automatic-semicolon-insertion rules are
    unaffected. No renaming or cross-line joining happens.
    """
    out: list[str] = []
    i, n = 0, len(text)
    prev_token: str | None = None
    prev_word: str | None = None
    last_was_ws = True
    while i < n:
        ch = text[i]
        if ch in "'\"":
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            token = text[i:j]
            out.append(token)
            prev_token = quote
            prev_word = None
            last_was_ws = False
            i = j
            continue
        if ch == "`":
            # Template literal: track ${...} nesting so braces inside
            # expressions do not confuse the scanner.
            j = i + 1
            depth = 0
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if depth == 0 and text[j] == "`":
                    j += 1
                    break
                if text.startswith("${", j):
                    depth += 1
                    j += 2
                    continue
                if depth and text[j] == "}":
                    depth -= 1
                j += 1
            token = text[i:j]
            out.append(token)
            prev_token = "`"
            prev_word = None
            last_was_ws = False
            i = j
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                j = text.find("\n", i)
                j = n if j == -1 else j
                i = j
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                j = n if end == -1 else end + 2
                if not last_was_ws and j < n and not text[j].isspace():
                    out.append(" ")
                    last_was_ws = True
                i = j
                continue
            if _looks_like_regex(prev_token, prev_word):
                j = i + 1
                in_class = False
                while j < n:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "[":
                        in_class = True
                    elif text[j] == "]":
                        in_class = False
                    elif text[j] == "/" and not in_class:
                        j += 1
                        while j < n and text[j].isalpha():
                            j += 1
                        break
                    j += 1
                out.append(text[i:j])
                prev_token = "/"
                prev_word = None
                last_was_ws = False
                i = j
                continue
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            need_sep = False
            if prev_token:
                k = j
                while k < n and text[k].isspace():
                    k += 1
                nxt = text[k] if k < n else None
                if nxt is not None and (prev_token + nxt) in _COMPOSITE_OPS:
                    need_sep = True
            if "\n" in text[i:j]:
                if not last_was_ws:
                    out.append("\n")
                    last_was_ws = True
            elif need_sep and not last_was_ws:
                out.append(" ")
                last_was_ws = True
            i = j
            continue
        if ch.isalnum() or ch in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            if out and (out[-1].isalnum() or out[-1] in "_$}"):
                out.append(" ")
            out.append(word)
            prev_word = word
            prev_token = None
            last_was_ws = False
            i = j
            continue
        out.append(ch)
        prev_token = ch
        prev_word = None
        last_was_ws = False
        i += 1
    return "".join(out).strip() + "\n"


def _looks_like_regex(prev_token: str | None, prev_word: str | None) -> bool:
    if prev_word is not None:
        return prev_word in REGEX_PREFIX_WORDS
    return prev_token is None or prev_token in _REGEX_PREFIX_CHARS


def bundle(files, source_dir, target, header, minify=False):
    chunks = [header.rstrip(), ""]
    if minify and target.suffix == ".js":
        for name in files:
            path = source_dir / name
            raw = path.read_text(encoding="utf-8").strip()
            chunks.append(_minify_js(raw).rstrip())
            chunks.append("")
    else:
        for name in files:
            path = source_dir / name
            chunks.append(f"/* source: {path.relative_to(ROOT).as_posix()} */")
            chunks.append(path.read_text(encoding="utf-8").strip())
            chunks.append("")
    text = "\n".join(chunks).rstrip() + "\n"
    if minify and target.suffix == ".css":
        text = _minify_css(text) + "\n"
    target.write_text(text, encoding="utf-8")


def main():
    bundle(
        JS_FILES,
        JS_SRC,
        STATIC / "app.js",
        "// Generated by app/tools/build_static.py. Edit app/static/src/js/* instead.",
        minify=True,
    )
    bundle(
        CSS_FILES,
        CSS_SRC,
        STATIC / "styles.css",
        "/* Generated by app/tools/build_static.py. Edit app/static/src/css/* instead. */",
        minify=True,
    )


if __name__ == "__main__":
    main()
