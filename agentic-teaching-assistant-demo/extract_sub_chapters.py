# importing required modules
from pypdf import PdfReader
import tempfile
import shutil
from typing import List, Tuple
import sys
# Optional, more robust PDF handlers. Import lazily and handle absence.
try:
    import pikepdf
except Exception:
    pikepdf = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, NVIDIARerank
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnablePassthrough
import concurrent.futures
from colorama import Fore
import os,json
import argparse
from openai import OpenAI
from llm import create_llm
import requests
import asyncio
import re
from collections import OrderedDict
# Create LLM for legacy LangChain chains (fallback only)
llm = create_llm("extract_sub_chapters")


sub_topics_generation_prompt = """You are an expert in generation short chapter title to outline the studying curriculum.
        You will have access to one summary extracted from the a processed document which user uploaded previously.

        You will condense each summary and produce an appropriate title for that particular summary.
        <EXAMPLE>        
        document_summary:\nThis is a digital learning tool for driving license training. It is well-proven by students and driving schools. It is web-based and updated to most recent Swedish traffic regulations. This document includes basic variations of learning that are good to know before you practice driving.\n
        **chapter_title:**\n1: Intro to driving course - before driving practice.\n

        document_summary:\nThe document outlines essential safety practices for driving on country roads, emphasizing proactive scanning, speed control, and risk mitigation. Key strategies include maintaining a three-second following distance, regularly checking mirrors in a systematic pattern, and adjusting speed for conditions to avoid "speed blindness." It details proper positioning for turns (right edge for right turns, center for lefts) and highlights dangers of overtaking and abrupt maneuvers. Technical aspects cover reaction/braking distance calculations, the impact of kinetic energy in crashes, and using roadside reflectors (spaced 50m apart) for distance judgment. The text also addresses parking restrictions, hard shoulder usage, and the importance of avoiding left turns without clear visibility. Overall, it stresses defensive driving techniques to counter higher speeds and reduced friction on rural roads.
        **chapter_title:**\n 2: Driving essentials - dirving on Country roads.

        ...and so on
        </EXAMPLE>

        <RULEs>
        You will strictly follow below 3 rules, and in this order, when you produce the chapter titles :        
        1. you should always mark your response with '**chapter_title:**\n
        2. you will be given a chapter_nr, say 9, then add a prefix '9:' before the title
        3. you will condense the provided summary into one very short sentence appropriate for a title 
        4. return only the title, do not elaborate/explain anything else.
        </RULES>

        current input document_summary: {document_summary}        
        **chapter_title:**\n {chapter_nr}:"""

sub_topics_generation_prompt_template = ChatPromptTemplate.from_template(sub_topics_generation_prompt)


sub_topics_gen_chain = (
    RunnablePassthrough()    
    | sub_topics_generation_prompt_template
    | llm
)

def get_pdf_pages(pdf_file):
    # Use PdfReader with the file path and strict=False so PdfReader
    # manages the file lifecycle internally and avoids returning a
    # reader that relies on a closed file handle.
    try:
        reader = PdfReader(pdf_file, strict=False)
        n = len(reader.pages)
        print(type(n), n)
        return reader, n
    except Exception as e:
        print(f"Error opening/reading PDF '{pdf_file}': {e}")
        return None, 0

async def title_generator(summary,chapter_nr):
    query=sub_topics_generation_prompt.format(document_summary=summary, chapter_nr=chapter_nr)
    
    # Use LLM service for subtopic title generation
    try:
        llm_subtopic = create_llm("subtopic_title_generation")
        response = await llm_subtopic.ainvoke(query)
        if response and response.content:
            return response.content
    except Exception as e:
        print(Fore.YELLOW + f"LLM service error, falling back to LangChain: {e}" + Fore.RESET)
    
    # Fallback to LangChain if new client fails
    output = sub_topics_gen_chain.invoke({"document_summary":summary,"chapter_nr":chapter_nr})
    output = output.content
    return output

# creating a pdf reader object
def get_text_from_page(reader,i):
    # getting a specific page from the pdf file
    page = reader.pages[i]

    # extracting text from page
    try:
        text = page.extract_text()
    except Exception as e:
        print(f"Exception extracting text from page {i}: {e}")
        text = ""

    # if the extracted text is empty or very short, skip heavy LLM/title generation
    if not text or len(text.strip()) < 20:
        return ""

    try:
        # Run async title_generator from sync context using asyncio.run
        output = asyncio.run(title_generator(text, i))
        return output
    except Exception as e:
        print(f"Exception generating title for page {i}: {e}")
        return ""



def parallel_extract_pdf_page_and_text(path_to_pdf_file):
    reader, n = get_pdf_pages(path_to_pdf_file)
    if reader is None or n == 0:
        print("No pages to process.")
        return []
    # Configurable thread count for subtopic title extraction.
    extract_workers = int(os.environ.get("SUBTOPIC_EXTRACT_WORKERS", "5"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=extract_workers) as executor:
        # Start the load operations and mark each future with its URL
        future_to_page_text = {executor.submit(get_text_from_page, reader, i): (i) for (i) in range(n)}
        outputs = []
        for future in concurrent.futures.as_completed(future_to_page_text):
            temp = future_to_page_text[future]
            try:
                data = future.result()
                outputs.append(data)
            except Exception as exc:
                print('generated an exception: %s' % (exc))
                outputs.append('')
            else:
                try:
                    print('page is %d bytes' % (len(data)))
                except Exception:
                    print('page result length unknown')
                #outputs.append
    #print("#### extracted future_to_page_text >>>> ", len(outputs), outputs)
    return outputs


def _extract_prefix(s: str) -> Tuple[int, int]:
    """Extract numeric prefix and return (num, tie_breaker).

    Tie breaker is unused in the key but returned here for possible debugging.
    If the prefix isn't a valid int, return a large number so it sorts at the end.
    """
    if not isinstance(s, str):
        return (10 ** 9, 0)
    parts = s.split(':', 1)
    if len(parts) < 2:
        # No colon - treat as very large (put at the end)
        return (10 ** 9, 0)
    prefix = parts[0].strip()
    try:
        num = int(prefix)
        return (num, 0)
    except ValueError:
        return (10 ** 9, 0)


def sort_list_by_prefix(items: List[str]) -> List[str]:
    """Return a new list sorted by ascending numeric prefix.

    The sort is stable for equal numeric prefixes. Non-parsable or missing prefixes
    are placed at the end in their original relative order.
    """
    # Enumerate to keep stability for non-unique keys when needed
    enumerated = list(enumerate(items))

    def key_fn(pair):
        idx, s = pair
        num, _ = _extract_prefix(s)
        return (num, idx)

    enumerated.sort(key=key_fn)
    return [s for idx, s in enumerated]



def _strip_numeric_prefix(title: str) -> str:
    """Remove the leading numeric prefix (e.g. '0: ', '8: ') from a subtopic title.

    The prompt template asks the LLM to continue after ``{chapter_nr}:``, so
    the raw output contains the page/segment number as a prefix.
    ``sort_list_by_prefix`` needs that prefix for ordering, but once sorted
    it should be stripped so titles are clean for the UI.
    """
    title = title.strip()
    if ':' in title:
        prefix, rest = title.split(':', 1)
        if prefix.strip().isdigit():
            return rest.strip()
    return title


def post_process_extract_sub_chapters(output):
    sub_chapters=[]
    for o in output:
        if not o or not isinstance(o, str):
            continue
        # Handle multiple possible LLM output formats:
        # - "**chapter_title:**\n0: Title" (expected)
        # - "**chapter_title:\n0: Title" (LLM variation - missing * before newline)
        # - "chapter_title:\n0: Title" (no asterisks)
        if "**chapter_title:**" in o:
            strip_o = o.index("**chapter_title:**") + 18
            sub_chapters.append(o[strip_o:])
        elif "**chapter_title:" in o:
            # Handle case where LLM omits the closing asterisks
            strip_o = o.index("**chapter_title:") + 16
            # Skip any trailing asterisks or newline
            remaining = o[strip_o:].lstrip('*').lstrip('\n')
            sub_chapters.append(remaining)
        elif "chapter_title:" in o:
            # Fallback - no asterisks at all
            strip_o = o.index("chapter_title:") + 14
            remaining = o[strip_o:].lstrip('*').lstrip('\n')
            sub_chapters.append(remaining)
    ordered_subchapters = sort_list_by_prefix(sub_chapters)
    # Strip the numeric prefix (e.g. "0: ", "8: ") now that sorting is done
    ordered_subchapters = [_strip_numeric_prefix(t) for t in ordered_subchapters]
    return ordered_subchapters


# ── TF-IDF Segmented Extraction ──────────────────────────────────────
# These functions group similar consecutive pages into segments using
# TF-IDF cosine similarity, then generate ONE subtopic title per segment
# instead of one per page.  For a 50-page PDF this typically reduces
# LLM calls from ~50 to ~8-15.

def extract_all_page_texts(pdf_path: str) -> List[str]:
    """Extract text from every page of a PDF.  Pure I/O, no LLM calls.

    Returns a list of strings indexed by page number.  Pages whose text
    is shorter than 20 characters are returned as empty strings.
    """
    reader, n = get_pdf_pages(pdf_path)
    if reader is None or n == 0:
        return []

    texts: List[str] = []
    for i in range(n):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception as e:
            print(f"[extract_all_page_texts] Error on page {i}: {e}")
            text = ""
        texts.append(text.strip() if len(text.strip()) >= 20 else "")
    print(Fore.CYAN + f"[extract] Extracted text from {n} pages "
          f"({sum(1 for t in texts if t)} valid)" + Fore.RESET)
    return texts


def segment_pages_by_topic(
    page_texts: List[str],
    similarity_threshold: float = 0.15,
) -> List[Tuple[List[int], str]]:
    """Group consecutive pages with similar content into segments.

    Uses TF-IDF vectorisation + pairwise cosine similarity on adjacent
    pages.  When the similarity between page *i* and page *i+1* drops
    below ``similarity_threshold`` a new segment boundary is created.

    Args:
        page_texts: List of page texts (empty strings for skipped pages).
        similarity_threshold: Cosine-similarity cutoff for segment breaks.

    Returns:
        List of ``(page_indices, combined_text)`` tuples.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
    except ImportError:
        # sklearn not available – fall back to one-segment-per-valid-page
        print(Fore.YELLOW + "[segment] scikit-learn not installed, "
              "falling back to per-page segments" + Fore.RESET)
        segments = []
        for i, t in enumerate(page_texts):
            if t:
                segments.append(([i], t))
        return segments

    # Collect only pages with actual text
    valid = [(i, t) for i, t in enumerate(page_texts) if t]
    if not valid:
        return []
    if len(valid) == 1:
        return [([valid[0][0]], valid[0][1])]

    indices = [v[0] for v in valid]
    texts = [v[1] for v in valid]

    try:
        vec = TfidfVectorizer(stop_words="english", max_features=500)
        tfidf = vec.fit_transform(texts)
    except ValueError:
        # Can happen if all texts are stop-words only
        return [([i], t) for i, t in valid]

    # Compute adjacent-page similarity
    sim_matrix = _cos_sim(tfidf)

    # Build segments by comparing consecutive valid pages
    segments: List[Tuple[List[int], str]] = []
    current_pages = [indices[0]]
    current_texts = [texts[0]]

    for j in range(1, len(valid)):
        sim = sim_matrix[j - 1, j]
        if sim >= similarity_threshold:
            # Same segment – merge
            current_pages.append(indices[j])
            current_texts.append(texts[j])
        else:
            # New segment boundary
            segments.append((current_pages, "\n\n".join(current_texts)))
            current_pages = [indices[j]]
            current_texts = [texts[j]]

    # Flush last segment
    segments.append((current_pages, "\n\n".join(current_texts)))

    print(Fore.CYAN + f"[segment] Grouped {len(valid)} valid pages "
          f"into {len(segments)} segments "
          f"(threshold={similarity_threshold})" + Fore.RESET)
    return segments


def segmented_extract_subtopics(pdf_path: str) -> List[str]:
    """Sync wrapper: extract text → TF-IDF segment → one LLM title per segment.

    Returns an ordered list of subtopic title strings (same format as
    ``post_process_extract_sub_chapters``).
    """
    page_texts = extract_all_page_texts(pdf_path)
    if not page_texts:
        return []

    try:
        threshold = float(os.environ.get("SEGMENT_SIMILARITY_THRESHOLD", "0.15"))
    except (ValueError, TypeError):
        threshold = 0.15
    segments = segment_pages_by_topic(page_texts, threshold)
    if not segments:
        return []

    titles: List[str] = []
    for page_ids, combined_text in segments:
        seg_nr = page_ids[0]  # use first page number as the segment id
        # Truncate very long combined text to avoid token limits
        summary = combined_text[:4000]
        try:
            raw = asyncio.run(title_generator(summary, seg_nr))
        except Exception as e:
            print(Fore.YELLOW + f"[segmented] Title gen failed for "
                  f"segment starting at page {seg_nr}: {e}" + Fore.RESET)
            raw = ""
        if raw:
            titles.append(raw)

    return post_process_extract_sub_chapters(titles)


async def async_segmented_extract_subtopics(pdf_path: str) -> List[str]:
    """Async version: extract text → TF-IDF segment → concurrent LLM titles.

    Same result as :func:`segmented_extract_subtopics` but generates all
    segment titles concurrently via ``asyncio.gather``.
    """
    page_texts = extract_all_page_texts(pdf_path)
    if not page_texts:
        return []

    try:
        threshold = float(os.environ.get("SEGMENT_SIMILARITY_THRESHOLD", "0.15"))
    except (ValueError, TypeError):
        threshold = 0.15
    segments = segment_pages_by_topic(page_texts, threshold)
    if not segments:
        return []

    async def _gen_title(seg_nr: int, text: str) -> str:
        try:
            return await title_generator(text[:4000], seg_nr)
        except Exception as e:
            print(Fore.YELLOW + f"[async_segmented] Title gen failed "
                  f"for segment {seg_nr}: {e}" + Fore.RESET)
            return ""

    raw_titles = await asyncio.gather(*[
        _gen_title(page_ids[0], combined_text)
        for page_ids, combined_text in segments
    ])

    # Filter empties and post-process
    return post_process_extract_sub_chapters(list(raw_titles))


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Generate Chapters")
    argparser.add_argument(
        "--pdf_file_loc",
        type=str,
        default="/workspace/mnt/pdfs/SwedenDriving_intro.pdf",
        help="avsolute path to a specific pdf file",
    )
    argparser.add_argument(
        "--segmented", action="store_true",
        help="Use TF-IDF segmented extraction instead of per-page",
    )
    args = argparser.parse_args()
    path_to_pdf_file=args.pdf_file_loc

    if args.segmented:
        output = segmented_extract_subtopics(path_to_pdf_file)
    else:
        output = parallel_extract_pdf_page_and_text(path_to_pdf_file)
        output = post_process_extract_sub_chapters(output)
    
    i=0
    for p_text in output:
        print(f" ---------------------- extracted page number: {str(i)} ---------------------------")
        print(p_text)
        i+=1
    print('\n'.join(output))


