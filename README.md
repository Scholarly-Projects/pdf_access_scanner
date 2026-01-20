# pdf_access_scanner

A Python tool for batch surveying PDF files for missing alt text fields, title metadata, tagging structure and correctly ordered headers. The script was created so PDF files in University of Idaho's VERSO institutional repository can be more transparently assessed for what kind of remediation work needs to be done to meet WCAG 2.1 standards. Folders are surveyed using the PikePDF library and results are generated in a CSV which prints each filename alongside a pass or fail judgement for each of the above measures. While there are more complex qualifications involved in meeting WCAG 2.1, this tool provides a good starting point to understand a collection's accessibility benchmarks holistically, as opposed to approaching remediation linearly on a file by file basis. _Andrew Weymouth_, Winter 2025.

## About

This report evaluates PDF accessibility using only the document’s internal structure (tags and metadata), not visual analysis.

- “Contains images” checks whether the PDF includes tagged <Figure> elements in its structure tree.
    - Yes: tagged figures found
    - No: tagged structure exists but no figures
    - N/A: no tagging structure at all (so figures can’t be assessed)
- “Alt text” is only evaluated if figures are present (Yes).
    - Pass: all figures have alt text
    - Fail: at least one figure lacks alt text
    - N/A: when “Contains images” is N/A (untagged PDFs can’t provide semantic alt text)
- “Metadata” checks for required document info (e.g., title, author)  Pass or Fail
- “Tags” indicates whether the PDF has a proper structure tree  Pass or Fail
- “Header ordering” validates logical heading hierarchy (e.g., no H1  H3 jumps)—but only if tags exist.
    - Pass/Fail if tagged
    - N/A if untagged

*Overall*: “Pass” means the PDF meets that criterion; “Fail” means it doesn’t; “N/A” means the criterion can’t be assessed due to missing structure.