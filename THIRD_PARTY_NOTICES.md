# Third-party notices

The Job Search Kit is MIT licensed (see LICENSE). The Windows installer bundles, and the kit uses, the following software. Each keeps its own license; copies of the license texts ship inside the installed packages (`python\Lib\site-packages\*.dist-info` and `python\LICENSE.txt`).

| Software | Used for | License |
|---|---|---|
| Python 3.12 (python-build-standalone distribution by Astral) | runs the kit | Python Software Foundation License 2.0; the build-standalone packaging is MIT and BSD-3 |
| requests, with certifi, charset-normalizer, idna, urllib3 | reading job boards and GitHub releases | Apache 2.0 (requests, requests' dependencies: MPL 2.0 for certifi, MIT for charset-normalizer and urllib3, BSD-3 for idna) |
| python-dotenv | reading optional tokens from `.env` | BSD-3 |
| python-docx, with lxml and typing-extensions | building Word resumes | MIT (python-docx), BSD-3 (lxml), PSF (typing-extensions) |
| pdfplumber, with pdfminer.six, pypdfium2, Pillow, cffi, pycparser, cryptography | counting rendered pages | MIT (pdfplumber, pdfminer.six), Apache 2.0 or BSD-3 (pypdfium2 and PDFium), MIT-CMU (Pillow), MIT (cffi), BSD-3 (pycparser), Apache 2.0 or BSD-3 (cryptography) |
| Inno Setup | builds the Windows installer; not installed on the user's computer | Inno Setup License (free for any use, including commercial) |
| LibreOffice | optional, installed separately by the user, used to render page counts | MPL 2.0 |

Job postings and company information shown by the kit belong to the boards and employers that published them; see SOURCES.md for how each source is read and credited.
