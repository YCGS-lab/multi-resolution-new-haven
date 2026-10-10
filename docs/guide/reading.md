# How to read these docs

## Three levels

1. **[Overview](/)**: the whole project on one page.
2. **Section overviews** (the "Overview" page of each sidebar section): how
   one major piece works, with diagrams, and which parts matter.
3. **Detail pages**: what specific code does and why, with the code shown.

Read down only as far as you need. Each level links to the next.

## Boilerplate vs. design decisions

Much of the code is standard practice. Some of it makes choices that a
reviewer should check, because another reasonable choice exists and this one
has consequences. Pages mark them with these boxes:

::: tip Standard practice
Code that follows a common, well-established pattern (a CLI entry point, a
retrying HTTP session, a Terraform S3 bucket). Skim it; it is described
briefly.
:::

::: warning Design decision
A choice specific to this project, with the reasoning for it and its
trade-offs. **These are the parts to review closely.**
:::

::: danger Workaround
Code that exists only to work around a bug or limitation in a library or
service. It may become unnecessary, or break, when that dependency changes.
:::

Section headings carry the same labels as badges, for scanning:
<Badge type="tip" text="standard" />, <Badge type="warning" text="decision" />
and <Badge type="danger" text="workaround" />.

## Code snippets

Code is shown straight from the source files, so it is always current. Each
snippet's tab shows the file and the *region* it comes from:

::: code-group
<<< @/../website/js/cog.js#clip [website/js/cog.js#clip]
:::

A region is a block of the source file between two marker comments, as in
VS Code's folding regions:

```js
// #region clip
...
// #endregion clip
```

The same markers in Python, Terraform and the justfile are `# region name`
and `# endregion name`; in CSS `/* #region name */`; in HTML
`<!-- #region name -->`. To find a snippet in the source, search the file for
`region <name>`. Snippets carry no line numbers, because they would restart
at 1 for every region.

`npm run check` (in `docs/`) checks that every snippet's region exists. It
also lists regions that no page uses. It runs before every `npm run build`.

The [comparison section](/comparison/) also shows **historical code**, the
renderer this project replaced. That code no longer exists in the source
files, so it is copied into the pages as plain code blocks. Each one is
labeled with the file it came from at commit `bd8e191`.

## Terms

Domain terms (COG, Web Mercator, shader, overview, ...) are explained where
they first appear and collected in the [glossary](/guide/glossary).

## Running the docs

```sh
cd docs
npm ci
npm run dev        # http://localhost:5173/
npm run build      # check snippets, then build to docs/.vitepress/dist/
```
