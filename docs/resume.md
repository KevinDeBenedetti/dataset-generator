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
`REACTIVE_RESUME_URL` at the instance's final address.

## What the page shows

- **The list**: each resume's name, slug, tags, last change, and whether it is
  public or locked.
- **A resume**: name, headline, contact details and custom fields, the summary,
  then every visible section in reading order (experience, education, skills,
  languages, certifications, projects…), custom sections last. Rich text reads
  as plain text, lists as `- ` lines; only http(s) links are kept, and a
  reference's phone number is left out.

## API

| Route                      | Returns                                                       |
| -------------------------- | ------------------------------------------------------------- |
| `GET /resumes`             | The instance read, and every resume of the key's account      |
| `GET /resumes/{resume_id}` | One resume as text: basics, summary and the visible sections |

Errors: `400` without `REACTIVE_RESUME_API_KEY`, `403` for a user who isn't an
admin, `404` for a resume the key's account doesn't hold, and `502` when the
instance refuses the key, redirects, fails to answer or isn't a Reactive Resume
instance; the message says which.
