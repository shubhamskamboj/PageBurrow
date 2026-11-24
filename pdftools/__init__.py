"""All PDF tools of PageBurrow. Each runs on this device; nothing is uploaded anywhere."""
from . import convert_from, convert_to, edit, intelligence, optimize, organize, security  # noqa: F401 (register tools)
from . import browser, ocr
from .common import Input, Options, Result, ToolError, pdf_inputs
from .convert_to import libreoffice
from .registry import TOOLS, tool

# Tools that turn one PDF into one PDF, so they can follow each other in a workflow.
CHAINABLE = {"merge", "rotate", "page_numbers", "watermark", "compress", "protect", "unlock", "repair", "ocr", "crop",
             "redact", "remove_pages", "extract_pages", "pdfa"}


@tool("workflow")
def workflow(files, opt):
    steps = opt.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ToolError("Add at least one step to the workflow.")
    names = [str(s.get("tool")) if isinstance(s, dict) else "" for s in steps]
    for index, name in enumerate(names):
        if name not in CHAINABLE:
            raise ToolError(f"Step {index + 1} cannot be part of a workflow.")
        if name == "merge" and index:
            raise ToolError("Merge can only be the first step.")
        if name == "protect" and index != len(steps) - 1:
            raise ToolError("Protect must be the last step, because later steps would need the password.")
    extras = [f for f in files if f.suffix != ".pdf"]
    current = pdf_inputs(files)
    notes = []
    for index, (name, step) in enumerate(zip(names, steps), 1):
        options = Options(step.get("options") or {})
        if name == "merge":
            result = TOOLS["merge"](current, options)
            current = [Input(result.files[0][0], raw=result.files[0][1])]
            continue
        produced = []
        for item in current:
            try:
                result = TOOLS[name]([item] + extras, options)
            except ToolError as error:
                raise ToolError(f"Step {index} ({name.replace('_', ' ')}): {error}") from None
            if len(result.files) != 1:
                raise ToolError(f"Step {index} makes several files, so it can only be used on its own.")
            password = "" if name == "unlock" else item.password
            produced.append(Input(item.name, raw=result.files[0][1], password=password))
            notes += [n for n in result.notes if n not in notes]
        current = produced
    out = [(item.stem + "_processed.pdf", item.raw) for item in current]
    return Result(out, f"Ran {len(steps)} step(s) on {len(out)} file(s).", notes)


def run(name, files, options):
    if name not in TOOLS:
        raise ToolError("Unknown tool.")
    return TOOLS[name](files, Options(options))


def capabilities():
    return {"ocr_languages": [{"code": c, "name": ocr.NAMES.get(c, c)} for c in ocr.installed()],
            "ocr_available": [{"code": c, "name": n} for c, n in ocr.NAMES.items() if c not in ocr.installed()],
            "libreoffice": bool(libreoffice()), "browser": bool(browser.find()), "tools": sorted(TOOLS)}
