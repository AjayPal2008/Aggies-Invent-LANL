"""Record the captioned LANL Learn walkthrough (docs/demo/LANL-Learn-demo.mp4).

Needs the Docker stack running (http://localhost:8000) and Playwright:
    pip install playwright imageio-ffmpeg && python -m playwright install chromium
    python scripts/record_demo.py /tmp/demo-video      # records a .webm into that folder
Then convert to MP4 with ffmpeg (see docs/demo/README.md). The walkthrough publishes three draft trainings and
assigns a role to the demo employee, so run it on demo data only.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://localhost:8000"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "video")
W, H = 1440, 900

OVERLAY = r"""
(() => {
  const add = () => {
    if (document.getElementById('__cap')) return;
    const st = document.createElement('style');
    st.textContent = `#__cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1100px;z-index:2147483647;
      background:rgba(10,24,72,.92);color:#fff;font:600 20px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;padding:14px 22px;
      border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.35);text-align:center;opacity:0;transition:opacity .35s;pointer-events:none}
      #__cap.on{opacity:1} #__cap small{display:block;font-weight:500;font-size:15px;opacity:.85;margin-top:2px}
      #__cur{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:2147483646;
      background:rgba(255,190,40,.55);border:2px solid #f5a300;pointer-events:none;transition:transform .08s}
      #__cur.down{transform:scale(.7);background:rgba(255,150,0,.8)}
      #__title{position:fixed;inset:0;z-index:2147483647;background:linear-gradient(135deg,#0b1d5c,#1f3c9b);color:#fff;display:flex;
      flex-direction:column;align-items:center;justify-content:center;font-family:system-ui,-apple-system,sans-serif;text-align:center;padding:40px}
      #__title h1{font-size:56px;margin:0 0 14px;color:#fff} #__title p{font-size:24px;margin:6px 0;opacity:.9;max-width:1000px}`;
    document.head.appendChild(st);
    const c = document.createElement('div'); c.id = '__cap'; document.body.appendChild(c);
    const k = document.createElement('div'); k.id = '__cur'; document.body.appendChild(k);
    const x = sessionStorage.getItem('__curxy'); if (x) { const [a, b] = x.split(','); k.style.left = a + 'px'; k.style.top = b + 'px'; }
    else { k.style.left = '720px'; k.style.top = '450px'; }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
  window.__cap = (t, s) => { add(); const c = document.getElementById('__cap'); if (!t) { c.classList.remove('on'); return; }
    c.innerHTML = t + (s ? `<small>${s}</small>` : ''); c.classList.add('on'); };
  window.__move = (x, y, ms) => new Promise(r => { add(); const k = document.getElementById('__cur');
    const sx = parseFloat(k.style.left) || 720, sy = parseFloat(k.style.top) || 450, t0 = performance.now();
    const step = (t) => { const p = Math.min(1, (t - t0) / ms), e = p < .5 ? 2*p*p : 1 - Math.pow(-2*p + 2, 2) / 2;
      k.style.left = (sx + (x - sx) * e) + 'px'; k.style.top = (sy + (y - sy) * e) + 'px';
      if (p < 1) requestAnimationFrame(step); else { sessionStorage.setItem('__curxy', x + ',' + y); r(); } };
    requestAnimationFrame(step); });
  window.__press = () => { const k = document.getElementById('__cur'); k.classList.add('down'); setTimeout(() => k.classList.remove('down'), 180); };
})();
"""


class Demo:
    def __init__(self, page):
        self.p = page

    async def wait(self, s):
        await self.p.wait_for_timeout(int(s * 1000))

    async def cap(self, text, sub="", hold=0):
        await self.p.evaluate("([t, s]) => window.__cap(t, s)", [text, sub])
        if hold:
            await self.wait(hold)

    async def title(self, heading, lines, hold=4.5):
        html = f"<h1>{heading}</h1>" + "".join(f"<p>{l}</p>" for l in lines)
        await self.p.evaluate("h => { const d = document.createElement('div'); d.id = '__title'; d.innerHTML = h; document.body.appendChild(d); }", html)
        await self.wait(hold)
        await self.p.evaluate("() => document.getElementById('__title')?.remove()")

    async def point(self, selector, ms=700):
        loc = self.p.locator(selector).first
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        if not box:
            return None
        x, y = box["x"] + min(box["width"] / 2, 160), box["y"] + box["height"] / 2
        await self.p.evaluate("([x, y, ms]) => window.__move(x, y, ms)", [x, y, ms])
        return loc

    async def click(self, selector, after=1.2):
        loc = await self.point(selector)
        if loc is None:
            print("  ! not found:", selector)
            return False
        await self.p.evaluate("() => window.__press()")
        await self.wait(0.25)
        try:
            await loc.click(timeout=4000)
        except Exception:
            await loc.evaluate("e => e.click()")  # something overlaps it; click it directly
        await self.wait(after)
        return True

    async def go(self, view, after=2.2):
        link = f"nav [data-view='{view}']"
        if await self.p.locator(link).count():
            await self.click(link, after)
        else:
            await self.p.evaluate(f"location.hash = '#{view}'")
            await self.wait(after)

    async def scroll(self, px, steps=6, pause=0.25):
        for _ in range(steps):
            await self.p.mouse.wheel(0, px / steps)
            await self.wait(pause)

    async def type(self, selector, text):
        await self.click(selector, 0.3)
        await self.p.locator(selector).first.press_sequentially(text, delay=45)

    async def sign_out(self):
        await self.p.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        await self.p.goto(BASE + "/login/")
        await self.wait(1.2)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(OUT),
                                        record_video_size={"width": W, "height": H}, device_scale_factor=1)
        await ctx.add_init_script(OVERLAY)
        page = await ctx.new_page()
        d = Demo(page)

        # ---- intro and sign-in ---------------------------------------------------------
        await page.goto(BASE + "/login/")
        await d.wait(1.2)
        await d.title("LANL Learn", ["Adaptive training for Los Alamos National Laboratory",
                                     "Product walkthrough: admin library → manager tools → employee learning"])
        await d.cap("One sign-in for employees, managers and training admins",
                    "LANL company email, or single sign-on. These demo buttons sign in as each role.", 4)

        # ---- admin: training library ---------------------------------------------------
        await d.cap("Training admin", "Signing in as the admin who owns the training library")
        await d.click("[data-demo='admin@lanl.gov']", 3)
        await d.go("library", 3)
        await d.cap("The training library: every LANL requirement in three layers",
                    "Institutional (everyone), division (Weapons, STE, Operations) and role, the way UTrain assigns them", 4)
        await d.scroll(420)
        await d.cap("Each course is backed by real source documents",
                    "LANL manuals, the Code of Conduct, DOE orders and handbooks, federal regulations: 74 courses, 84 documents", 3.5)
        await d.click("tr[data-code='UT-27392'], tr[data-code='UT-27392'] td", 2.5)
        await d.cap("Admins manage every file",
                    "Open, rename, replace with a newer version, re-download from LANL, or delete. Upload PDFs and slide decks.", 4.5)
        await page.keyboard.press("Escape")
        await d.wait(1)
        await d.scroll(-420)
        await d.cap("AI-built lessons are drafts until a person reviews them",
                    "Nothing reaches employees until the training owner checks it against the source pages", 2.5)
        await d.click("#lib-publish", 2.5)
        for code in ("UT-27392", "UT-31112", "UT-62676"):
            await d.click(f"input[name=code][value='{code}']", 0.6)
        await d.cap("Publishing Ethics, Insider Threat and Initial Security to learners", "", 1.5)
        await d.click("input[name=reviewed]", 0.8)
        await d.click("#pd button.btn:not(.ghost)", 2.5)
        for tab in ("weapons", "roles", "path"):
            await d.click(f"[data-tab='{tab}']", 2.2)
            if tab == "weapons":
                await d.cap("Division layer", "What everyone in Weapons needs, on top of institutional training", 2.5)
            elif tab == "roles":
                await d.cap("Role layer", "Technical and soft-skill training per role; roles repeat across divisions with additions", 2.5)
            else:
                await d.cap("Plan preview", "See exactly what a new hire, a promotion or a transfer would be assigned", 2.5)
        await d.go("data", 2.5)
        await d.cap("Connected to LANL's systems", "LANL directory, UTrain and Oracle HR feeds, with sync status in one place", 4)

        # ---- manager ---------------------------------------------------------------------
        await d.sign_out()
        await d.cap("Group leader", "Signing in as a manager with an 86-person organization")
        await d.click("[data-demo='manager@lanl.gov']", 3.5)
        await d.cap("The team at a glance", "Progress, overdue and expiring training, new hires by fiscal year", 3.5)
        await d.scroll(500)
        await d.wait(1.5)
        await d.go("team", 2.5)
        await d.cap("Built for 80–90 person teams", "Sub-teams, filters, bulk assign, due dates, reminders and CSV export", 4)
        await d.go("insights", 2.5)
        await d.cap("Compliance and knowledge gaps", "Required-training compliance by division, and a knowledge-gap heatmap by role", 4)
        await d.go("retraining", 2.5)
        await d.cap("Expiring training and retakes", "Retake windows are set by assessment scores, so weak areas get revisited sooner", 3.5)

        await d.go("roledirectory", 2.5)
        await d.cap("Role directory: you hired someone. What do they need?",
                    "Open the role and get its job description, skills and every training to assign", 3.5)
        await d.click("[data-role='computational-scientist']", 3)
        await d.cap("Job description, required skills, and the full list", "Grouped by layer, with when each is due", 3.5)
        await d.scroll(520)
        await d.wait(1.5)
        await page.select_option("#rd-entry", "promotion")
        await page.wait_for_selector("#rd-list", timeout=15000)
        await d.wait(1)
        await page.evaluate("document.querySelector('#rd-list').scrollIntoView({behavior: 'smooth', block: 'start'})")
        await d.wait(1.5)
        await d.cap("A promotion within the division gets only the new role's training",
                    "Institutional and division training are already done and renew on their own cycle", 4)
        await page.select_option("#rd-entry", "new_hire")
        await page.wait_for_selector("#rd-list", timeout=15000)
        await d.wait(1)
        await page.evaluate("document.querySelector('#rd-list').scrollIntoView({behavior: 'smooth', block: 'start'})")
        await d.wait(1.5)
        await d.cap("A new hire gets onboarding, division and role training", "Assign it in one step", 2.5)
        await d.click("#rd-assign", 2)
        await d.type("#as-q", "Jordan")
        await d.wait(1.5)
        await d.click("#as-results [data-pick]", 1)
        await d.click("#as-go", 2.5)
        await d.cap("Done: Jordan's onboarding is assigned with due dates", "Anything already in progress is left alone", 3)
        await page.keyboard.press("Escape")
        await d.wait(0.8)

        await d.go("interviews", 2)
        await d.cap("Interview reviews", "CASPer-style scenario answers, scored 1–9 by AI against a rubric; the manager's score counts", 3.5)
        await d.go("roles", 2.5)
        await d.cap("Open roles", "Internal candidates ranked by skills, completed training, experience and performance", 3.5)
        await d.go("promotions", 2.5)
        await d.cap("Promotion readiness", "Clear criteria for who is ready to move up, and what's still missing", 3.5)

        # ---- employee --------------------------------------------------------------------
        await d.sign_out()
        await d.cap("Employee", "Signing in as Jordan, a new data scientist")
        await d.click("[data-demo-path='employee']", 3.5)
        await d.cap("A personal plan, by phase", "First 2 weeks, 30 days, 90 days, tailored to Jordan's role and experience", 4)
        await d.scroll(450)
        await d.wait(1.5)
        await d.go("calendar", 2.5)
        await d.cap("Calendar", "Due dates and in-person classes Jordan can register for", 3)
        await d.go("studio", 2.5)
        await d.cap("Learning studio", "Review courses from the diagnostic, plus every assigned course", 3)
        await d.click("#assigned-courses", 3)
        await d.point("#s-training")
        await page.select_option("#s-training", "UT-31112")
        await d.wait(3)
        await d.cap("DOE Insider Threat Awareness, built from DOE Order 470.5A",
                    "The source document is split into short modules, so nobody has to read all 45 pages", 4)
        mod = "[data-module]:has-text('EMPLOYEE TRAINING')"
        if not await page.locator(mod).count():
            mod = "[data-module] >> nth=1"
        await d.click(mod, 1.5)
        await d.click("#s-gen", 3.5)
        await d.scroll(520)
        await d.wait(0.8)
        await d.cap("A lesson built from the document's own pages",
                    "Tuned to Jordan's level and pace, with read-aloud on every section", 3.5)
        await d.scroll(300)
        await d.wait(2)
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await d.wait(1)
        await d.point("#s-modality")
        await page.select_option("#s-modality", "mindmap")
        await d.wait(0.8)
        await d.click("#s-gen", 3.5)
        await page.evaluate("document.querySelector('#lesson').scrollIntoView({behavior: 'smooth', block: 'start'})")
        await d.wait(1.2)
        await d.cap("Same content, different format", "Text, mind map or audio; the platform learns which format works for each person", 3.5)
        await d.scroll(500)
        await d.wait(1.5)
        await d.scroll(-500)
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await d.wait(1)
        await d.click("#s-practice", 3.5)
        await d.cap("Practice questions before the real quiz", "Policies are tested with quizzes; judgment calls with situational interviews", 3.5)
        await d.type("#chat-input", "Can I accept a gift from a vendor?")
        await page.keyboard.press("Enter")
        await d.wait(3.5)
        await d.cap("An AI tutor answers questions about the course", "", 3)
        await d.go("profile", 2.5)
        await d.cap("Learning profile", "Skills, progress and the formats that work best for Jordan, measured rather than guessed", 4)

        # ---- accessibility ---------------------------------------------------------------
        await d.cap("")
        await d.click("#a11y-open", 1.5)
        await d.cap("Accessible by design", "High contrast, color-blind-safe themes, larger text, read-aloud, captions, extra time", 3)
        await d.click("input[name=contrast][value='high-dark']", 2.5)
        await d.cap("High contrast (dark)", "Settings follow the employee across devices", 2)
        await d.click("input[name=textScale][value='1.5']", 2.5)
        await d.cap("Larger text for low vision", "", 2)
        await d.click("input[name=textScale][value='1']", 0.8)
        await d.click("input[name=contrast][value='standard']", 1.2)
        await d.wait(2)
        await page.keyboard.press("Escape")
        await d.wait(1)

        await d.cap("")
        await d.title("LANL Learn", ["The right training for every new hire, promotion and transfer",
                                     "Lessons built from LANL's own documents, reviewed before publishing",
                                     "Adapts to each person · Compliance for managers · Accessible · Scales to 20,000+"], 6)
        await ctx.close()
        await browser.close()


asyncio.run(main())
