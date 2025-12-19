import csv
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import argparse

try:
    import pikepdf
except ImportError:
    print("Error: pikepdf is not installed. Please install it using: pip install pikepdf")
    sys.exit(1)


def extract_heading_levels_from_struct_tree(obj, pdf) -> list:
    """
    Recursively traverse the structure tree and collect heading levels in document order.
    Returns a list like [1, 2, 3, 2, 1, 2, ...]
    """
    levels = []
    if isinstance(obj, pikepdf.Array):
        for item in obj:
            levels.extend(extract_heading_levels_from_struct_tree(item, pdf))
    elif isinstance(obj, pikepdf.Dictionary):
        # Resolve indirect objects
        obj = obj.unparse() if hasattr(obj, 'unparse') else obj
        # Check role map
        role = obj.get("/S")
        if role and isinstance(role, pikepdf.Name):
            role_str = str(role)[1:]  # remove leading /
            if role_str in ("H1", "H2", "H3", "H4", "H5", "H6"):
                level = int(role_str[1])
                levels.append(level)
        # Recurse into children (K or Kids)
        if "/K" in obj:
            levels.extend(extract_heading_levels_from_struct_tree(obj["/K"], pdf))
        elif "/Kids" in obj:
            levels.extend(extract_heading_levels_from_struct_tree(obj["/Kids"], pdf))
    return levels


def validate_heading_order(levels: list) -> bool:
    """
    Validate heading order: no skipping (e.g., H1 → H3), and no invalid backtracking.
    Rules:
      - Must start with H1 or H2 (H2 allowed if document doesn't use H1)
      - Cannot jump more than one level down (H1 → H3 = invalid)
      - Can jump back up arbitrarily (H3 → H1 = OK if new section)
    But note: PDF structure doesn't encode "section resets", so we use a conservative model:
      - Track current "permitted max next level"
      - After H1, next heading must be H1 or H2 (not H3+)
    However, full outline validation is complex.

    Simplified rule (matches PAC & Adobe):
      - The sequence of heading levels must never increase by more than 1.
      - Going from level N to M is OK if M <= N+1.
    """
    if not levels:
        return True  # No headings = trivially valid

    for i in range(1, len(levels)):
        prev = levels[i - 1]
        curr = levels[i]
        if curr > prev + 1:
            return False
    return True


def assess_pdf_accessibility(pdf_path: str) -> dict:
    """
    Returns a dict with "Pass"/"Fail"/"N/A" for each criterion.
    """
    result = {
        "alt_text": "Fail",
        "metadata": "Fail",
        "tags": "Fail",
        "header_order": "N/A",  # will update if tagged
    }

    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root

            # --- Tags (D) ---
            is_tagged = "/StructTreeRoot" in root
            result["tags"] = "Pass" if is_tagged else "FAIL"

            # --- Metadata (C) ---
            has_xmp = "/Metadata" in root
            has_docinfo = any(key in pdf.docinfo for key in ['/Title', '/Author', '/Subject', '/Creator'])
            result["metadata"] = "Pass" if (has_xmp or has_docinfo) else "Fail"

            # --- Alt Text (B) ---
            # Only meaningful in tagged PDFs; check for /Alt in image XObjects
            def has_alt_in_obj(obj):
                if isinstance(obj, pikepdf.Dictionary) and "/Alt" in obj:
                    alt_val = obj["/Alt"]
                    if isinstance(alt_val, (str, pikepdf.String)):
                        return len(str(alt_val).strip()) > 0
                if isinstance(obj, pikepdf.Array):
                    return any(has_alt_in_obj(item) for item in obj)
                return False

            found_alt = False
            if is_tagged:  # Only check if tagged (alt text requires tagging to be effective)
                for page in pdf.pages:
                    if "/Resources" in page:
                        res = page["/Resources"]
                        if "/XObject" in res:
                            xobjs = res["/XObject"]
                            if isinstance(xobjs, pikepdf.Dictionary):
                                for name, stream in xobjs.items():
                                    if (isinstance(stream, pikepdf.Stream) and
                                        stream.get("/Subtype") == "/Image"):
                                        if has_alt_in_obj(stream):
                                            found_alt = True
                                            break
                                if found_alt:
                                    break
                result["alt_text"] = "Pass" if found_alt else "Fail"
            else:
                # Untagged: alt text not usable → Fail
                result["alt_text"] = "Fail"

            # --- Header Ordering (E) ---
            if is_tagged:
                try:
                    struct_root = root["/StructTreeRoot"]
                    heading_levels = extract_heading_levels_from_struct_tree(struct_root, pdf)
                    is_valid = validate_heading_order(heading_levels)
                    result["header_order"] = "Pass" if is_valid else "Fail"
                except Exception as e:
                    # Parsing failed → conservatively mark as Fail
                    result["header_order"] = "Fail"
            else:
                result["header_order"] = "N/A"

    except Exception as e:
        print(f"Warning: Could not analyze {pdf_path}: {e}")
        # Keep defaults (all Fail / N/A)

    return result


def scan_pdfs(root_folder: str) -> List[Tuple[str, dict]]:
    flagged = []
    root_path = Path(root_folder)

    if not root_path.exists():
        print(f"Error: Folder '{root_folder}' does not exist.")
        return flagged

    def process_pdf(pdf_file: Path):
        print(f"  Analyzing: {pdf_file.name}")
        result = assess_pdf_accessibility(str(pdf_file))
        # Include all PDFs (even if all Pass) for transparency
        try:
            rel_name = str(pdf_file.relative_to(root_path.parent))
        except ValueError:
            rel_name = str(pdf_file)
        flagged.append((rel_name, result))

    for item in root_path.iterdir():
        if item.is_file() and item.suffix.lower() == '.pdf':
            process_pdf(item)
        elif item.is_dir():
            for subitem in item.iterdir():
                if subitem.is_file() and subitem.suffix.lower() == '.pdf':
                    process_pdf(subitem)

    return flagged


def create_csv_report(results: List[Tuple[str, dict]], folder_path: str) -> str:
    output_dir = Path(__file__).parent / "A"
    output_dir.mkdir(exist_ok=True)

    clean_name = (
        folder_path
        .lstrip('/').lstrip('\\')
        .replace(':', '').replace('/', '.').replace('\\', '.')
    )
    csv_path = output_dir / f"{clean_name}.csv"

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Filename",
            "Alt text?",
            "Metadata?",
            "Tags?",
            "Header ordering?"
        ])
        for filename, r in results:
            writer.writerow([
                filename,
                r["alt_text"],
                r["metadata"],
                r["tags"],
                r["header_order"]
            ])

    return str(csv_path)


def main():
    parser = argparse.ArgumentParser(description="Assess PDFs for WCAG 2.1 accessibility criteria.")
    parser.add_argument("folder_path", help="Path to folder containing PDFs")
    args = parser.parse_args()

    print(f"Scanning: {args.folder_path}")
    print("Checking: Alt text, Metadata, Tagging, and (if tagged) Heading order")
    print()

    results = scan_pdfs(args.folder_path)

    if not results:
        print("No PDF files found.")
        return

    csv_path = create_csv_report(results, args.folder_path)

    print(f"\nAnalyzed {len(results)} PDF(s).")
    print(f"Report saved to: {csv_path}")


if __name__ == "__main__":
    main()