"""The generated documentation views as a static site (ADR 0117).

The pages are formatted from the same rows the generator writes the markdown views from
(`doc_scripts.generate_doc_indexes.generated_blocks`), so what a view says has one source. A page
is a function of the tree: it reads no history and no clock, so two builds of one commit are the
same bytes. Run `python -m doc_site --out DIR` from `tools/`.
"""
