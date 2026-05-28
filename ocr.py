#!/usr/bin/env python3
"""
Google Cloud Document AI — PDF OCR Tool

Extracts text from scanned PDF books using Google's Document AI OCR.
Outputs both .txt (plain text) and .md (Markdown) files.

Usage:
    python ocr.py --setup                    First-time configuration
    python ocr.py "path/to/book.pdf"         Process a single PDF
    python ocr.py --dir ~/Desktop/scans/     Process all PDFs in a folder
    python ocr.py --all                      Process all PDFs in lit/
    python ocr.py --cleanup                  Remove temp files and GCS objects
    python ocr.py --resume                   Resume interrupted processing
"""

import argparse
import json
import logging
import math
import os
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

# Suppress noisy pypdf warnings about malformed PDF internal references
logging.getLogger("pypdf").setLevel(logging.ERROR)


# ============================================================
# Constants
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
MANIFEST_FILE = SCRIPT_DIR / "manifest.json"
CHUNKS_DIR = SCRIPT_DIR / "chunks"
OUTPUT_TXT_DIR = SCRIPT_DIR / "output" / "txt"
OUTPUT_MD_DIR = SCRIPT_DIR / "output" / "md"
DEFAULT_INPUT_DIR = SCRIPT_DIR / "lit"

DEFAULT_MAX_PAGES_PER_CHUNK = 200
DEFAULT_MAX_PAGES_PER_BATCH = 5000
DEFAULT_MAX_CONCURRENT_BATCHES = 5

TOTAL_STAGES = 6


# ============================================================
# Utilities
# ============================================================

def print_header(text):
    """Print a prominent header."""
    width = 54
    print(f"\n{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}\n")


def print_stage(num, emoji, text):
    """Print a stage header."""
    print(f"\n[{num}/{TOTAL_STAGES}] {emoji}  {text}")


def load_config():
    """Load config.json or exit with a helpful message."""
    if not CONFIG_FILE.exists():
        print("❌ config.json not found.")
        print("   Run 'python ocr.py --setup' first.")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_manifest(data):
    """Save processing manifest for resume support."""
    with open(MANIFEST_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def load_manifest():
    """Load existing manifest if available."""
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return None


# ============================================================
# Setup (--setup)
# ============================================================

def run_setup():
    """Interactive first-time configuration."""
    print_header("📋 Google Cloud Document AI — Setup")

    # Check for Homebrew
    if not shutil.which("brew"):
        print("⚠️ Homebrew is not installed on this Mac.")
        print("  Homebrew is required to install the Google Cloud CLI (google-cloud-sdk).")
        print("  To install it, run this command in your terminal:")
        print("  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        print("  Please install Homebrew and run this setup again.\n")
        sys.exit(1)

    # Check for existing config
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            existing = json.load(f)
        print("Existing configuration found:")
        print(f"  Project ID:    {existing.get('project_id', '?')}")
        print(f"  Processor ID:  {existing.get('processor_id', '?')}")
        print(f"  Bucket:        {existing.get('bucket_name', '?')}")
        resp = input("\nOverwrite? [y/N]: ").strip().lower()
        if resp != "y":
            print("Setup cancelled.")
            return

    print("Enter the values you noted during Google Cloud Console setup.\n")

    project_id = input("  GCP Project ID: ").strip()
    if not project_id:
        print("❌ Project ID cannot be empty.")
        return

    processor_id = input("  Document AI Processor ID: ").strip()
    if not processor_id:
        print("❌ Processor ID cannot be empty.")
        return

    bucket_name = input("  GCS Bucket name (without gs://): ").strip()
    if not bucket_name:
        print("❌ Bucket name cannot be empty.")
        return

    location = input("  Processor region [us]: ").strip() or "us"

    config = {
        "project_id": project_id,
        "location": location,
        "processor_id": processor_id,
        "bucket_name": bucket_name,
        "max_pages_per_chunk": DEFAULT_MAX_PAGES_PER_CHUNK,
        "max_pages_per_batch": DEFAULT_MAX_PAGES_PER_BATCH,
        "max_concurrent_batches": DEFAULT_MAX_CONCURRENT_BATCHES,
    }

    # ── Test connections ──
    print("\n🔍 Testing connections...\n")

    # Test GCS
    try:
        from google.cloud import storage as gcs

        storage_client = gcs.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            print(f"  ❌ Bucket '{bucket_name}' not found.")
            print("     Create it in Google Cloud Console → Cloud Storage → Create Bucket")
            return
        print(f"  ✅ GCS bucket '{bucket_name}' is accessible")
    except Exception as e:
        print(f"  ❌ GCS connection failed: {e}")
        print("     Make sure you have run:")
        print("       gcloud auth application-default login")
        return

    # Test Document AI
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai_v1 as documentai

        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)
        processor_name = docai_client.processor_path(project_id, location, processor_id)
        processor = docai_client.get_processor(name=processor_name)
        print(f"  ✅ Document AI processor '{processor.display_name}' is accessible")
    except Exception as e:
        print(f"  ❌ Document AI connection failed: {e}")
        print("     Check your Processor ID and make sure the Document AI API is enabled.")
        return

    # Save config
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n{'─' * 54}")
    print(f"  ✅ Setup complete! Configuration saved to config.json")
    print(f"  You can now run:  python ocr.py \"path/to/book.pdf\"")
    print(f"{'─' * 54}\n")


# ============================================================
# Stage 1: Analyze PDFs
# ============================================================

def analyze_pdfs(pdf_paths, max_pages_per_chunk):
    """Scan PDFs and gather metadata."""
    from pypdf import PdfReader

    books = []
    total_pages = 0

    for pdf_path in sorted(pdf_paths):
        path = Path(pdf_path)
        try:
            reader = PdfReader(str(path))
            pages = len(reader.pages)
            size_bytes = path.stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            chunks_needed = math.ceil(pages / max_pages_per_chunk)

            books.append({
                "name": path.stem,
                "path": str(path.resolve()),
                "filename": path.name,
                "pages": pages,
                "size_bytes": size_bytes,
                "size_mb": round(size_mb, 1),
                "chunks_needed": chunks_needed,
                "chunks": [],
            })
            total_pages += pages
        except Exception as e:
            print(f"      ⚠️  Skipping {path.name}: {e}")

    return books, total_pages


def print_analysis_table(books, total_pages):
    """Print a formatted table of PDF analysis results."""
    max_name_len = max((len(b["filename"]) for b in books), default=4)
    max_name_len = min(max_name_len, 55)  # cap width

    sep = f"      {'─' * max_name_len}  {'─' * 7}  {'─' * 8}  {'─' * 6}"
    hdr = f"      {'File':<{max_name_len}}  {'Pages':>7}  {'Size':>8}  {'Chunks':>6}"

    print(sep)
    print(hdr)
    print(sep)
    for b in books:
        name = b["filename"]
        if len(name) > max_name_len:
            name = name[: max_name_len - 3] + "..."
        size_str = f"{b['size_mb']:.0f} MB"
        print(f"      {name:<{max_name_len}}  {b['pages']:>7}  {size_str:>8}  {b['chunks_needed']:>6}")
    print(sep)

    # Cost estimate
    free_pages = min(total_pages, 1000)
    billable = max(0, total_pages - 1000)
    cost = billable / 1000 * 1.50

    print(f"\n      📊 Total: {len(books)} files, {total_pages:,} pages")
    print(f"      💰 Estimated cost: ${cost:.2f} (first 1,000 pages/month are free)")


# ============================================================
# Stage 2: Split PDFs
# ============================================================

def split_pdfs(books, max_pages_per_chunk):
    """Split large PDFs into chunks of max_pages_per_chunk pages."""
    from pypdf import PdfReader, PdfWriter

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    total_chunks = 0
    split_count = 0

    for book in books:
        if book["pages"] <= max_pages_per_chunk:
            # No splitting needed
            book["chunks"] = [
                {
                    "chunk_path": book["path"],
                    "chunk_filename": book["filename"],
                    "start_page": 0,
                    "end_page": book["pages"] - 1,
                    "page_count": book["pages"],
                    "is_original": True,
                }
            ]
            total_chunks += 1
            continue

        # Need to split
        split_count += 1
        reader = PdfReader(book["path"])
        chunk_num = 0

        for start in range(0, book["pages"], max_pages_per_chunk):
            end = min(start + max_pages_per_chunk, book["pages"])
            chunk_num += 1

            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])

            chunk_filename = f"{book['name']}_part{chunk_num:03d}.pdf"
            chunk_path = CHUNKS_DIR / chunk_filename

            with open(chunk_path, "wb") as f:
                writer.write(f)

            chunk_size_mb = chunk_path.stat().st_size / (1024 * 1024)

            book["chunks"].append(
                {
                    "chunk_path": str(chunk_path),
                    "chunk_filename": chunk_filename,
                    "start_page": start,
                    "end_page": end - 1,
                    "page_count": end - start,
                    "is_original": False,
                }
            )
            total_chunks += 1

        print(
            f"      ✂️  {book['filename']} → {chunk_num} chunks "
            f"({book['pages']} pages)"
        )

    if split_count == 0:
        print("      ℹ️  No PDFs need splitting (all ≤200 pages)")

    return total_chunks


# ============================================================
# Stage 3: Upload to GCS
# ============================================================

def upload_to_gcs(books, config):
    """Upload PDF chunks to Google Cloud Storage."""
    from google.cloud import storage as gcs

    client = gcs.Client(project=config["project_id"])
    bucket = client.bucket(config["bucket_name"])

    # Collect all chunks
    all_chunks = []
    for book in books:
        all_chunks.extend(book["chunks"])

    total = len(all_chunks)
    uploaded = 0
    skipped = 0
    total_bytes = 0

    for chunk in all_chunks:
        blob_name = f"input/{chunk['chunk_filename']}"
        blob = bucket.blob(blob_name)
        chunk["gcs_uri"] = f"gs://{config['bucket_name']}/{blob_name}"

        # Skip if already uploaded (resume support)
        if blob.exists():
            skipped += 1
            uploaded += 1
            continue

        file_path = chunk["chunk_path"]
        file_size = os.path.getsize(file_path)
        total_bytes += file_size

        blob.upload_from_filename(file_path)
        uploaded += 1

        size_mb = file_size / (1024 * 1024)
        print(
            f"      ☁️  [{uploaded}/{total}] {chunk['chunk_filename']} "
            f"({size_mb:.0f} MB)"
        )

    if skipped > 0:
        print(f"      ⏭️  {skipped} files already uploaded (skipped)")

    total_mb = total_bytes / (1024 * 1024)
    print(f"      ✅ {uploaded} files ready in GCS ({total_mb:.0f} MB uploaded)")


# ============================================================
# Stage 4: Process with Document AI
# ============================================================

def process_with_docai(books, config):
    """Submit batch OCR jobs to Document AI."""
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai_v1 as documentai

    location = config["location"]
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)

    processor_name = client.processor_path(
        config["project_id"], location, config["processor_id"]
    )

    # Collect all chunks
    all_chunks = []
    for book in books:
        for chunk in book["chunks"]:
            all_chunks.append(chunk)

    # Group into batches respecting page limit
    max_pages_per_batch = config.get(
        "max_pages_per_batch", DEFAULT_MAX_PAGES_PER_BATCH
    )
    batches = []
    current_batch = []
    current_pages = 0

    for chunk in all_chunks:
        if current_pages + chunk["page_count"] > max_pages_per_batch and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_pages = 0
        current_batch.append(chunk)
        current_pages += chunk["page_count"]

    if current_batch:
        batches.append(current_batch)

    total_batches = len(batches)
    print(f"      Submitting {total_batches} batch(es)...\n")

    # Submit batches
    operations = []
    for i, batch in enumerate(batches):
        batch_pages = sum(c["page_count"] for c in batch)
        output_uri = f"gs://{config['bucket_name']}/output/batch_{i + 1}/"

        gcs_documents = documentai.GcsDocuments(
            documents=[
                documentai.GcsDocument(
                    gcs_uri=chunk["gcs_uri"],
                    mime_type="application/pdf",
                )
                for chunk in batch
            ]
        )

        request = documentai.BatchProcessRequest(
            name=processor_name,
            input_documents=documentai.BatchDocumentsInputConfig(
                gcs_documents=gcs_documents
            ),
            document_output_config=documentai.DocumentOutputConfig(
                gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                    gcs_uri=output_uri,
                )
            ),
        )

        operation = client.batch_process_documents(request=request)
        operations.append((i + 1, operation, output_uri, batch))
        print(
            f"      📤 Batch {i + 1}/{total_batches}: "
            f"{len(batch)} documents, {batch_pages:,} pages"
        )

    # Wait for all operations to complete
    print(f"\n      ⏳ Processing... (this may take 10-60 minutes for large batches)")

    for batch_num, operation, output_uri, batch in operations:
        try:
            start_time = time.time()

            # Poll with status updates
            while not operation.done():
                elapsed = int(time.time() - start_time)
                mins, secs = divmod(elapsed, 60)
                print(
                    f"      ⏳ Batch {batch_num}: processing... ({mins}m {secs}s elapsed)",
                    end="\r",
                )
                time.sleep(15)

            # Force get result to raise any errors
            operation.result()

            elapsed = int(time.time() - start_time)
            mins, secs = divmod(elapsed, 60)
            print(
                f"      ✅ Batch {batch_num} complete ({mins}m {secs}s)                    "
            )

            # Extract per-document output locations from metadata
            metadata = documentai.BatchProcessMetadata(operation.metadata)
            for status in metadata.individual_process_statuses:
                for chunk in batch:
                    if chunk["gcs_uri"] == status.input_gcs_source:
                        chunk["result_gcs_prefix"] = status.output_gcs_destination
                        break

        except Exception as e:
            print(f"      ❌ Batch {batch_num} failed: {e}")
            for chunk in batch:
                if "result_gcs_prefix" not in chunk:
                    chunk["result_gcs_prefix"] = None
                    chunk["error"] = str(e)


# ============================================================
# Stage 5: Download & Parse Results
# ============================================================

def download_results(books, config):
    """Download and parse OCR results from GCS."""
    from google.cloud import documentai_v1 as documentai
    from google.cloud import storage as gcs

    storage_client = gcs.Client(project=config["project_id"])
    bucket = storage_client.bucket(config["bucket_name"])

    total_chunks = sum(len(b["chunks"]) for b in books)
    processed = 0

    for book in books:
        for chunk in book["chunks"]:
            processed += 1
            result_prefix = chunk.get("result_gcs_prefix")

            if not result_prefix:
                print(
                    f"      ⚠️  [{processed}/{total_chunks}] "
                    f"No results for {chunk['chunk_filename']}"
                )
                chunk["text"] = ""
                continue

            # Strip gs://bucket/ prefix to get blob prefix
            prefix = result_prefix.replace(f"gs://{config['bucket_name']}/", "")
            if not prefix.endswith("/"):
                prefix += "/"

            # List all output JSON files for this chunk
            blobs = list(bucket.list_blobs(prefix=prefix))
            json_blobs = [b for b in blobs if b.name.endswith(".json")]

            if not json_blobs:
                print(
                    f"      ⚠️  [{processed}/{total_chunks}] "
                    f"No JSON output found for {chunk['chunk_filename']}"
                )
                chunk["text"] = ""
                continue

            # Parse and concatenate text from all shards (sorted by name)
            chunk_text_parts = []
            for blob in sorted(json_blobs, key=lambda b: b.name):
                try:
                    json_content = blob.download_as_text()
                    document = documentai.Document.from_json(json_content)
                    if document.text:
                        chunk_text_parts.append(document.text)
                except Exception as e:
                    print(f"      ⚠️  Error parsing {blob.name}: {e}")

            chunk["text"] = "\n".join(chunk_text_parts)
            char_count = len(chunk["text"])
            print(
                f"      📥 [{processed}/{total_chunks}] "
                f"{chunk['chunk_filename']}: {char_count:,} chars"
            )


# ============================================================
# Stage 6: Save Output Files
# ============================================================

def save_output(books):
    """Save extracted text as .txt and .md files."""
    OUTPUT_TXT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD_DIR.mkdir(parents=True, exist_ok=True)

    for book in books:
        # Sort chunks by start page to ensure correct order
        sorted_chunks = sorted(book["chunks"], key=lambda c: c["start_page"])

        # ── Plain text (.txt) ──
        txt_parts = []
        for chunk in sorted_chunks:
            text = chunk.get("text", "")
            if text:
                txt_parts.append(text.strip())

        full_text = "\n\n".join(txt_parts)

        txt_path = OUTPUT_TXT_DIR / f"{book['name']}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        # ── Markdown (.md) ──
        md_path = OUTPUT_MD_DIR / f"{book['name']}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {book['name']}\n\n")
            f.write(f"*Source: {book['filename']}*  \n")
            f.write(f"*Pages: {book['pages']}*\n\n")
            f.write("---\n\n")

            for chunk in sorted_chunks:
                text = chunk.get("text", "")
                if text:
                    if len(sorted_chunks) > 1:
                        f.write(
                            f"\n<!-- Pages {chunk['start_page'] + 1}"
                            f"–{chunk['end_page'] + 1} -->\n\n"
                        )
                    f.write(text.strip())
                    f.write("\n")

        # Print status
        chunk_info = ""
        if len(book["chunks"]) > 1:
            chunk_info = f", merged from {len(book['chunks'])} chunks"
        print(
            f"      ✅ {book['name']}.txt + .md "
            f"({book['pages']} pages{chunk_info})"
        )


# ============================================================
# Cleanup (--cleanup)
# ============================================================

def run_cleanup():
    """Remove temporary files and GCS objects."""
    config = load_config()
    print_header("🗑️  Cleanup")

    # Clean local chunks
    if CHUNKS_DIR.exists():
        file_count = len(list(CHUNKS_DIR.glob("*.pdf")))
        shutil.rmtree(CHUNKS_DIR)
        print(f"  ✅ Removed chunks/ directory ({file_count} files)")
    else:
        print("  ℹ️  No chunks/ directory to clean")

    # Clean manifest
    if MANIFEST_FILE.exists():
        MANIFEST_FILE.unlink()
        print("  ✅ Removed manifest.json")

    # Clean GCS
    try:
        from google.cloud import storage as gcs

        client = gcs.Client(project=config["project_id"])
        bucket = client.bucket(config["bucket_name"])

        # Delete input files
        input_blobs = list(bucket.list_blobs(prefix="input/"))
        for blob in input_blobs:
            blob.delete()
        if input_blobs:
            print(
                f"  ✅ Removed {len(input_blobs)} files from "
                f"gs://{config['bucket_name']}/input/"
            )

        # Delete output files
        output_blobs = list(bucket.list_blobs(prefix="output/"))
        for blob in output_blobs:
            blob.delete()
        if output_blobs:
            print(
                f"  ✅ Removed {len(output_blobs)} files from "
                f"gs://{config['bucket_name']}/output/"
            )

        if not input_blobs and not output_blobs:
            print("  ℹ️  GCS bucket already clean")

    except Exception as e:
        print(f"  ⚠️  Could not clean GCS: {e}")

    print("\n  ✅ Cleanup complete!")
    print("  ℹ️  Output files in output/ were preserved.\n")


# ============================================================
# Resume Support
# ============================================================

def resume_processing(config):
    """Resume an interrupted processing run."""
    manifest = load_manifest()
    if not manifest:
        print("❌ No manifest.json found. Nothing to resume.")
        print("   Start a new run with: python ocr.py --all")
        sys.exit(1)

    stage = manifest.get("stage", "unknown")
    books = manifest.get("books", [])

    if not books:
        print("❌ Manifest contains no book data.")
        sys.exit(1)

    print_header("📄 Google Cloud Document AI — Resuming")
    print(f"  Resuming from stage: {stage}")
    print(f"  Books: {len(books)}")

    total_pages = sum(b["pages"] for b in books)

    stages_order = ["upload", "process", "download", "save"]
    if stage not in stages_order:
        print(f"❌ Unknown stage '{stage}' in manifest.")
        sys.exit(1)

    start_idx = stages_order.index(stage)

    for i in range(start_idx, len(stages_order)):
        current_stage = stages_order[i]
        stage_num = i + 3  # stages 3-6

        if current_stage == "upload":
            print_stage(3, "☁️", "Uploading to Google Cloud Storage...")
            upload_to_gcs(books, config)
            save_manifest({"stage": "process", "books": books})

        elif current_stage == "process":
            print_stage(4, "🔍", "Processing with Document AI...")
            process_with_docai(books, config)
            save_manifest({"stage": "download", "books": books})

        elif current_stage == "download":
            print_stage(5, "📥", "Downloading results...")
            download_results(books, config)
            save_manifest({"stage": "save", "books": books})

        elif current_stage == "save":
            print_stage(6, "💾", "Saving output files...")
            save_output(books)

    # Done
    cost = max(0, total_pages - 1000) / 1000 * 1.50
    print_header("✅ Done!")
    print(f"  📚 {len(books)} books processed ({total_pages:,} pages)")
    print(f"  📁 Text output:     {OUTPUT_TXT_DIR}")
    print(f"  📁 Markdown output: {OUTPUT_MD_DIR}")
    print(f"  💰 Estimated cost: ${cost:.2f}")
    print(f"  🗑️  Run 'python ocr.py --cleanup' to remove temp files\n")


# ============================================================
# Main Pipeline
# ============================================================

def run_pipeline(pdf_paths, config, dry_run=False):
    """Run the full OCR pipeline."""
    max_pages_per_chunk = config.get(
        "max_pages_per_chunk", DEFAULT_MAX_PAGES_PER_CHUNK
    )

    print_header("📄 Google Cloud Document AI — PDF OCR Tool")

    # ── Stage 1: Analyze ──
    print_stage(1, "📂", "Analyzing PDFs...")
    books, total_pages = analyze_pdfs(pdf_paths, max_pages_per_chunk)

    if not books:
        print("      ❌ No valid PDF files to process.")
        return

    print_analysis_table(books, total_pages)

    if dry_run:
        print("\n      ℹ️  Dry run — no processing performed.")
        return

    # Confirm
    resp = input("\n      Continue? [Y/n]: ").strip().lower()
    if resp == "n":
        print("      Cancelled.")
        return

    # ── Stage 2: Split ──
    print_stage(2, "✂️", "Splitting large PDFs...")
    total_chunks = split_pdfs(books, max_pages_per_chunk)
    print(f"      ✅ {total_chunks} total chunk(s) ready")

    # Save manifest for resume
    save_manifest({"stage": "upload", "books": books})

    # ── Stage 3: Upload ──
    print_stage(3, "☁️", "Uploading to Google Cloud Storage...")
    upload_to_gcs(books, config)
    save_manifest({"stage": "process", "books": books})

    # ── Stage 4: Process ──
    print_stage(4, "🔍", "Processing with Document AI...")
    process_with_docai(books, config)
    save_manifest({"stage": "download", "books": books})

    # ── Stage 5: Download ──
    print_stage(5, "📥", "Downloading results...")
    download_results(books, config)
    save_manifest({"stage": "save", "books": books})

    # ── Stage 6: Save ──
    print_stage(6, "💾", "Saving output files...")
    save_output(books)

    # ── Summary ──
    cost = max(0, total_pages - 1000) / 1000 * 1.50
    print_header("✅ Done!")
    print(f"  📚 {len(books)} books processed ({total_pages:,} pages)")
    print(f"  📁 Text output:     {OUTPUT_TXT_DIR}")
    print(f"  📁 Markdown output: {OUTPUT_MD_DIR}")
    print(f"  💰 Estimated cost: ${cost:.2f}")
    print(f"  🗑️  Run 'python ocr.py --cleanup' to remove temp files\n")


# ============================================================
# Argument Parsing & Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Google Cloud Document AI — PDF OCR Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python ocr.py --setup                    First-time configuration
  python ocr.py "My Book.pdf"              Process a single PDF
  python ocr.py --dir ~/Desktop/scans/     Process all PDFs in a folder
  python ocr.py --all                      Process all PDFs in lit/
  python ocr.py --cleanup                  Remove temp files and GCS objects
  python ocr.py --resume                   Resume interrupted processing
  python ocr.py --all --dry-run            Preview without processing
        """,
    )

    parser.add_argument("file", nargs="?", help="Path to a PDF file to process")
    parser.add_argument("--setup", action="store_true", help="First-time configuration")
    parser.add_argument("--dir", metavar="DIR", help="Process all PDFs in this directory")
    parser.add_argument("--all", action="store_true", help="Process all PDFs in lit/")
    parser.add_argument("--cleanup", action="store_true", help="Remove temp files and GCS data")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted processing")
    parser.add_argument("--dry-run", action="store_true", help="Preview without processing")

    args = parser.parse_args()

    # ── Route to the correct action ──

    if args.setup:
        run_setup()
        return

    if args.cleanup:
        run_cleanup()
        return

    if args.resume:
        config = load_config()
        resume_processing(config)
        return

    # Determine input PDF files
    pdf_paths = []

    if args.file:
        path = Path(args.file).resolve()
        if not path.exists():
            print(f"❌ File not found: {args.file}")
            sys.exit(1)
        if path.suffix.lower() != ".pdf":
            print(f"❌ Not a PDF file: {args.file}")
            sys.exit(1)
        pdf_paths = [str(path)]

    elif args.dir:
        dir_path = Path(args.dir).resolve()
        if not dir_path.is_dir():
            print(f"❌ Directory not found: {args.dir}")
            sys.exit(1)
        pdf_paths = sorted(str(p) for p in dir_path.glob("*.pdf"))
        if not pdf_paths:
            print(f"❌ No PDF files found in {args.dir}")
            sys.exit(1)

    elif args.all:
        if not DEFAULT_INPUT_DIR.is_dir():
            print(f"❌ Default input directory not found: {DEFAULT_INPUT_DIR}")
            sys.exit(1)
        pdf_paths = sorted(str(p) for p in DEFAULT_INPUT_DIR.glob("*.pdf"))
        if not pdf_paths:
            print(f"❌ No PDF files found in {DEFAULT_INPUT_DIR}")
            sys.exit(1)

    else:
        parser.print_help()
        return

    # Dry run doesn't need GCP config — just analyze local files
    if args.dry_run:
        config = {"max_pages_per_chunk": DEFAULT_MAX_PAGES_PER_CHUNK}
    else:
        config = load_config()

    run_pipeline(pdf_paths, config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
