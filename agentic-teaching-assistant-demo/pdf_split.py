"""
pdf_split.py - Parallel PDF Splitting & Processing Pipeline

Optimizes curriculum generation for large PDFs by:
1. Pre-splitting large PDFs (>threshold pages) into smaller chunks
2. Using Python multiprocessing to process chunks in parallel:
   - Extract subtopics per page (LLM)
   - Generate study materials via RAG + LLM
3. Prioritizing the first chunk for quick UI feedback
4. Assembling results into the existing Chapter/SubTopic data model

Architecture:
    ┌─────────────┐     ┌──────────┐     ┌───────────────────┐
    │ Large PDF    │────▶│ Split    │────▶│ Chunk 1 (10 pp)  │
    │ (100 pages)  │     │ Engine   │     │ Chunk 2 (10 pp)  │
    │              │     │          │     │ ...              │
    │              │     │          │     │ Chunk N (10 pp)  │
    └─────────────┘     └──────────┘     └───────────────────┘
                                                    │
                                    ┌───────────────┴───────────────┐
                                    │  VectorDB Ingest             │
                                    │  (original PDF - unchanged)  │
                                    └───────────────┬───────────────┘
                                                    │
                                         ┌──────────▼──────────┐
                                         │  Multiprocessing     │
                                         │  Pool                │
                                         ├─────────────────────┤
                                         │ Worker 1 (Chunk 1)  │◀── Priority
                                         │ Worker 2 (Chunk 2)  │
                                         │ Worker 3 (Chunk 3)  │
                                         │ ...                 │
                                         └──────────┬──────────┘
                                                    │
                                         ┌──────────▼──────────┐
                                         │ Assemble Chapter    │
                                         │ (all SubTopics,     │
                                         │  ordered by page)   │
                                         └─────────────────────┘

Each worker process:
    1. Extracts text from chunk pages (pypdf)
    2. Generates subtopic titles per page (LLM, 5 threads)
    3. Generates study materials per subtopic (RAG + LLM)

Note: VectorDB ingestion uses the ORIGINAL PDF (not chunks), so
RAG queries can retrieve context from the entire document. Splitting
is purely for parallelizing the processing steps.

Usage:
    # As integration in nodes.py
    from pdf_split import parallel_sub_topic_builder
    subtopics = await parallel_sub_topic_builder(username, pdf_path, subject, pdf_name)

    # Standalone
    python pdf_split.py /path/to/large.pdf --username test --chunk-size 10
    python pdf_split.py /path/to/large.pdf --split-only  # just split, don't process
"""

from __future__ import annotations

import os
import time
import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, asdict
from colorama import Fore

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None
    print(Fore.YELLOW + "[pdf_split] pypdfium2 not installed. Install with: pip install pypdfium2" + Fore.RESET)


# ── Configuration ─────────────────────────────────────────────────────
# These can be overridden via environment variables

DEFAULT_CHUNK_SIZE = int(os.environ.get("PDF_SPLIT_CHUNK_SIZE", "10"))
MAX_WORKERS = int(os.environ.get("PDF_SPLIT_MAX_WORKERS", "4"))
SPLIT_THRESHOLD = int(os.environ.get("PDF_SPLIT_THRESHOLD", "10"))


# ── Data Classes (pickle-safe for multiprocessing) ────────────────────

@dataclass
class PdfChunkInfo:
    """Metadata for a PDF chunk. All fields are pickle-safe primitives."""
    chunk_index: int
    chunk_path: str           # path to the split chunk file on disk
    original_pdf_path: str    # path to the original (full) PDF
    original_pdf_name: str    # filename of the original PDF (for RAG queries)
    start_page: int           # global start page in original PDF (0-indexed)
    end_page: int             # global end page in original PDF (exclusive)
    total_pages: int          # total pages in original PDF


@dataclass
class ChunkResult:
    """Result from processing a single chunk. All fields are pickle-safe."""
    chunk_index: int
    start_page: int
    end_page: int
    subtopics: List[Dict]     # list of SubTopic-compatible dicts
    status: str               # "completed", "failed", "skipped"
    error: Optional[str] = None
    processing_time: float = 0.0


# ── PDF Splitting ─────────────────────────────────────────────────────

def get_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF without fully parsing it.

    Tries pypdfium2 first (fastest), falls back to pypdf.
    """
    if pdfium is not None:
        try:
            doc = pdfium.PdfDocument(pdf_path)
            n = len(doc)
            return n
        except Exception:
            pass

    # Fallback to pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path, strict=False)
        return len(reader.pages)
    except Exception:
        return 0


def split_pdf(
    input_path: str,
    output_dir: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> List[PdfChunkInfo]:
    """Split a PDF into chunks of ``chunk_size`` pages each.

    If the PDF has fewer pages than ``chunk_size``, returns a single chunk
    pointing to the original file (no splitting needed).

    Args:
        input_path: Path to the PDF file.
        output_dir: Directory to write chunk files to.
        chunk_size: Maximum pages per chunk.

    Returns:
        Ordered list of :class:`PdfChunkInfo` objects.
    """
    if pdfium is None:
        raise ImportError("pypdfium2 is required for PDF splitting. Install: pip install pypdfium2")

    pdf = pdfium.PdfDocument(input_path)
    total_pages = len(pdf)
    original_name = os.path.basename(input_path)

    # No split needed for small PDFs
    if total_pages <= chunk_size:
        return [PdfChunkInfo(
            chunk_index=0,
            chunk_path=input_path,
            original_pdf_path=input_path,
            original_pdf_name=original_name,
            start_page=0,
            end_page=total_pages,
            total_pages=total_pages,
        )]

    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(original_name)[0]
    chunks: List[PdfChunkInfo] = []

    for start in range(0, total_pages, chunk_size):
        end = min(start + chunk_size, total_pages)
        chunk_doc = pdfium.PdfDocument.new()
        chunk_doc.import_pages(pdf, list(range(start, end)))

        chunk_index = start // chunk_size
        chunk_path = os.path.join(output_dir, f"{base_name}_part{chunk_index + 1}.pdf")
        chunk_doc.save(chunk_path)

        chunks.append(PdfChunkInfo(
            chunk_index=chunk_index,
            chunk_path=chunk_path,
            original_pdf_path=input_path,
            original_pdf_name=original_name,
            start_page=start,
            end_page=end,
            total_pages=total_pages,
        ))

    print(
        Fore.CYAN
        + f"[pdf_split] Split '{original_name}' ({total_pages} pages) "
        + f"into {len(chunks)} chunks of ~{chunk_size} pages"
        + Fore.RESET
    )
    return chunks


def render_pdf_to_images(input_path: str, output_prefix: str):
    """Render each page of a PDF as a PNG image (utility function).

    Useful for VLM processing of page content.
    """
    if pdfium is None:
        raise ImportError("pypdfium2 is required. Install: pip install pypdfium2")

    pdf = pdfium.PdfDocument(input_path)
    for page_number in range(len(pdf)):
        page = pdf[page_number]
        pil_image = page.render(scale=2).to_pil()
        output_path = f"{output_prefix}_page_{page_number + 1}.png"
        pil_image.save(output_path)


# ── Chunk Processing Worker ──────────────────────────────────────────
# These functions run in CHILD processes via multiprocessing.
# They must be top-level functions (not lambdas/closures) and all
# arguments/return values must be pickle-safe (plain dicts, strings, etc.)

def _chunk_worker(args: Tuple[Dict, str]) -> Dict:
    """Multiprocessing worker: process one PDF chunk.

    Creates its own asyncio event loop (child processes don't inherit
    the parent's loop).

    Args:
        args: Tuple of (chunk_info_dict, username)

    Returns:
        A ChunkResult-compatible dict (pickle-safe).
    """
    chunk_dict, username = args

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Create the coroutine first, then run it in the loop.
    # This ensures it's always properly awaited even if run_until_complete raises.
    coro = _async_process_chunk(chunk_dict, username)
    try:
        result = loop.run_until_complete(coro)
        return result
    except Exception as e:
        # Cancel the coroutine if it didn't complete, to suppress the
        # "coroutine was never awaited" RuntimeWarning
        try:
            coro.close()
        except Exception:
            pass
        return {
            "chunk_index": chunk_dict["chunk_index"],
            "start_page": chunk_dict["start_page"],
            "end_page": chunk_dict["end_page"],
            "subtopics": [],
            "status": "failed",
            "error": str(e),
            "processing_time": 0.0,
        }
    finally:
        loop.close()


async def _async_process_chunk(chunk_dict: Dict, username: str) -> Dict:
    """Async implementation of single-chunk processing.

    For each page in the chunk:
        1. Extract text (pypdf via existing ThreadPoolExecutor)
        2. Generate subtopic title (LLM)
    Then for each valid subtopic:
        3. Generate study material (RAG query on ORIGINAL filename + LLM)

    Imports are done inside the function to avoid pickle issues when
    sending the function across process boundaries.
    """
    t_start = time.time()

    # ── Lazy imports (avoids pickling module-level state) ──
    from extract_sub_chapters import (
        parallel_extract_pdf_page_and_text,
        post_process_extract_sub_chapters,
        segmented_extract_subtopics,
    )
    from study_material_gen_agent import study_material_gen

    chunk_path = chunk_dict["chunk_path"]
    start_page = chunk_dict["start_page"]
    end_page = chunk_dict["end_page"]
    original_pdf_name = chunk_dict["original_pdf_name"]
    chunk_index = chunk_dict["chunk_index"]
    subject = os.path.splitext(original_pdf_name)[0]

    print(
        Fore.LIGHTBLUE_EX
        + f"[Worker {chunk_index}] Processing pages {start_page}-{end_page - 1} "
        + f"of '{original_pdf_name}'"
        + Fore.RESET
    )

    # ── Step 1: Extract subtopics from chunk pages ──
    # Algorithm 1: TF-IDF segmentation groups similar pages into topic segments.
    # This reduces LLM calls from ~10 (1 per page) to ~3-5 (1 per segment).
    # Note: In worker processes we use the async version directly since we
    # already have an event loop from _chunk_worker.
    use_segmented = os.environ.get("USE_SEGMENTED_EXTRACTION", "true").lower() in ("1", "true", "yes")
    
    if use_segmented:
        try:
            from extract_sub_chapters import async_segmented_extract_subtopics
            ordered_subtopics = await async_segmented_extract_subtopics(chunk_path)
        except ImportError:
            ordered_subtopics = segmented_extract_subtopics(chunk_path)
    else:
        raw_outputs = parallel_extract_pdf_page_and_text(chunk_path)
        ordered_subtopics = post_process_extract_sub_chapters(raw_outputs)
    
    # Algorithm 3: Deduplicate near-identical subtopics within this chunk
    if ordered_subtopics and len(ordered_subtopics) > 1:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
            
            try:
                dedup_threshold = float(os.environ.get("SUBTOPIC_DEDUP_THRESHOLD", "0.85"))
            except (ValueError, TypeError):
                dedup_threshold = 0.85
            if dedup_threshold < 1.0:
                cleaned = [t.split(":")[-1].strip() if ":" in t else t.strip() for t in ordered_subtopics]
                non_empty = [(i, c) for i, c in enumerate(cleaned) if len(c) > 3]
                if len(non_empty) > 1:
                    texts = [c for _, c in non_empty]
                    try:
                        vec = TfidfVectorizer(stop_words='english', max_features=200)
                        tfidf = vec.fit_transform(texts)
                        sim = _cos_sim(tfidf)
                        duplicates = set()
                        for a in range(len(non_empty)):
                            for b in range(a + 1, len(non_empty)):
                                if sim[a][b] > dedup_threshold:
                                    duplicates.add(non_empty[b][0])
                        if duplicates:
                            before_count = len(ordered_subtopics)
                            ordered_subtopics = [t for idx, t in enumerate(ordered_subtopics) if idx not in duplicates]
                            print(f"[Worker {chunk_index}] Dedup: {before_count} → {len(ordered_subtopics)} subtopics")
                    except ValueError:
                        pass
        except ImportError:
            pass

    if not ordered_subtopics:
        elapsed = time.time() - t_start
        print(
            Fore.YELLOW
            + f"[Worker {chunk_index}] No subtopics extracted (pages {start_page}-{end_page - 1})"
            + Fore.RESET
        )
        return {
            "chunk_index": chunk_index,
            "start_page": start_page,
            "end_page": end_page,
            "subtopics": [],
            "status": "skipped",
            "error": "No subtopics extracted from chunk pages",
            "processing_time": elapsed,
        }

    # ── Step 2: Generate study materials per subtopic (concurrent) ──
    # RAG queries use the ORIGINAL PDF filename so that context comes from
    # the full document (not just this chunk).
    # Uses asyncio.Semaphore to limit concurrent LLM calls and respect rate limits.
    concurrency = int(os.environ.get("STUDY_MATERIAL_CONCURRENCY", "8"))
    sem = asyncio.Semaphore(concurrency)
    max_retries = 3

    async def _gen_one(j: int, sub_topic_title: str):
        _title = (
            sub_topic_title.split(":")[-1].strip()
            if ":" in sub_topic_title
            else sub_topic_title
        )
        study_str, md_str = "", ""
        async with sem:
            # Retry with exponential backoff for rate limit (429) errors
            for attempt in range(max_retries):
                try:
                    study_str, md_str = await study_material_gen(
                        username, subject, _title, original_pdf_name, num_docs=3
                    )
                    # Check for suspiciously short responses (likely 429 error passed through)
                    if md_str and len(md_str) > 150:
                        break
                    elif attempt < max_retries - 1:
                        backoff = 2 ** attempt * 2
                        print(Fore.YELLOW + f"[Worker {chunk_index}] Short response for '{_title}', retrying in {backoff}s" + Fore.RESET)
                        await asyncio.sleep(backoff)
                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        backoff = 2 ** attempt * 3
                        print(Fore.YELLOW + f"[Worker {chunk_index}] Rate limited on '{_title}', backoff {backoff}s" + Fore.RESET)
                        await asyncio.sleep(backoff)
                    elif attempt == max_retries - 1:
                        print(Fore.RED + f"[Worker {chunk_index}] Study material failed for '{_title}': {e}" + Fore.RESET)
                        study_str, md_str = "", ""
                    else:
                        await asyncio.sleep(2)
        return j, sub_topic_title, study_str, md_str

    gen_results = await asyncio.gather(*[
        _gen_one(j, title) for j, title in enumerate(ordered_subtopics)
    ])

    subtopic_dicts: List[Dict] = []
    for j, sub_topic_title, study_str, md_str in sorted(gen_results, key=lambda r: r[0]):
        if md_str:
            global_number = start_page + j
            subtopic_dicts.append({
                "number": global_number,
                "sub_topic": sub_topic_title,
                "status": "NA",
                "study_material": study_str,
                "display_markdown": md_str,
                "reference": original_pdf_name,
                "quizzes": [],
                "feedback": [],
            })

    elapsed = time.time() - t_start
    print(
        Fore.LIGHTGREEN_EX
        + f"[Worker {chunk_index}] Complete: {len(subtopic_dicts)} subtopics "
        + f"in {elapsed:.1f}s (pages {start_page}-{end_page - 1})"
        + Fore.RESET
    )

    return {
        "chunk_index": chunk_index,
        "start_page": start_page,
        "end_page": end_page,
        "subtopics": subtopic_dicts,
        "status": "completed",
        "error": None,
        "processing_time": elapsed,
    }


# ── Main Orchestrator ─────────────────────────────────────────────────

async def split_and_process_pdf(
    pdf_path: str,
    username: str,
    output_dir: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_workers: int = MAX_WORKERS,
    prioritize_first: bool = True,
    progress_callback: Optional[Callable] = None,
) -> List[Dict]:
    """Split a large PDF and process all chunks in parallel.

    This is the main entry point for the parallel processing pipeline.

    Args:
        pdf_path: Path to the PDF file.
        username: User identifier (used for RAG collection queries).
        output_dir: Directory for split chunk files (default: ``<pdf_dir>/_splits``).
        chunk_size: Pages per chunk.
        max_workers: Maximum number of parallel worker processes.
        prioritize_first: If True, process chunk 1 first (synchronously)
            so the UI can show results quickly while remaining chunks
            process in the background.
        progress_callback: Optional async callable
            ``callback(chunk_index, status, total_chunks)``
            for real-time progress reporting (e.g., SSE streaming).

    Returns:
        Flat list of SubTopic-compatible dicts, ordered by global page number.
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(pdf_path), "_splits")

    # ── Step 1: Split PDF into chunks ──
    t0 = time.time()
    chunks = split_pdf(pdf_path, output_dir, chunk_size)
    total_chunks = len(chunks)
    t_split = time.time() - t0
    print(
        Fore.CYAN
        + f"[pdf_split] Split into {total_chunks} chunk(s) in {t_split:.2f}s"
        + Fore.RESET
    )

    if not chunks:
        return []

    if progress_callback:
        await progress_callback(-1, "split_complete", total_chunks)

    # Convert to pickle-safe dicts for multiprocessing
    chunk_dicts = [asdict(c) for c in chunks]

    # ── Step 2: Process chunks ──
    all_results: List[Optional[Dict]] = [None] * total_chunks

    if total_chunks == 1:
        # Single chunk — no multiprocessing overhead needed
        print(Fore.CYAN + "[pdf_split] Single chunk, processing directly..." + Fore.RESET)
        result = _chunk_worker((chunk_dicts[0], username))
        all_results[0] = result

    elif prioritize_first:
        # Process chunk 0 synchronously first (priority / fast UI feedback)
        print(
            Fore.LIGHTGREEN_EX
            + "[pdf_split] Priority: processing chunk 0 first..."
            + Fore.RESET
        )
        if progress_callback:
            await progress_callback(0, "processing", total_chunks)

        all_results[0] = _chunk_worker((chunk_dicts[0], username))

        if progress_callback:
            status = all_results[0]["status"] if all_results[0] else "failed"
            await progress_callback(0, status, total_chunks)

        # Process remaining chunks in parallel via multiprocessing
        remaining = chunk_dicts[1:]
        if remaining:
            n_workers = min(max_workers, len(remaining))
            print(
                Fore.LIGHTGREEN_EX
                + f"[pdf_split] Parallel: processing {len(remaining)} remaining "
                + f"chunks with {n_workers} workers..."
                + Fore.RESET
            )

            loop = asyncio.get_running_loop()
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = [
                    loop.run_in_executor(
                        executor, _chunk_worker, (cd, username)
                    )
                    for cd in remaining
                ]

                # Collect results as they complete
                for coro in asyncio.as_completed(futures):
                    result = await coro
                    idx = result["chunk_index"]
                    all_results[idx] = result
                    if progress_callback:
                        await progress_callback(idx, result["status"], total_chunks)
    else:
        # Process ALL chunks in parallel (no priority)
        n_workers = min(max_workers, total_chunks)
        print(
            Fore.LIGHTGREEN_EX
            + f"[pdf_split] Parallel: processing all {total_chunks} chunks "
            + f"with {n_workers} workers..."
            + Fore.RESET
        )

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = [
                loop.run_in_executor(
                    executor, _chunk_worker, (cd, username)
                )
                for cd in chunk_dicts
            ]

            for coro in asyncio.as_completed(futures):
                result = await coro
                idx = result["chunk_index"]
                all_results[idx] = result
                if progress_callback:
                    await progress_callback(idx, result["status"], total_chunks)

    # ── Step 3: Assemble all subtopics (ordered by global page number) ──
    all_subtopics: List[Dict] = []
    total_process_time = 0.0
    completed = 0
    failed = 0

    for result in all_results:
        if result is None:
            failed += 1
            continue
        if result["status"] == "completed":
            all_subtopics.extend(result["subtopics"])
            completed += 1
        elif result["status"] == "failed":
            failed += 1
            print(
                Fore.RED
                + f"[pdf_split] Chunk {result['chunk_index']} failed: {result.get('error', '?')}"
                + Fore.RESET
            )
        total_process_time += result.get("processing_time", 0.0)

    # Sort by global page number, then re-number sequentially
    all_subtopics.sort(key=lambda st: st["number"])
    for i, st in enumerate(all_subtopics):
        st["number"] = i

    wall_time = time.time() - t0
    print(
        Fore.LIGHTGREEN_EX
        + f"[pdf_split] Done: {len(all_subtopics)} subtopics from "
        + f"{completed}/{total_chunks} chunks. "
        + f"Wall: {wall_time:.1f}s, Sum of workers: {total_process_time:.1f}s"
        + (f", {failed} chunk(s) failed" if failed else "")
        + Fore.RESET
    )

    # ── Step 4: Cleanup temporary split files ──
    _cleanup_splits(output_dir, chunks)

    return all_subtopics


def _cleanup_splits(output_dir: str, chunks: List[PdfChunkInfo]):
    """Remove temporary split chunk files (not the original PDF)."""
    for chunk in chunks:
        if chunk.chunk_path != chunk.original_pdf_path:
            try:
                os.remove(chunk.chunk_path)
            except OSError:
                pass
    try:
        if os.path.isdir(output_dir) and not os.listdir(output_dir):
            os.rmdir(output_dir)
    except OSError:
        pass


# ── Integration Functions ─────────────────────────────────────────────
# Drop-in replacements for nodes.py::sub_topic_builder

async def parallel_sub_topic_builder(
    username: str,
    pdf_path: str,
    subject: str,
    pdf_filename: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_workers: int = MAX_WORKERS,
    progress_callback: Optional[Callable] = None,
) -> list:
    """Process a PDF's subtopics. Delegates to ``sub_topic_builder`` which
    uses TF-IDF segmentation + dedup + concurrent study materials.

    With the algorithmic optimizations (TF-IDF reduces 244 pages to ~25
    segments, dedup removes another ~15%), multiprocessing adds overhead
    (process spawning, 429 retries, module re-imports) for diminishing
    returns. Processing the full document in the main process with
    ``asyncio.gather`` concurrency is both simpler and faster.

    The multiprocessing pipeline (``split_and_process_pdf``) is retained
    in this module for potential future use with very large corpora where
    the number of unique subtopics exceeds what single-process concurrency
    can handle efficiently.

    Args:
        username: User identifier.
        pdf_path: Full path to the PDF file.
        subject: Subject/title derived from PDF name.
        pdf_filename: Basename of the PDF file.
        progress_callback: Optional async callback for progress events.

    Returns:
        List of SubTopic Pydantic objects.
    """
    page_count = get_page_count(pdf_path)
    print(
        Fore.CYAN
        + f"[pdf_split] PDF '{pdf_filename}' has {page_count} pages — "
        + "using TF-IDF segmentation (main process)"
        + Fore.RESET
    )

    # Delegate to sub_topic_builder which has TF-IDF segmentation + dedup +
    # concurrent study material generation via asyncio.gather.
    from nodes import sub_topic_builder
    return await sub_topic_builder(
        username, pdf_path, subject, pdf_filename,
        progress_callback=progress_callback,
    )


async def process_all_pdfs_parallel(
    pdf_dir: str,
    username: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_workers: int = MAX_WORKERS,
    progress_callback: Optional[Callable] = None,
) -> Dict[str, list]:
    """Process all PDFs in a directory using the parallel pipeline.

    Each PDF is split and processed independently. Results are keyed
    by PDF filename.

    Args:
        pdf_dir: Directory containing PDF files.
        username: User identifier.
        chunk_size: Pages per chunk.
        max_workers: Maximum parallel worker processes.
        progress_callback: Optional async callback
            ``callback(pdf_name, status, pdf_index, total_pdfs)``.

    Returns:
        Dict mapping PDF filename to list of SubTopic-compatible dicts.
    """
    pdf_files = sorted(
        f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")
    )

    if not pdf_files:
        print(f"[pdf_split] No PDF files found in {pdf_dir}")
        return {}

    results: Dict[str, list] = {}

    for i, pdf_file in enumerate(pdf_files):
        pdf_path = os.path.join(pdf_dir, pdf_file)

        if progress_callback:
            await progress_callback(pdf_file, "processing", i, len(pdf_files))

        subtopics = await split_and_process_pdf(
            pdf_path=pdf_path,
            username=username,
            chunk_size=chunk_size,
            max_workers=max_workers,
            # Prioritize first chunk of first PDF only
            prioritize_first=(i == 0),
        )

        results[pdf_file] = subtopics

        if progress_callback:
            await progress_callback(pdf_file, "completed", i, len(pdf_files))

    return results


# ── Standalone Usage ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Split and process PDFs in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split only (no LLM processing)
  python pdf_split.py /path/to/large.pdf --split-only

  # Full parallel processing
  python pdf_split.py /path/to/large.pdf --username test --chunk-size 10

  # Process all PDFs in a directory
  python pdf_split.py /path/to/pdf_dir/ --username test

  # Adjust parallelism
  python pdf_split.py /path/to/large.pdf --username test --max-workers 8 --chunk-size 15
        """,
    )
    parser.add_argument("pdf_path", help="Path to PDF file or directory of PDFs")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Pages per chunk (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS,
                        help=f"Max parallel processes (default: {MAX_WORKERS})")
    parser.add_argument("--username", default="test",
                        help="Username for RAG collection (default: test)")
    parser.add_argument("--split-only", action="store_true",
                        help="Only split the PDF, don't process subtopics/study materials")
    args = parser.parse_args()

    if args.split_only:
        # ── Split-only mode ──
        if os.path.isfile(args.pdf_path):
            split_dir = args.pdf_path + "_splits"
            chunks = split_pdf(args.pdf_path, split_dir, args.chunk_size)
            print(f"\nSplit into {len(chunks)} chunk(s):")
            for c in chunks:
                pages = c.end_page - c.start_page
                print(f"  Part {c.chunk_index + 1}: {c.chunk_path} ({pages} pages, "
                      f"global pages {c.start_page}-{c.end_page - 1})")
        else:
            for f in sorted(os.listdir(args.pdf_path)):
                if f.lower().endswith(".pdf"):
                    path = os.path.join(args.pdf_path, f)
                    split_dir = os.path.join(args.pdf_path, "_splits")
                    chunks = split_pdf(path, split_dir, args.chunk_size)
                    for c in chunks:
                        pages = c.end_page - c.start_page
                        print(f"  {f} → Part {c.chunk_index + 1}: {pages} pages")
    else:
        # ── Full processing mode ──
        if os.path.isfile(args.pdf_path):
            results = asyncio.run(split_and_process_pdf(
                pdf_path=args.pdf_path,
                username=args.username,
                chunk_size=args.chunk_size,
                max_workers=args.max_workers,
            ))
            print(f"\n{'='*60}")
            print(f"Processed {len(results)} subtopic(s):")
            for st in results:
                print(f"  [{st['number']:3d}] {st['sub_topic'][:70]}")
        else:
            results = asyncio.run(process_all_pdfs_parallel(
                pdf_dir=args.pdf_path,
                username=args.username,
                chunk_size=args.chunk_size,
                max_workers=args.max_workers,
            ))
            print(f"\n{'='*60}")
            for pdf_name, subtopics in results.items():
                print(f"\n{pdf_name}: {len(subtopics)} subtopic(s)")
                for st in subtopics:
                    print(f"  [{st['number']:3d}] {st['sub_topic'][:70]}")
