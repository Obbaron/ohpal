---
title: Create Excel from AMPM
section: Getting started
order: 40
keywords: excel, template, samples, workbook, exports, xlsx, create
---
# Create Excel from AMPM

Makes the samples-template workbook for one build, without opening the build.

1. On the File tab, choose **Create Excel from AMPM**.
2. Pick the build's folder.
3. The workbook is written to an `exports` folder inside the build, named
   after the build: `<build>/exports/<build name>.xlsx`. If one is already
   there you are asked before it is replaced.

What goes into it depends on what the folder contains:

| Found | Result |
| --- | --- |
| DHXML (with or without the parts CSV) | The full template: one row per part with its bounding box, plus laser parameters when the parts CSV is there. |
| Parts CSV only | A reduced template built from the CSV alone. The result message says so. |
| Neither | Nothing to build from. You are told which files are missing. |

This is different from **Export to Excel** on the Data tab, which writes the
data you are looking at. See [Exporting to Excel](help:export-excel).
