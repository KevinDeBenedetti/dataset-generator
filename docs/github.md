---
title: GitHub recipes
---

# GitHub recipes

The **GitHub** page shows your public GitHub data and the recipes that turn it
into datasets. A recipe picks what a dataset is generated from and names the
Hugging Face dataset it publishes to; a generation stops at a draft that you
review before anything reaches the Hub.

Only public data is read. A GitHub token saved in **Settings** only raises the
API quota from 60 to 5,000 requests an hour; the page shows what is left.

## Recipes

| Setting       | What it does                                                                     |
| ------------- | -------------------------------------------------------------------------------- |
| Name          | How you tell recipes apart (unique per user, 50 recipes at most)                 |
| Publishes to  | The Hugging Face dataset, `namespace/name`, created private on the first publish |
| Model         | The model for the generation; empty uses the **jobs** default of the Models page |
| Profile facts | Who you are, your stack and your projects, from your GitHub profile              |
| Repos         | Up to 200, each with its README and metadata or not, and its `docs/` files       |

Every change is saved as you go. Deleting a recipe leaves its Hugging Face
dataset in place.

## Choosing what a repo contributes

Open a repo in the list to see it as a generation does:

- **What the model sees**: the exact text of the overview call (description,
  language, topics, detected stack, README). Its hash decides whether the next
  run regenerates it.
- **README**: cleaned of badges and cut at 3,000 characters.
- **Docs**: the Markdown and text files under `docs/`. The default pick is the
  first 6 readable files; **Choose files** lets you tick up to 20, **None**
  leaves them out. Files over 50 KB are skipped, and each one is cut at 3,000
  characters.

Forks and archived repos are listed but can't be selected.

## Generating

**Generate draft** queues the recipe as it is at that moment; a worker runs
it, and the page follows its progress. The run is incremental: a source whose
text did not change since the published version keeps its pairs without a
model call. When it finishes, the page counts the new pairs, the ones kept,
those held out (an answer far from its source) and the published pairs the
draft would remove — a deselected source, a removed file. A repo that GitHub
fails to return keeps its published pairs, and the failure is listed with the
draft.

## Reviewing and publishing

**Review the draft** opens the run's review page, with three lists:

- **New**: the pairs generated this run, all included; untick one to leave it
  out.
- **Held out**: pairs whose answer is far from its source, left out; tick one
  to take it in.
- **Removed**: pairs of the published dataset this draft no longer has.
  Publishing deletes them.

Filters narrow the lists by category, repo, text, low grounding, or pairs
that fail your quality rules (Quality page). The page also lists possible
duplicates — same question, close answers — with a button to leave the second
one out. **Edit**
rewrites the question or answer of a pair that goes out; the rewritten pair
gets the id of its new content and loses its grounding score, computed for
the model's answer. Pairs carried over from the published version are not
shown and can't be edited here.

**Publish to Hugging Face** pushes exactly what you reviewed, in one commit
(data, held-out pairs, manifest and card), then opens the dataset page.

## API

| Route                                  | Returns                                                       |
| -------------------------------------- | ------------------------------------------------------------- |
| `GET /github/profile`                  | Your account and the API quota left                           |
| `GET /github/repos`                    | Your public repos, with whether a generation takes them       |
| `GET /github/repos/{owner}/{repo}`     | README, `docs/` files, detected stack and the overview text   |
| `GET /github/repos/{owner}/{repo}/doc` | One `docs/` file (`path`), cut where a generation cuts it     |
| `GET /recipes`, `POST /recipes`        | Your recipes; a new one                                       |
| `GET/PUT/DELETE /recipes/{recipe_id}`  | One recipe (another user's answers 404)                       |
| `POST /recipes/{recipe_id}/run`        | Queues a generation; follow it with `GET /jobs/runs/{run_id}` |
| `POST /jobs/runs/{run_id}/publish`     | Publishes the reviewed draft: `exclude`, `promote`, `edits`   |
| `GET /jobs/runs/{run_id}/checks`       | Near-duplicates and quality-rule failures of the draft        |

GitHub answers are cached 5 minutes per account. Errors: `400` without a GitHub
username in **Settings**, `404` outside your account, `429` when the GitHub
quota is exhausted.

See [Datasets on Hugging Face](./datasets.md) for what happens once a draft is
published.
