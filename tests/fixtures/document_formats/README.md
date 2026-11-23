# Document-format routing fixtures

`atom.xml` is explicitly synthetic. Its Atom envelope contains XHTML event links
and an iCalendar link so tests can prove that embedded HTML does not authorize
generic calendar discovery from an unsupported feed.

The same tests reuse these existing captures without copying or changing them:

- `sustainable_ow/feed.xml`: reduced public RSS with capture provenance in its
  existing manifest. Adding a standard XML declaration is a labeled test variant.
- `batch2/clear-lake.xml`: existing ChamberMaster/GrowthZone XML fixture.
- `registered_html_calendar/lansdowne/lansdowne-full-calendar.html`: captured
  publisher HTML; its existing manifest documents reductions and synthetic prose.
- `battersea_bloem/square-events.json`: captured Square event-product JSON envelope.

XHTML variants wrap unchanged calendar markup with an XML declaration and the
standard XHTML namespace. Custom-element and JSON-LD positive cases are synthetic
and use relative future dates so the regression does not expire.
