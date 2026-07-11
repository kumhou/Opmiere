"""Rebuild Opmiere web shell: design-system chrome + 4-region layout.

Preserves every element id and the entire <script> block.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "opmiere" / "web" / "static" / "index.html"
CSS_PATH = ROOT / "scripts" / "_shell_style.css"
NEW_STYLE = CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""


def is_tag(n) -> bool:
    return getattr(n, "name", None) is not None


def main() -> None:
    raw = INDEX.read_text(encoding="utf-8")
    script_i = raw.find("<script>")
    assert script_i > 0, "no script"
    script_raw = raw[script_i:]
    soup = BeautifulSoup(raw[:script_i], "html.parser")

    style = soup.find("style")
    style.clear()
    style.append(NEW_STYLE)

    body = soup.body
    header = body.find("header")
    help_modal = body.find(id="helpModal")
    main_el = body.find("main")
    left, center, right = main_el.find_all("section", recursive=False)

    # Detach nodes we keep
    header = header.extract()
    help_modal = help_modal.extract()
    left_kids = [c.extract() for c in list(left.children) if is_tag(c)]
    center_kids = [c.extract() for c in list(center.children) if is_tag(c)]
    right_kids = [c.extract() for c in list(right.children) if is_tag(c)]

    # Split center: Preview section until Timeline h2, then timeline until tool dump
    preview_kids: list = []
    timeline_kids: list = []
    center_tools: list = []
    mode = "preview"
    for n in center_kids:
        text = n.get_text(" ", strip=True) if hasattr(n, "get_text") else ""
        if n.name == "h2" and text.lower() == "timeline":
            mode = "timeline"
            # skip the bare "Timeline" heading; panel head has it
            continue
        if mode == "timeline" and n.name == "label":
            low = text.lower()
            # inspector-ish labels start after timeline essentials
            if any(
                low.startswith(p)
                for p in (
                    "gain",
                    "opacity",
                    "crop",
                    "rotate",
                    "speed",
                    "pip",
                    "fade",
                    "clip name",
                    "project notes",
                    "relink",
                    "export preset",
                    "move to track",
                    "track rename",
                    "search clips",
                    "import markers",
                    "import edl",
                )
            ):
                mode = "tools"
        if mode == "preview":
            # drop the bare Preview h2
            if n.name == "h2" and text.lower() == "preview":
                continue
            preview_kids.append(n)
        elif mode == "timeline":
            timeline_kids.append(n)
        else:
            center_tools.append(n)

    # header → topbar id
    header["id"] = "topbar"
    # restyle brand
    h1 = header.find("h1")
    if h1:
        h1.name = "span"
        h1["class"] = h1.get("class", [])
    sub = header.find(class_="sub")
    brand = soup.new_tag("div", **{"class": "brand"})
    if h1:
        brand.append(h1.extract())
    if sub:
        brand.append(sub.extract())
    # insert brand at start
    header.insert(0, brand)
    # spacer before help
    btn_help = header.find(id="btnHelp")
    spacer = soup.new_tag("div", **{"class": "spacer"})
    if btn_help:
        btn_help.insert_before(spacer)
        actions = soup.new_tag("div", **{"class": "top-actions"})
        actions.append(btn_help.extract())
        header.append(actions)

    # help modal card class
    if help_modal and help_modal.find("div"):
        d = help_modal.find("div")
        classes = d.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        if "help-card" not in classes:
            d["class"] = classes + ["help-card"]

    def make_panel(pid: str, title: str, kids: list, body_class: str | None = None):
        sec = soup.new_tag("section", id=pid, **{"class": "panel"})
        head = soup.new_tag("div", **{"class": "panel-head"})
        h = soup.new_tag("h2")
        h.string = title
        head.append(h)
        body_div = soup.new_tag(
            "div",
            **{"class": "panel-body" + (f" {body_class}" if body_class else "")},
        )
        for k in kids:
            body_div.append(k)
        sec.append(head)
        sec.append(body_div)
        return sec

    # Media panel = left column content
    panel_media = make_panel("panel-media", "Media / Project", left_kids)

    # Preview panel
    preview_wrap_kids = preview_kids
    # wrap in previewStack for flex
    stack = soup.new_tag("div", id="previewStack")
    for k in preview_wrap_kids:
        stack.append(k)
    panel_preview = soup.new_tag("section", id="panel-preview", **{"class": "panel"})
    ph = soup.new_tag("div", **{"class": "panel-head"})
    ph2 = soup.new_tag("h2")
    ph2.string = "Program"
    ph.append(ph2)
    panel_preview.append(ph)
    # preview uses stack as body without extra padding conflict
    pb = soup.new_tag("div", **{"class": "panel-body", "style": "padding:0;display:flex;flex-direction:column;min-height:0"})
    pb.append(stack)
    panel_preview.append(pb)

    # Timeline panel
    tl_chrome = soup.new_tag("div", id="timelineChrome")
    tl_main = soup.new_tag("div", **{"class": "tl-main"})
    for k in timeline_kids:
        tl_main.append(k)
    tl_chrome.append(tl_main)
    panel_timeline = soup.new_tag("section", id="panel-timeline", **{"class": "panel"})
    th = soup.new_tag("div", **{"class": "panel-head"})
    th2 = soup.new_tag("h2")
    th2.string = "Timeline"
    th.append(th2)
    panel_timeline.append(th)
    tb = soup.new_tag("div", **{"class": "panel-body", "style": "padding:0;display:flex;flex-direction:column;min-height:0;overflow:hidden"})
    tb.append(tl_chrome)
    panel_timeline.append(tb)

    # Inspector = center tools + right column, in collapsible groups
    inspector_kids: list = []

    def group(title: str, nodes: list, open_=False):
        det = soup.new_tag("details", **{"class": "tool-group"})
        if open_:
            det["open"] = ""
        s = soup.new_tag("summary")
        s.string = title
        g = soup.new_tag("div", **{"class": "group-body"})
        for n in nodes:
            g.append(n)
        det.append(s)
        det.append(g)
        return det

    # Put clip-related tools first (open), then craft from right, then rest
    # Split center_tools into chunks by h2 if any, else one big "Clip tools"
    if center_tools:
        inspector_kids.append(group("Clip / edit tools", center_tools, open_=True))

    # Right column: split by h2
    bucket: list = []
    bucket_title = "Craft"
    for n in right_kids:
        if n.name == "h2":
            if bucket:
                inspector_kids.append(group(bucket_title, bucket, open_=(bucket_title in ("Craft", "Mix"))))
                bucket = []
            bucket_title = n.get_text(" ", strip=True) or "Tools"
            continue
        bucket.append(n)
    if bucket:
        inspector_kids.append(group(bucket_title, bucket, open_=(bucket_title in ("Craft", "Mix", "Doctor"))))

    panel_inspector = make_panel("panel-inspector", "Inspector", inspector_kids)

    app = soup.new_tag("div", id="app")
    app.append(panel_media)
    app.append(panel_preview)
    app.append(panel_inspector)
    app.append(panel_timeline)

    # Rebuild body
    body.clear()
    body.append(header)
    body.append(help_modal)
    body.append(app)

    # Validate ids
    new_html = str(soup)
    new_ids = set()
    import re
    new_ids = set(re.findall(r'\bid="([^"]+)"', new_html))
    # script may reference ids; compare to old
    old_ids = set(re.findall(r'\bid="([^"]+)"', raw[:script_i]))
    missing = sorted(old_ids - new_ids)
    extra = sorted(new_ids - old_ids)
    if missing:
        raise SystemExit(f"Missing ids ({len(missing)}): {missing[:40]}")

    out = "<!DOCTYPE html>\n" + new_html
    if not out.rstrip().endswith("</html>"):
        pass
    # soup may have added html wrapper; ensure script appended before </body>
    if "</body>" in out:
        out = out.replace("</body>", script_raw + "\n</body>")
    else:
        out = out + script_raw

    INDEX.write_text(out, encoding="utf-8")
    print(f"Wrote {INDEX}")
    print(f"ids old={len(old_ids)} new={len(new_ids)} extra={extra}")
    print(f"preview nodes={len(preview_kids)} timeline={len(timeline_kids)} tools={len(center_tools)}")


if __name__ == "__main__":
    main()
