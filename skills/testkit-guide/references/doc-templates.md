# Document templates and writing rules

## Contents
- Plain user language (all documents)
- User guide (`guide.md`)
- Release notes (`release-notes.md`)
- FAQ / help articles (`faq.md`, `articles/<slug>.md`)
- Vietnamese notes

## Plain user language (all documents)

- Write for someone who has never seen the product and does not know the team's words. Use the **labels exactly as they appear on screen**, in bold: Click **Sign in**.
- One action per step, imperative, present tense: "Type your email address in the **Email** box." Not "The user should enter their credentials".
- Say what happens after the action when it matters: "Your notes page opens."
- No internal words: no ticket keys, TC/BUG ids, stream names, API paths, status codes, component or table names, "AC", "regression", "staging". Unless the user asked for an internal version.
- No promises beyond what you saw: describe only behaviour you observed in the product (or a run report confirmed). Something you could not reach is a question for the user, not a guess.
- Short sentences (≤ 20 words), short paragraphs (≤ 3 sentences). Numbers as digits.
- Errors: quote the exact message and say how to fix it: If you see "Invalid email or password.", check …
- Accessibility: every image has a caption that says what it shows; never rely on colour alone ("the red box" is fine in a caption, but the step text must name the control).
- Screenshots must not show real personal data. Use the demo/test accounts with neutral names; mention in your report if a screenshot shows an email or name.

## User guide (`guide.md`)

```markdown
# <Task-oriented title: "Getting started with Acme Notes">

<One or two sentences: what the reader will be able to do, and how long it takes.>

**Before you start:** <account, role, permission or data the reader needs>

## <Flow 1 as a task: "Sign in">

1. <Step text>.

![Step 1 — <what the image shows>](doc-img/<flow>-01.png)

2. <Step text>.

![Step 2 — …](doc-img/<flow>-02.png)

<Optional: "If you see …" troubleshooting line for the common error of this flow.>

## <Flow 2 …>

## Good to know

| Question | Answer |
|---|---|
```

- One `##` section per flow, in the order a new user does them.
- Step numbers in the text match the badge numbers on the images (the annotator numbers boxes by step within a flow).
- Put a `---` line before a flow to start it on a new page in Word.

## Release notes (`release-notes.md`)

Source material: the tickets of the version (title, description, ACs), their run reports (`qa/runs/<RUN_ID>/report.md` verdicts), the bugs fixed and verified in the period (`qa/bugs/*.md` with `status: verified`), and the bugs still open that users can hit.

```markdown
# <Product> <version> — release notes

Released <date>. <One sentence on the theme of the release.>

## New
- **<Feature name in user words>** — <what the user can now do, and where>. <How to start, if not obvious.>

## Improved
- **<Area>** — <what is better for the user: faster, clearer, fewer steps>.

## Fixed
- <What used to go wrong, in user words, now fixed>: "Coupons that had expired were sometimes accepted at checkout."

## Known issues
- <What can still go wrong> — <workaround if any>. <"We are working on a fix." only if a bug is open.>
```

Rules:
- Group by user impact, not by ticket. Merge tickets that deliver one feature into one line; drop purely internal tickets (refactoring, CI, test data).
- **Fixed** only lists bugs with status `verified` (a `fixed` bug is not proven yet: leave it out or ask).
- **Known issues** lists open/reopened bugs of severity minor or above that a user can reach, plus tickets whose run verdict was `READY WITH KNOWN ISSUES`. Never list security holes in public notes: tell the user instead.
- Tickets with verdict `NOT READY` are not in the release unless the user says they ship anyway; ask.
- No internal IDs unless asked. When asked, add them at the end of a line in parentheses: (PROJ-123).

## FAQ / help articles

`faq.md`: questions people really ask, from (1) the guide's troubleshooting lines, (2) known issues and their workarounds, (3) error messages seen during runs, (4) `Questions` sections of results files that product answered.

```markdown
# <Product> — frequently asked questions

## Signing in

### I see "Invalid email or password." What should I do?
<Answer in 1–4 sentences or steps. Link the guide section if longer.>

### …
```

- Questions in the user's words, starting with "How do I…", "Why…", "What does … mean", "I see … ".
- One answer per question; steps as a numbered list; add one annotated screenshot only when the answer is about finding something on screen.
- A help article (`articles/<slug>.md`) is one task in depth: title as a task, "Before you start", steps with images, "If something goes wrong", "Related".

## Vietnamese notes

When `project.language: vi`: use the on-screen Vietnamese labels exactly; address the reader as "bạn"; prefer short imperative sentences ("Nhấn **Đăng nhập**."); keep product names and English UI labels as they appear in the app. Headings for release notes: **Tính năng mới**, **Cải thiện**, **Đã sửa**, **Vấn đề đã biết**.
