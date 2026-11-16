# dataset-generator

Builds question/answer datasets from GitHub profiles, resumes, files and web pages, and keeps them as private dataset repos on the Hugging Face Hub.

## Language

### Datasets on the Hub

**Hub dataset repo**:
A private dataset repository on the Hugging Face Hub that holds one Q&A dataset: its pairs, the job's review list and manifest when a job made it, and its card.
_Avoid_: Hub dataset (alone), export, remote dataset

**Dataset version**:
The content of a Hub dataset repo at one commit; every read returns one and every publication creates the next.
_Avoid_: snapshot, revision, state

**Moved dataset**:
A Hub dataset repo whose latest commit is no longer the one a draft was built from, because something was published or edited in between.
_Avoid_: conflict, stale repo

**App card**:
A dataset card the app wrote, and may therefore replace on the next publication; any other card belongs to the dataset's owner and is left as it is.
_Avoid_: generated card, README

### Rows

**Own row**:
A row of a dataset that the Q&A job publishing it generated, recognised by a category that job uses.
_Avoid_: job pair, managed row

**Foreign row**:
A row of a dataset that the Q&A job publishing it did not generate, such as a pair added from a file; the job carries it through unchanged.
_Avoid_: external pair, unknown row
