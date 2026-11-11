---
title: Reactive Resume
---

# Reactive Resume

The **Resume** page reads your resumes from [Reactive Resume](https://rxresu.me),
the hosted instance or your own, and shows the one you pick as text: its
basics, summary and sections, with what you hid left out. Only admins see the
page: it reads with the server's API key, which belongs to the operator's
account.

## Setting it up

Two server secrets, nothing else:

| Variable                  | What it is                                                                     |
| ------------------------- | ------------------------------------------------------------------------------ |
| `REACTIVE_RESUME_URL`     | The root of the instance, e.g. `https://resume.example.com`; blank: rxresu.me |
| `REACTIVE_RESUME_API_KEY` | An API key of your Reactive Resume account (read access is enough)            |

The list holds every resume of the key's account, newest change first: no
username or slug to configure. Without the key the page says what to set and
reads nothing. The key goes out as `x-api-key` on the instance's OpenAPI
routes (`/api/openapi`, Reactive Resume v5 or later), and the server never
follows a redirect, which would carry the key along: point
`REACTIVE_RESUME_URL` at the instance's final address. Use `https://` for any
instance reached through the internet or an ingress, or the key travels
unencrypted: an `http://` address that only redirects to its https twin is
refused with that https address to set.

## What the page shows

- **The list**: each resume's name, slug, tags, last change, and whether it is
  public or locked.
- **A resume**: name, headline, contact details and custom fields, the summary,
  then every visible section in reading order (experience, education, skills,
  languages, certifications, projects…), custom sections last. Rich text reads
  as plain text, lists as `- ` lines; only http(s) links are kept, and a
  reference's phone number is left out.

## Your resume as a dataset

Each resume can feed a private Hugging Face dataset of question/answer pairs
about you, for a portfolio chatbot or its evaluation. Its card, above the
resume, holds the settings:

| Setting      | What it decides                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------ |
| Publishes to | The dataset, `namespace/name`; by default `resume-<slug>` in your namespace, one dataset per resume                |
| Language     | The pairs' language: the resume's own (detected from its text), English or French                                  |
| Model        | Your LLM, or another model of your endpoint                                                                        |
| Regenerate   | Only when you generate it, every day, every Monday or the 1st of every month, at a time of your choice (UTC)       |
| Publish      | For a scheduled run: publish what passes the checks at once and keep the doubtful pairs for review (on by default) |

**Generate a draft** queues a run with the saved settings: it stops at a draft
that you review in **Drafts** before anything reaches the Hub. A scheduled run
publishes what passes and keeps the pairs held out for review as a draft of its
own; with **Publish** off it stops at a draft too.

The dataset has the columns of the [GitHub Q&A](./github.md) dataset, `source`
being `resume`, so the two join as they are:

- **Facts** (category `profile`): who you are, where, your current or latest
  position, where you worked, what you studied, your skills, languages,
  certifications and projects as the resume lists them, and how to reach you
  (email, website, links — never the phone number). Exact answers from the
  resume's fields, no model, rebuilt every run.
- **Generated pairs** (category: the section, such as `experience` or
  `skills`): one model call per batch of a section's items, each question
  naming you. A rephrasing of an existing question is dropped, and an answer
  far from its item is held out for review (`review.jsonl`).
- **Unanswerable questions** (category `unanswerable`): about six plausible
  questions about you that the resume doesn't answer (a degree, a skill or a
  job it doesn't list), each answered by saying so, with what the resume does
  say on the topic and how to reach you. They test, and teach, the portfolio's
  chat to decline instead of inventing. Asked again only when the resume
  changes; one it now answers is dropped.

Your LLM then grades every new pair, 0 to 1: true to its source, useful to a
visitor, its question self-contained. A pair graded below 0.6 is held out for
review with the grader's reason (`judge`, `judge_note`); an unanswerable
question the resume does answer is dropped. The exact facts are not graded,
and the length rule of the **Quality** page doesn't apply to them.

Runs are incremental: every item is hashed into the dataset's `manifest.json`,
an unchanged item keeps its pairs with no model call, and a resume that hasn't
changed since the published version costs nothing — a daily schedule only
spends tokens on the days you edit it. **Regenerate every section** ignores the
published version.

## API

| Route                                   | Returns                                                         |
| --------------------------------------- | --------------------------------------------------------------- |
| `GET /resumes`                          | The instance read, and every resume of the key's account        |
| `GET /resumes/{resume_id}`              | One resume as text: basics, summary and the visible sections    |
| `GET /resumes/{resume_id}/dataset`      | Its dataset settings, the next scheduled run and the latest run |
| `PUT /resumes/{resume_id}/dataset`      | Save them; a preset runs first at its next time                 |
| `DELETE /resumes/{resume_id}/dataset`   | Forget them: the schedule stops, the dataset stays              |
| `POST /resumes/{resume_id}/dataset/run` | Queue a generation that stops at a draft (`202`)                |

Errors: `400` without `REACTIVE_RESUME_API_KEY` or for an unusable model, `403`
for a user who isn't an admin, `404` for a resume the key's account doesn't
hold or settings not saved yet, `409` while a generation runs, `422` for a bad
setting, and `502` when the instance refuses the key, redirects, fails to
answer or isn't a Reactive Resume instance; the message says which.
