"""The console use-case demo: one deal, walked end to end through the real product.

Two entry points share everything in this package, which is the whole point of it being a
package rather than a script:

* ``scripts/credit_memo_console_walkthrough.py`` narrates each act to a presenter and
  waits for Enter before performing it.
* ``tests/browser/test_console_use_cases.py`` runs the same acts and asserts each one.

A demo nobody asserts rots quietly, and a suite nobody watches proves nothing to an
audience. Sharing :mod:`~scripts.demo_console.acts` between them means the walkthrough a
presenter shows is the walkthrough CI keeps working.

What a presenter says is an ordered list of short business points rather than a paragraph,
and :mod:`~scripts.demo_console.narrative` owns that format. The six-step server demo in
``scripts/credit_memo_demo_playwright.py`` renders through it too, so both demos read the
same way.
"""
