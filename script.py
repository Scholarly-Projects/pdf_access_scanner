import csv
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import argparse
import re

try:
    import pikepdf
except ImportError:
    print("Error: pikepdf is not installed. Please install it using: pip install pikepdf")
    sys.exit(1)


def extract_heading_levels_from_struct_tree(obj, pdf) -> list:
    """
    Recursively traverse the structure tree and collect heading levels in document order.
    This version is more robust against malformed structures.
    """
    levels = []
    if not obj or obj is None:
        return levels

    if isinstance(obj, pikepdf.Array):
        for item in obj:
            levels.extend(extract_heading_levels_from_struct_tree(item, pdf))
    elif isinstance(obj, pikepdf.Dictionary):
        role = obj.get("/S")
        if role and isinstance(role, pikepdf.Name):
            role_str = str(role).lstrip('/').upper()
            if role_str.startswith("H") and role_str[1:].isdigit():
                levels.append(int(role_str[1:]))
        
        # Recurse into children, checking both /K and /Kids
        for key in ["/K", "/Kids"]:
            if key in obj:
                levels.extend(extract_heading_levels_from_struct_tree(obj[key], pdf))
    return levels


def validate_heading_order(levels: list) -> bool:
    """
    Validate heading order: the sequence of heading levels must never increase by more than 1.
    """
    if not levels:
        return True  # No headings = trivially valid

    for i in range(1, len(levels)):
        prev = levels[i - 1]
        curr = levels[i]
        if curr > prev + 1:
            return False
    return True


def find_figures_and_check_alt(struct_elem, pdf) -> dict:
    """
    Recursively find Figure elements and check for alt text.
    Returns a dict: {'found_figures': bool, 'all_have_alt': bool}
    """
    status = {'found_figures': False, 'all_have_alt': True}
    if not struct_elem or struct_elem is None:
        return status

    if isinstance(struct_elem, pikepdf.Array):
        for item in struct_elem:
            item_status = find_figures_and_check_alt(item, pdf)
            status['found_figures'] = status['found_figures'] or item_status['found_figures']
            status['all_have_alt'] = status['all_have_alt'] and item_status['all_have_alt']

    elif isinstance(struct_elem, pikepdf.Dictionary):
        role = struct_elem.get("/S")
        if role and isinstance(role, pikepdf.Name):
            role_str = str(role).lstrip('/').upper()
            if role_str == "FIGURE":
                status['found_figures'] = True
                # Check for Alt text on the Figure element itself
                alt_text = struct_elem.get("/Alt")
                if not alt_text or not str(alt_text).strip():
                    status['all_have_alt'] = False
                    # We can stop early if we found a figure without alt text
                    return status
        
        # Recurse into children
        for key in ["/K", "/Kids"]:
            if key in struct_elem:
                item_status = find_figures_and_check_alt(struct_elem[key], pdf)
                status['found_figures'] = status['found_figures'] or item_status['found_figures']
                status['all_have_alt'] = status['all_have_alt'] and item_status['all_have_alt']
                if not status['all_have_alt']:
                    return status # Early exit
    return status


def assess_pdf_accessibility(pdf_path: str) -> dict:
    """
    Returns a dict with "Pass"/"Fail"/"N/A" for each criterion.
    """
    result = {
        "alt_text": "Fail",
        "metadata": "Fail",
        "tags": "Fail",
        "header_order": "N/A", # Default, will be updated
    }

    try:
        with pikepdf.open(pdf_path) as pdf:
            root = pdf.Root

            # --- Tags (D) ---
            is_tagged = "/StructTreeRoot" in root and isinstance(root["/StructTreeRoot"], pikepdf.Dictionary)
            result["tags"] = "Pass" if is_tagged else "Fail"

            # --- Metadata (C) - Specifically looking for a Title ---
            title_found = False
            # 1. Check DocInfo first
            if pdf.docinfo and '/Title' in pdf.docinfo and pdf.docinfo.get('/Title'):
                title_found = True
            # 2. If not in DocInfo, check XMP metadata
            if not title_found and "/Metadata" in root:
                try:
                    xmp_data = root["/Metadata"].read_bytes()
                    xmp_str = xmp_data.decode('utf-8', errors='ignore')
                    # Simple regex search for dc:title
                    if re.search(r'<dc:title[^>]*>.*?</dc:title>', xmp_str, re.DOTALL | re.IGNORECASE):
                        title_found = True
                except Exception:
                    pass # Ignore XMP parsing errors
            result["metadata"] = "Pass" if title_found else "Fail"

            # --- Alt Text (B) - Simplified to Pass/Fail ---
            if is_tagged:
                struct_root = root["/StructTreeRoot"]
                figure_status = find_figures_and_check_alt(struct_root, pdf)
                # If no figures were found, or all figures had alt text, it's a pass.
                result["alt_text"] = "Pass" if (not figure_status['found_figures'] or figure_status['all_have_alt']) else "Fail"
            else:
                # Untagged PDFs cannot have proper, semantic alt text
                result["alt_text"] = "Fail"

            # --- Header Ordering (E) - Conditional logic ---
            if is_tagged:
                try:
                    struct_root = root["/StructTreeRoot"]
                    heading_levels = extract_heading_levels_from_struct_tree(struct_root, pdf)
                    is_valid = validate_heading_order(heading_levels)
                    result["header_order"] = "Pass" if is_valid else "Fail"
                except Exception as e:
                    print(f"  Warning: Could not parse headings for {pdf_path}: {e}")
                    result["header_order"] = "Fail" # Treat parsing errors as a failure
            else:
                # Per the requirement, if tags are "Fail", header ordering is "N/A"
                result["header_order"] = "N/A"

    except Exception as e:
        print(f"Warning: Could not analyze {pdf_path}: {e}")

    return result


def scan_pdfs(root_folder: str) -> List[Tuple[str, dict]]:
    results = []
    root_path = Path(root_folder)

    if not root_path.exists():
        print(f"Error: Folder '{root_folder}' does not exist.")
        return results

    # Get all PDF files and sort them alphabetically before processing
    pdf_files = sorted(list(root_path.rglob("*.pdf")))

    for pdf_file in pdf_files:
        print(f"  Analyzing: {pdf_file.relative_to(root_path)}")
        result = assess_pdf_accessibility(str(pdf_file))
        results.append((str(pdf_file.relative_to(root_path)), result))

    return results


def create_csv_report(results: List[Tuple[str, dict]], folder_path: str) -> str:
    output_dir = Path(__file__).parent / "A"
    output_dir.mkdir(exist_ok=True)

    clean_name = re.sub(r'[\\/*?:"<>|]', ".", folder_path.strip('/\\'))
    csv_path = output_dir / f"{clean_name}.csv"

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # REVISED: Updated headers to be lowercase as requested
        writer.writerow([
            "Filename",
            "alt text",
            "metadata",
            "tags",
            "header ordering"
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
    parser = argparse.ArgumentParser(description="Assess PDFs for WCAG 2.1 accessibility criteria (Revised Output).")
    parser.add_argument("folder_path", help="Path to folder containing PDFs")
    args = parser.parse_args()

    print(f"Scanning: {args.folder_path}")
    print("Checking: Alt Text (in Figures), Metadata (Title), Tagging, and (if tagged) Heading order")
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