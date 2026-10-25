# LANL Learn walkthrough video

[LANL-Learn-demo.mp4](LANL-Learn-demo.mp4) (5 min 11 s, captioned, no audio) walks through the whole product:

1. **Sign-in**, one page for employees, managers and admins.
2. **Admin, Training library:** three layers, real source documents per course, managing each file, reviewing and
   publishing draft lessons, division and role layers, plan preview, and data sources.
3. **Manager:** team dashboard, team list, compliance and knowledge gaps, expiring training, the Role directory
   (new hire vs. promotion, assigning a role's trainings in one step), interview reviews, open roles and promotion
   readiness.
4. **Employee:** personal plan, calendar, the Learning studio (a DOE Insider Threat course built from DOE Order
   470.5A, a lesson, the same content as a mind map, practice questions and the AI tutor), and the learning profile.
5. **Accessibility:** high contrast and larger text.

Recorded with AI turned off (offline lessons). With an Anthropic API key, the lessons, tutor and scoring are written
by Claude.

## Re-recording

With the Docker stack running:

```bash
pip install playwright imageio-ffmpeg && python -m playwright install chromium
python scripts/record_demo.py /tmp/demo-video
ffmpeg -i /tmp/demo-video/*.webm -c:v libx264 -preset slow -crf 27 -pix_fmt yuv420p -movflags +faststart -an docs/demo/LANL-Learn-demo.mp4
```

The script publishes three draft trainings (Ethics, Insider Threat, Initial Security) and assigns the Computational
Scientist role to the demo employee, so run it against demo data.
