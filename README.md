# PageBurrow

## Online hosted preview

[Deploy the online version on Render](https://render.com/deploy?repo=https://github.com/shubhamskamboj/PageBurrow)

The repository includes a Docker-based web service configuration in `render.yaml`.
Sign in to Render, open the deploy link, select the Free instance, and deploy.
Render assigns an HTTPS address; that address opens the working PDF tool.
The website is **not live until the deployment succeeds**. GitHub stores the source;
the Python app runs on Render, not GitHub Pages.

The hosted preview uploads documents to the server. It separates visitors using
secure session cookies and temporary storage, supports 10 MB requests/uploads,
and deletes sessions after 30 minutes of inactivity (cleanup waits for any running
operation to finish). Restarting the service also removes all sessions. Download
results before leaving. There are four visitor slots and 40 MB of stored input
per session; generated output can temporarily exceed this amount. Requests run
one at a time. Large or complex PDFs can exceed the instance's memory or processing
time limits. This is a small demonstration service, not a high-traffic production
deployment; use non-sensitive sample documents during evaluation.

English/Hindi OCR and built-in Office converters are included. LibreOffice and a
headless browser are not installed in this container. HTML-to-PDF and adding OCR
languages are disabled online. Browser translation still depends on the visitor's
browser. The original local version retains these features and its offline behavior.

Free Render services sleep when idle and discard local files on restart. For
details, see [Render's free service limitations](https://render.com/docs/free).
Do not scale this preview across multiple instances: sessions are in memory.

For another container host, provide `PUBLIC_ORIGIN=https://your-domain.example`
and `PORT=10000`, with HTTPS terminated by the host's reverse proxy. On Render,
the application automatically uses `RENDER_EXTERNAL_URL`. For a custom domain,
set `PUBLIC_ORIGIN` to that domain's HTTPS URL.

## Local version

Every PDF tool in your browser, on your own device. Files are processed by a small program running on your computer (or Android phone). Nothing is uploaded to the internet, there is no account, and there are no file-count or size limits other than your device's memory.

- **Edit a PDF**: change existing text in its original font, size and color. Add text you can drag, resize and stretch. Erase text from scans while keeping the paper's background. Add images, links, highlights, rectangles, ellipses, lines and freehand drawing.
- **33 more tools** on the start screen: merge, split, compress, OCR, conversions to and from Word, PowerPoint, Excel, images, HTML and Markdown, page numbers, watermarks, forms, passwords, signatures, redaction, comparison and more. See [Tools](#tools).

`docs/ilovepdf-review.md` compares each tool with the iLovePDF website: its pros and cons, and how this tool addresses the cons.

## Start it

The packages for Windows, macOS and Linux include their own Python and PDF engine. **The person using them installs nothing and needs no internet.**

**To give PageBurrow to anyone, send `PageBurrow.zip`** (about 210 MB). It works on Windows, macOS and Linux, so you don't need to ask which computer they have. They unzip it and follow **START-HERE.txt**: on Windows they double-click **Start-Windows.cmd**, on a Mac **Start-macOS.command**, on Linux **start-linux.sh**. The packages below hold the same tool for one kind of computer, so they are smaller:

| Device | Package | Start |
| --- | --- | --- |
| Any computer: Windows, macOS or Linux | `PageBurrow.zip` | Unzip it (on Windows: right-click, **Extract All**), then double-click the Start file for that computer |
| Windows 10 / 11 | `PageBurrow-Windows.zip` | Right-click the zip, choose **Extract All**, then double-click **Start-Windows.cmd** in the extracted folder |
| macOS 11 or later (Apple silicon or Intel) | `PageBurrow-macOS.tar.gz` | Double-click the file to unpack it, then double-click **Start-macOS.command** |
| Linux (x86-64 or ARM64) | `PageBurrow-Linux.tar.gz` | Unpack it, then double-click **start-linux.sh** (choose *Run in Terminal* if asked) or run `sh start-linux.sh` |
| Android | `PageBurrow-Source.zip` + the Termux app | See [Android](#android-termux), or use phone access with no install at all |
| iPhone / iPad | none: just Safari | See [Phones and tablets](#phones-and-tablets-iphone-ipad-android) and **Start-iPhone-iPad.txt** |

The tool opens in the browser at **http://127.0.0.1:8765**. Keep its window open while you work. Close the window or press `Ctrl+C` to stop it. Download your PDFs before stopping, because open documents are kept only in memory.

**The first time on a Mac**: macOS blocks files from the internet that are not from the App Store. On macOS 14 or older, right-click **Start-macOS.command**, choose **Open**, then **Open**. On macOS 15 or newer, double-click it, close the message, then open **System Settings > Privacy & Security** and select **Open Anyway**. The launcher then allows the rest of the package's files, so this happens only once. Alternatively, open Terminal and run `sh ` followed by the path of `Start-macOS.command`.

**The first time on Windows**: if Windows asks whether to run a file downloaded from the internet, choose **Run** (or **More info > Run anyway**).

### Make the packages

On a computer with internet, run:

```sh
python make_release.py            # or on Windows: .venv\Scripts\python.exe make_release.py
```

It creates the five packages in `dist/`: `PageBurrow.zip` for any computer, and one smaller package for each system. Downloads are kept in `build/downloads`, so later builds are quick. `python make_release.py universal` builds only `PageBurrow.zip`, and `python make_release.py windows` only the Windows package. The macOS and Linux packages hold builds for both kinds of processor, and the launcher picks the right one.

### Without a package (Source zip, or this folder)

The launchers also work in this project folder and in the Source zip. There they use the Python installed on the computer (3.10 or newer) and download PyMuPDF and Pillow on the first start, which needs the internet once. Get Python from [python.org](https://www.python.org/downloads/). On Windows, tick *Add python.exe to PATH* during setup. On a Mac you can also use `brew install python`. On Linux, use your package manager, for example `sudo apt install python3 python3-venv`.

### Android (Termux)

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) or its [GitHub releases](https://github.com/termux/termux-app/releases). The Google Play version is outdated.
2. Unzip `PageBurrow-Source.zip` into your phone's **Download** folder.
3. In Termux, run `termux-setup-storage` once and allow access to files.
4. Run `sh ~/storage/downloads/PageBurrow/start-android-termux.sh`

The first start installs Python, PyMuPDF and Pillow from Termux's own packages. Then the tool opens in your browser. Termux keeps running in the background while you use the browser. Stop it in Termux with `Ctrl+C` (Termux's on-screen *CTRL* key, then *C*). With the free **Termux:Widget** app, you can add a *PageBurrow* shortcut to your home screen. The launcher creates that shortcut for you.

### Phones and tablets (iPhone, iPad, Android)

iOS does not allow the PDF engine to run on an iPhone or iPad. These devices use the tool running on another device on the same Wi-Fi. Android phones without Termux can do the same.

1. On the computer, start the **phone access** launcher: **Start-Windows-Phone-Access.cmd**, **Start-macOS-Phone-Access.command** or **start-linux-phone-access.sh**. On an Android phone, run `sh start-android-termux.sh --lan` instead.
2. The window, and the tool's start page on that computer, show an address like `http://192.168.1.23:8765` and a 6-digit PIN.
3. On the phone, open that address in Safari or Chrome and enter the PIN. The phone stays paired for 180 days. After 10 wrong PINs, pairing locks until the tool restarts.
4. Optional: add it to the home screen to open it from its own icon. On iPhone, tap **Share**, then **Add to Home Screen**. On Android, open Chrome's menu and choose **Add to Home screen**. The home-screen app asks for the PIN once more.

On Windows, allow Python on **private networks** if Windows Firewall asks. Files travel over your Wi-Fi unencrypted, so use phone access only on a network you trust, such as your home network. Without the phone access launcher, only the device running the tool can use it.

### Computers without internet

The Windows, macOS and Linux packages need no internet at all. For the Source zip or this folder, run `python prepare_offline.py` on a computer with internet. It downloads PyMuPDF and Pillow for Windows, macOS and Linux, for Python 3.10–3.14, into a `wheelhouse` folder (add `windows`, `macos` or `linux` to limit it). Copy the folder, including `wheelhouse`, to the offline computer.

### Start manually

```sh
python launch.py            # sets up on first run, then starts the tool
python launch.py --lan      # with phone access
python launch.py --system   # use PyMuPDF and Pillow already installed on this device
python app.py --help        # start the server directly: --port, --host, --no-browser
```

## Edit

- **Edit text**. Click a selectable line or text segment. Edit the text in the right panel, leave **Match original** selected and click **Apply**. The panel reports how the font was matched. A PDF line may contain several segments with different styles.
- **Add text**. Click or tap where the baseline should begin, type the text and select **Add text**. The text stays selected so you can adjust it, and you can click it again later with the Add text tool:
  - Drag the text with the mouse or a finger to move it. Arrow keys (Shift for 10 pt) or the **Move** buttons nudge it.
  - Drag a corner handle to make the font bigger or smaller. Drag a side handle to stretch or compress the letters. **Size** and **Width (%)** show the result and accept typed values.
  - Edit the text, font or color in the panel. The page previews changes as you type. Press **Delete** to remove the text, or **Esc** to cancel unsaved changes.
- **Eraser**. Drag over text to erase it. By default (**Erase text, keep the background**), only the ink is removed: the paper's color, shading, gradient and grain stay as they were, also on scanned pages. Pixels away from the letters are left untouched. If faint marks remain, select the area and raise **Erase strength**. If a background pattern changes, lower it. You can move or resize an erased area. Choose **Add text on this area** to start new text where the erased text was, at its size and in its ink color. The eraser works on dark text on lighter paper. It does not remove text you added; delete that instead.
- **Cover modes**. The Eraser can instead cover an area with the background color or with white. Click a cover to move or resize it, or to change its fill.
- Erased and covered content is hidden visually, but the original can still be recovered from the PDF.
- **Image, Link, Highlight, Rectangle, Ellipse and Line**. Drag a region on the page. The Image tool accepts PNG and JPEG.
- **Draw**. Draw freehand with the mouse, a pen or a finger. Choose the color and line width first.
- **Touch screens**. Moving, resizing and placing text work with touch. In Edit text and Add text, a finger drag on the page scrolls it. In the drawing tools it draws.
- **Undo and Redo** affect actions across pages.
- **Preview & download**. Shows the finished PDF, every page exactly as it will be saved, before you download it. Choose **Original** or **Side by side** to compare it with the PDF you opened, zoom in to check details, then select **Download PDF** (a separate `-edited.pdf` file), or **Back to editing** to fix something.

## Tools

Choose a tool on the start screen, or type in the search box. Add files by dragging them in or with **Choose files**. In Scan to PDF and JPG to PDF, a phone can also use **Take photos**. After a tool finishes, its result is shown in a **preview** before you download it, so you can check that it is right:

- Page through the result, jump with the thumbnails, and zoom in to check small text, signatures or image quality.
- **Original** and **Side by side** compare each page with the PDF it was made from (for tools that keep the pages, such as Watermark, Redact, Sign, Compress, Page numbers, Crop, OCR or Translate).
- When a tool makes several files (Split, PDF to JPG, …), choose which one to look at.
- Word, PowerPoint and Excel results are shown as pages (drawn by LibreOffice when it is installed, otherwise an approximate built-in preview). Markdown is shown as text.
- A result protected with a password is shown using the password you just set, which also confirms that it works.

Then download the result, or select **Continue with this PDF** to use it in another tool (or in the editor) without downloading it first. In the editor's **Compress** window, **Preview** shows the compressed PDF next to the uncompressed one.

| Group | Tools |
| --- | --- |
| Organize PDF | **Merge** (drag to set the order; each file's bookmarks are kept), **Split** (ranges, every N pages, extract pages, or by maximum file size), **Remove pages** and **Extract pages** (type page numbers or click thumbnails), **Organize** (drag thumbnails to reorder, rotate, delete, insert blank pages, combine pages from several PDFs), **Scan to PDF** (phone photos; drag the corners to straighten each page; color, grey, document or black-and-white) |
| Optimize PDF | **Compress** (see [Compress](#compress)), **Repair** (rescues readable pages and reports what was fixed or lost), **OCR** (makes scans searchable without changing how they look; turns sideways pages automatically), **PDF to PDF/A** |
| Convert to PDF | **JPG to PDF** (also PNG, GIF, BMP, TIFF, WEBP; JPEGs keep full quality), **Word**, **PowerPoint** and **Excel to PDF**, **HTML to PDF** (web address or .html file) |
| Convert from PDF | **PDF to JPG** (pages as JPG/PNG at 72–600 dpi, or the original embedded images), **PDF to Word**, **PDF to PowerPoint**, **PDF to Excel**, **PDF to Markdown**. Scanned pages are read with OCR. |
| Edit PDF | **Edit PDF** (the editor above), **Rotate**, **Page numbers** (positions, facing pages, formats such as "Page 1 of 9", any font on the computer including Hindi and other scripts), **Watermark** (text or image, any angle, 9 positions or tiled, opacity, above or below the content), **Crop** (automatic, drawn area or margins; optionally deletes what is outside), **PDF Forms** (fill, flatten, create fields by drawing them, or detect fields on a paper form) |
| PDF security | **Unlock**, **Protect** (AES-256, open and owner passwords, print/copy/edit permissions), **Sign** (draw, type or upload a signature; name, date and text; on chosen pages), **Redact** (words, or emails, phone numbers, card numbers, Aadhaar and PAN; drawn areas; preview the matches first; the content underneath is deleted, not just covered) |
| Smart tools | **Compare** (text and visual differences in a report PDF), **Summarize** (key sentences and terms), **Translate** (see below) |
| Workflows | Chain tools, for example *Merge → Page numbers → Compress*, and save the chain to reuse it |

### What some tools need

- **OCR languages.** English and Hindi are included. To add another language, open the OCR tool, open **Add a language**, choose it and select **Add** (1–15 MB, needs the internet once). After that it works offline. The languages are also used by the conversion tools and by Redact for scanned pages.
- **Word, PowerPoint and Excel to PDF.** A built-in converter handles .docx, .pptx, .xlsx, .txt and .csv with no install. It keeps text, styles, tables and images, but complex layouts are simplified. For exact layouts, and for older .doc, .ppt and .xls files, install the free [LibreOffice](https://www.libreoffice.org/); the tools use it automatically when it is installed.
- **HTML to PDF** uses Microsoft Edge, Google Chrome, Chromium or Brave if one is on the computer (Edge is part of Windows). Without one, it falls back to a basic layout without scripts and styles.
- **Translate** uses the translator built into Chrome or Edge 138 or newer, on desktop. The text stays on your device. The first time, the browser downloads the language, which needs the internet once. Other browsers show a clear message instead.
- **Summarize** picks the most important sentences of the document. It does not use an AI service, so it does not write new sentences.
- **PDF/A** creates the PDF/A-2b structure: embedded fonts, color profile and metadata. The result is not checked by a PDF/A validator, so for legal archiving, check it with one (for example veraPDF).
- **Sign** adds a visual signature. It cannot add a certificate-based digital signature or send signature requests to other people; those need a certificate authority or an online service.

## Compress

Choose **Compress PDF** on the start screen, or **Compress** while editing to compress the document with your edits. Set the maximum size, page size and mode, then select **Compress** and download the PDF.

- **Lossless** keeps decoded image pixels intact. It compresses PDF objects and tries a lossless predictor on compatible uncompressed and Flate-compressed scans. The resulting size depends on the contents and on how the PDF has already been compressed.
- **Allow JPEG compression** tries lossless first. If it needs more room, the tool tests JPEG quality settings from 60 to 95 for compatible opaque RGB and grayscale images. It keeps their original pixel dimensions and preserves vector text. PDFs with inline, masked or uncommon image types may shrink less. The highest quality that fits the target is used.
- **A4** fits the visible page proportionally within 210 × 297 mm (or landscape A4), centered with any needed margins. It keeps the original page orientation. If a file has links, bookmarks, annotations, form fields or unsupported page geometry and must be resized, use **Original page size**.
- **Maximum size** uses decimal MB (1 MB = 1,000,000 bytes). The tool checks the actual result before reporting a match. If it cannot reach the requested size, you can download the smallest result it found in your selected mode. The limit is 200 MB per PDF. Password-protected PDFs and PDFs with signature fields are declined.

Inspect the output before submitting or printing, especially small text, barcodes and scans from compressed originals.

## Limits

- An embedded font may be a subset that lacks the new characters or the Unicode mappings needed to render them. When that happens, install the original full font (TTF or OTF) and restart, or select a substitute in the panel. PDF standard fonts may render slightly differently across viewers.
- Direct replacement works on supported text segments in text-based PDFs. Scans, outlined letters, complex scripts, rotated text objects and some overlapping text may require another workflow. If the whole page was rotated via PDF page settings, text authored horizontally on the page can still be edited.
- Text replacements keep their original starting point and size. Longer lines can overlap nearby content. Pages do not reflow.
- The editor opens edit-enabled, password-protected PDFs when you enter the password. Editing a signed PDF can invalidate its signature.
- The editor's input limit is 160 MB. The other tools accept files up to 2 GB each, as far as the device's memory allows. Uploaded files, and the copies of results kept for their preview, are kept in a temporary folder while the tool runs and are deleted when you leave a tool or close a preview, after 6 hours, or when the tool stops.
- There is no batch find and replace and no certificate-based digital signing.

## PDF engine

The source is provided under the GNU Affero General Public License, version 3. See `COPYING`. The tool uses [PyMuPDF](https://pypi.org/project/PyMuPDF/) under its open-source AGPL terms or a commercial license obtained separately from Artifex, and [Pillow](https://pypi.org/project/pillow/) for images and compression. OCR uses the Tesseract engine built into PyMuPDF, with language data from [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) (Apache License 2.0) in the `tessdata` folder. The portable packages include Python from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) (Python Software Foundation License). Their `runtime` folders contain the license files of Python, PyMuPDF and Pillow.
