"""
Curriculum Routes

Handles curriculum generation, retrieval, and navigation.
Uses nodes.py functions: run_for_first_time_user, load_user_state, 
                         move_to_next_chapter, update_subtopic_status
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

# Add parent directory to path
parent_dir = Path(__file__).parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from common.debug import debug_print
from api.schemas.curriculum import (
    CurriculumResponse,
    CurriculumGenerateRequest,
    CurriculumGenerateResponse,
    SubtopicStatusUpdateRequest,
    SubtopicStatusUpdateResponse,
    NextChapterResponse,
    ChapterResponse,
    SubTopicResponse,
    StatusEnum,
)

router = APIRouter()

# Route curriculum ingestion diagnostics through debug gate.
print = debug_print

# Default paths
SAVE_TO = os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")
PDF_LOC = os.environ.get("AGENTICTA_PDF_LOC", "/workspace/mnt/pdfs/")

# Mock data store
_mock_curricula = {}


def _get_backend():
    """Lazy load backend functions."""
    try:
        from nodes import (
            init_user_storage,
            user_exists,
            load_user_state,
            run_for_first_time_user,
            move_to_next_chapter,
            update_subtopic_status,
        )
        from states import Status, convert_to_json_safe
        return {
            "init_user_storage": init_user_storage,
            "user_exists": user_exists,
            "load_user_state": load_user_state,
            "run_for_first_time_user": run_for_first_time_user,
            "move_to_next_chapter": move_to_next_chapter,
            "update_subtopic_status": update_subtopic_status,
            "Status": Status,
            "convert_to_json_safe": convert_to_json_safe,
            "available": True,
        }
    except ImportError:
        return {"available": False}


def _convert_status(status_value) -> Optional[StatusEnum]:
    """Convert backend status to API StatusEnum."""
    if status_value is None:
        return None
    
    # Handle Enum objects
    if hasattr(status_value, 'value'):
        return StatusEnum(status_value.value)
    
    # Handle string values
    if isinstance(status_value, str):
        try:
            return StatusEnum(status_value)
        except ValueError:
            return None
    
    return None


def _subtopic_to_response(subtopic) -> SubTopicResponse:
    """Convert backend SubTopic to API response."""
    if isinstance(subtopic, dict):
        return SubTopicResponse(
            number=subtopic.get("number", 0),
            sub_topic=subtopic.get("sub_topic", ""),
            status=_convert_status(subtopic.get("status")),
            study_material=subtopic.get("study_material"),
            display_markdown=subtopic.get("display_markdown"),
            reference=subtopic.get("reference", ""),
            quizzes=subtopic.get("quizzes"),
            feedback=subtopic.get("feedback"),
        )
    else:
        return SubTopicResponse(
            number=getattr(subtopic, "number", 0),
            sub_topic=getattr(subtopic, "sub_topic", ""),
            status=_convert_status(getattr(subtopic, "status", None)),
            study_material=getattr(subtopic, "study_material", None),
            display_markdown=getattr(subtopic, "display_markdown", None),
            reference=getattr(subtopic, "reference", ""),
            quizzes=getattr(subtopic, "quizzes", None),
            feedback=getattr(subtopic, "feedback", None),
        )


def _chapter_to_response(chapter) -> ChapterResponse:
    """Convert backend Chapter to API response."""
    if isinstance(chapter, dict):
        sub_topics = chapter.get("sub_topics", [])
        return ChapterResponse(
            number=chapter.get("number", 0),
            name=chapter.get("name", ""),
            status=_convert_status(chapter.get("status")),
            sub_topics=[_subtopic_to_response(st) for st in (sub_topics or [])],
            reference=chapter.get("reference", ""),
            pdf_loc=chapter.get("pdf_loc", ""),
            quizzes=chapter.get("quizzes"),
            feedback=chapter.get("feedback"),
        )
    else:
        sub_topics = getattr(chapter, "sub_topics", [])
        return ChapterResponse(
            number=getattr(chapter, "number", 0),
            name=getattr(chapter, "name", ""),
            status=_convert_status(getattr(chapter, "status", None)),
            sub_topics=[_subtopic_to_response(st) for st in (sub_topics or [])],
            reference=getattr(chapter, "reference", ""),
            pdf_loc=getattr(chapter, "pdf_loc", ""),
            quizzes=getattr(chapter, "quizzes", None),
            feedback=getattr(chapter, "feedback", None),
        )


def _get_mock_curriculum(user_id: str) -> dict:
    """Get or create mock curriculum for testing."""
    if user_id not in _mock_curricula:
        _mock_curricula[user_id] = {
            "active_chapter": {
                "number": 0,
                "name": "Introduction to Machine Learning",
                "status": "started",
                "sub_topics": [
                    {
                        "number": 0,
                        "sub_topic": "What is Machine Learning?",
                        "status": "started",
                        "study_material": "Machine learning is a subset of AI...",
                        "display_markdown": "# What is Machine Learning?\n\nMachine learning is a subset of AI...",
                        "reference": "intro_ml.pdf",
                        "quizzes": [],
                        "feedback": [],
                    },
                    {
                        "number": 1,
                        "sub_topic": "Types of Machine Learning",
                        "status": "NA",
                        "study_material": "There are three main types...",
                        "display_markdown": "# Types of Machine Learning\n\nThere are three main types...",
                        "reference": "intro_ml.pdf",
                        "quizzes": [],
                        "feedback": [],
                    },
                ],
                "reference": "intro_ml.pdf",
                "pdf_loc": "/workspace/mnt/pdfs/intro_ml.pdf",
                "quizzes": [],
                "feedback": [],
            },
            "next_chapter": {
                "number": 1,
                "name": "Supervised Learning",
                "status": "NA",
                "sub_topics": [],
                "reference": "supervised.pdf",
                "pdf_loc": "/workspace/mnt/pdfs/supervised.pdf",
                "quizzes": [],
                "feedback": [],
            },
            "study_plan": {
                "study_plan": [
                    {
                        "number": 0,
                        "name": "Introduction to Machine Learning",
                        "status": "started",
                        "sub_topics": [],
                        "reference": "intro_ml.pdf",
                        "pdf_loc": "/workspace/mnt/pdfs/intro_ml.pdf",
                        "quizzes": [],
                        "feedback": [],
                    },
                    {
                        "number": 1,
                        "name": "Supervised Learning",
                        "status": "NA",
                        "sub_topics": [],
                        "reference": "supervised.pdf",
                        "pdf_loc": "/workspace/mnt/pdfs/supervised.pdf",
                        "quizzes": [],
                        "feedback": [],
                    },
                ],
            },
            "status": ["progressing"],
        }
    return _mock_curricula[user_id]


@router.get("/generate-stream")
async def generate_curriculum_stream(
    user_id: str = Query(..., description="User identifier"),
    study_buddy_preference: str = Query("friendly and helpful", description="Study buddy preference"),
    study_buddy_name: str = Query("Study Buddy", description="Study buddy name"),
):
    """
    Generate a curriculum with real-time progress updates via Server-Sent Events.
    
    This performs TWO phases:
    1. RAG Ingestion: Upload PDFs to NeMo Retriever for vectorization
    2. Curriculum Creation: Generate chapters, subtopics, and study materials
    
    Progress events:
    - {"type": "start", "total_pdfs": N, "pdfs": ["file1.pdf", ...]}
    - {"type": "phase", "phase": "ingestion" | "curriculum", "message": "..."}
    - {"type": "progress", "pdf_index": 0, "pdf_name": "file.pdf", "status": "processing" | "ingesting" | "complete"}
    - {"type": "complete", "success": true, "message": "..."}
    - {"type": "error", "message": "..."}
    """
    backend = _get_backend()
    
    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            if not backend["available"]:
                # Mock mode - simulate progress
                mock_pdfs = ["chapter1.pdf", "chapter2.pdf", "chapter3.pdf"]
                yield f"data: {json.dumps({'type': 'start', 'total_pdfs': len(mock_pdfs), 'pdfs': mock_pdfs})}\n\n"
                
                for i, pdf in enumerate(mock_pdfs):
                    yield f"data: {json.dumps({'type': 'progress', 'pdf_index': i, 'pdf_name': pdf, 'status': 'processing'})}\n\n"
                    await asyncio.sleep(1.5)
                    yield f"data: {json.dumps({'type': 'progress', 'pdf_index': i, 'pdf_name': pdf, 'status': 'complete'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'complete', 'success': True, 'message': 'Mock curriculum generated'})}\n\n"
                return
            
            # Real backend mode
            backend["init_user_storage"](SAVE_TO, user_id)
            
            # Determine PDF location
            user_pdf_loc = os.path.join(SAVE_TO, user_id, "pdfs")
            if os.path.exists(user_pdf_loc) and os.listdir(user_pdf_loc):
                pdf_location = user_pdf_loc
            else:
                pdf_location = PDF_LOC
            
            # Check if PDFs exist
            if not os.path.exists(pdf_location):
                yield f"data: {json.dumps({'type': 'error', 'message': f'PDF directory not found: {pdf_location}'})}\n\n"
                return
            
            pdf_files = [f for f in os.listdir(pdf_location) if f.endswith('.pdf')]
            if not pdf_files:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No PDF files found. Please upload PDFs first.'})}\n\n"
                return
            
            # Validate PDF sizes and page counts before generation
            MAX_FILE_SIZE_MB = 4  # 4 MB file size limit
            MAX_PAGES = 50  # 50 pages limit
            
            import fitz  # PyMuPDF
            validation_errors = []
            
            for pdf_file in pdf_files:
                pdf_path = os.path.join(pdf_location, pdf_file)
                
                # Check file size
                file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                
                # Check page count
                try:
                    doc = fitz.open(pdf_path)
                    page_count = len(doc)
                    doc.close()
                except Exception as e:
                    validation_errors.append(f"{pdf_file}: Unable to read PDF ({str(e)})")
                    continue
                
                # Validate against limits
                if file_size_mb > MAX_FILE_SIZE_MB:
                    validation_errors.append(f"{pdf_file}: File too large ({file_size_mb:.1f} MB, max {MAX_FILE_SIZE_MB} MB)")
                
                if page_count > MAX_PAGES:
                    validation_errors.append(f"{pdf_file}: Too many pages ({page_count} pages, max {MAX_PAGES} pages)")
            
            # If validation errors exist, reject before generation
            if validation_errors:
                error_message = "Cannot generate curriculum - PDF validation failed:\n" + "\n".join(f"• {err}" for err in validation_errors)
                yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
                return
            
            # Send start event with PDF list
            yield f"data: {json.dumps({'type': 'start', 'total_pdfs': len(pdf_files), 'pdfs': pdf_files})}\n\n"
            
            # ============================================================
            # PHASE 1: RAG INGESTION - Ingest PDFs into Milvus FIRST
            # ============================================================
            # Milvus must index the documents before curriculum generation
            # so that RAG queries in study_material_gen() return relevant
            # context. Without this, the LLM produces short/poor responses
            # and the retry logic wastes time on backoff cycles.
            yield f"data: {json.dumps({'type': 'phase', 'phase': 'ingestion', 'message': 'Ingesting PDFs into vector store...'})}\n\n"
            
            try:
                from nemo_retriever_client_utils import (
                    fetch_collections,
                    create_collection,
                    upload_files_to_nemo_retriever,
                )

                collection_name = user_id

                # Check if collection exists AND already has chunks — skip re-ingestion
                # to avoid blocking the stream while nv-ingest reprocesses the file.
                collections_response = await fetch_collections()
                existing_map = {}
                if isinstance(collections_response, dict):
                    for c in collections_response.get("collections", []):
                        cname = c.get("collection_name", c) if isinstance(c, dict) else c
                        existing_map[cname] = c

                already_ingested = (
                    collection_name in existing_map
                    and isinstance(existing_map[collection_name], dict)
                    and existing_map[collection_name].get("num_entities", 0) > 0
                )

                if already_ingested:
                    chunk_count = existing_map[collection_name].get("num_entities", 0)
                    print(f"[generate_stream] Collection '{collection_name}' already has {chunk_count} chunks — skipping re-ingestion")
                    yield f"data: {json.dumps({'type': 'phase', 'phase': 'ingestion', 'message': f'PDF already ingested ({chunk_count} chunks) — skipping re-ingestion'})}\n\n"
                else:
                    if collection_name not in existing_map:
                        print(f"[generate_stream] Creating Milvus collection '{collection_name}'")
                        await create_collection(collection_name)

                    file_paths = [os.path.join(pdf_location, f) for f in pdf_files]
                    print(f"[generate_stream] Ingesting {len(file_paths)} PDF(s) into Milvus...")
                    await upload_files_to_nemo_retriever(file_paths, collection_name)

                    yield f"data: {json.dumps({'type': 'phase', 'phase': 'ingestion', 'message': f'Ingested {len(file_paths)} PDF(s) into vector store'})}\n\n"
                    print(f"[generate_stream] Milvus ingestion complete for {len(file_paths)} file(s)")

            except ImportError:
                print("[generate_stream] NeMo Retriever not available, skipping ingestion")
                yield f"data: {json.dumps({'type': 'phase', 'phase': 'ingestion', 'message': 'RAG ingestion skipped (module not available)'})}\n\n"
            except Exception as e:
                # Log but don't fail -- curriculum generation can still proceed
                # with degraded RAG quality.
                print(f"[generate_stream] Milvus ingestion error (non-fatal): {e}")
                yield f"data: {json.dumps({'type': 'phase', 'phase': 'ingestion', 'message': f'RAG ingestion warning: {str(e)[:100]}. Continuing with curriculum generation.'})}\n\n"
            
            # ============================================================
            # PHASE 2: CURRICULUM GENERATION - Generate chapters & study materials
            # ============================================================
            yield f"data: {json.dumps({'type': 'phase', 'phase': 'curriculum', 'message': 'Creating curriculum structure...'})}\n\n"
            
            user_dict = {
                "user_id": user_id,
                "study_buddy_preference": study_buddy_preference,
                "study_buddy_persona": None,
                "study_buddy_name": study_buddy_name,
                "curriculum": None,
            }
            
            # Mark all PDFs as uploaded first (to show progress)
            for i, pdf in enumerate(pdf_files):
                yield f"data: {json.dumps({'type': 'progress', 'pdf_index': i, 'pdf_name': pdf, 'status': 'uploaded'})}\n\n"
            
            # Mark first PDF as processing (it will get full study materials)
            yield f"data: {json.dumps({'type': 'progress', 'pdf_index': 0, 'pdf_name': pdf_files[0], 'status': 'processing'})}\n\n"
            
            # Create a progress queue so sub_topic_builder can stream updates
            subtopic_progress_queue = asyncio.Queue()

            async def subtopic_progress_callback(phase: str, message: str):
                """Called from sub_topic_builder to report subtopic-level progress."""
                await subtopic_progress_queue.put({"phase": phase, "message": message})

            # Run curriculum generation concurrently with progress draining
            async def _run_generation():
                try:
                    result = await backend["run_for_first_time_user"](
                        user=user_dict,
                        uploaded_pdf_loc=pdf_location,
                        save_to=SAVE_TO,
                        study_buddy_preference=study_buddy_preference,
                        progress_callback=subtopic_progress_callback,
                    )
                    return result
                finally:
                    # Always signal completion so the drain loop never hangs
                    await subtopic_progress_queue.put(None)

            gen_task = asyncio.create_task(_run_generation())

            # Drain progress events while generation runs.
            # Use a timeout so we never hang indefinitely if something
            # goes wrong with the sentinel.
            while True:
                try:
                    event = await asyncio.wait_for(
                        subtopic_progress_queue.get(), timeout=300.0
                    )
                except asyncio.TimeoutError:
                    print("[generate_stream] Progress queue drain timed out after 300s")
                    break
                if event is None:
                    break
                yield f"data: {json.dumps({'type': 'subtopic_progress', **event})}\n\n"

            global_state = await gen_task

            # Log generation result summary
            user_data = global_state.get("user", {}) if isinstance(global_state, dict) else {}
            curriculum_list = user_data.get("curriculum", [])
            num_chapters = 0
            if curriculum_list:
                study_plan = curriculum_list[0].get("study_plan", {}) if isinstance(curriculum_list[0], dict) else {}
                chapters = study_plan.get("study_plan", []) if isinstance(study_plan, dict) else []
                num_chapters = len(chapters)
            print(f"[generate_stream] Curriculum generation complete: {num_chapters} chapter(s) created for user '{user_id}'")

            # Mark first PDF as complete (study materials generated)
            yield f"data: {json.dumps({'type': 'progress', 'pdf_index': 0, 'pdf_name': pdf_files[0], 'status': 'complete'})}\n\n"
            
            # Mark remaining PDFs as "pending" (lazy loaded on-demand)
            for i in range(1, len(pdf_files)):
                yield f"data: {json.dumps({'type': 'progress', 'pdf_index': i, 'pdf_name': pdf_files[i], 'status': 'pending_lazy'})}\n\n"
            
            yield f"data: {json.dumps({'type': 'complete', 'success': True, 'message': 'Curriculum generated! First chapter ready, others will load on-demand.'})}\n\n"
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/add-documents-stream")
async def add_documents_stream(
    user_id: str = Query(..., description="User identifier"),
):
    """
    Add new documents to an existing user's curriculum with real-time progress updates.
    
    This is for RETURNING users who want to add more PDFs without regenerating
    their entire curriculum from scratch.
    
    Progress events:
    - {"type": "start", "total_new_pdfs": N, "new_pdfs": ["file1.pdf", ...], "existing_chapters": M}
    - {"type": "progress", "pdf_index": 0, "pdf_name": "file.pdf", "status": "pending" | "processing" | "complete"}
    - {"type": "complete", "success": true, "new_chapters": N, "total_chapters": M, "message": "..."}
    - {"type": "error", "message": "..."}
    """
    backend = _get_backend()
    
    async def add_documents_generator() -> AsyncGenerator[str, None]:
        try:
            if not backend["available"]:
                # Mock mode
                yield f"data: {json.dumps({'type': 'error', 'message': 'Backend not available in mock mode'})}\n\n"
                return
            
            # Initialize storage
            backend["init_user_storage"](SAVE_TO, user_id)
            
            # Check if user exists and has a curriculum
            if not backend["user_exists"](user_id):
                yield f"data: {json.dumps({'type': 'error', 'message': f'User {user_id} not found. Cannot add documents.'})}\n\n"
                return
            
            user_state = backend["load_user_state"](user_id)
            if not user_state or not user_state.get("curriculum"):
                yield f"data: {json.dumps({'type': 'error', 'message': 'No existing curriculum found. Use generate-stream for new users.'})}\n\n"
                return
            
            # Get user's PDF location
            user_pdf_loc = os.path.join(SAVE_TO, user_id, "pdfs")
            if not os.path.exists(user_pdf_loc):
                yield f"data: {json.dumps({'type': 'error', 'message': 'No PDF directory found. Please upload PDFs first.'})}\n\n"
                return
            
            all_pdfs = [f for f in os.listdir(user_pdf_loc) if f.endswith('.pdf')]
            if not all_pdfs:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No PDF files found in user directory.'})}\n\n"
                return
            
            # Get existing processed files to find NEW pdfs
            # Handle both dict and Pydantic object access
            curriculum_list = user_state.get("curriculum", [])
            if not curriculum_list:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No curriculum found in user state.'})}\n\n"
                return
            
            curriculum = curriculum_list[0]
            
            # Handle study_plan - could be dict or Pydantic object
            if hasattr(curriculum, 'study_plan'):
                study_plan = curriculum.study_plan
            elif isinstance(curriculum, dict):
                study_plan = curriculum.get("study_plan", {})
            else:
                study_plan = {}
            
            # Get chapters list - could be dict or Pydantic object
            if hasattr(study_plan, 'study_plan'):
                existing_chapters = study_plan.study_plan
            elif isinstance(study_plan, dict):
                existing_chapters = study_plan.get("study_plan", [])
            else:
                existing_chapters = []
            
            # Get PDF references from chapters
            existing_pdf_refs = set()
            for ch in existing_chapters:
                if hasattr(ch, 'reference'):
                    existing_pdf_refs.add(ch.reference or "")
                elif isinstance(ch, dict):
                    existing_pdf_refs.add(ch.get("reference", ""))
            
            new_pdfs = [f for f in all_pdfs if f not in existing_pdf_refs]
            
            if not new_pdfs:
                yield f"data: {json.dumps({'type': 'complete', 'success': True, 'new_chapters': 0, 'total_chapters': len(existing_chapters), 'message': 'No new documents to add. All PDFs are already in your curriculum.'})}\n\n"
                return
            
            # Validate new PDFs
            MAX_FILE_SIZE_MB = 4
            MAX_PAGES = 50
            import fitz
            validation_errors = []
            
            for pdf_file in new_pdfs:
                pdf_path = os.path.join(user_pdf_loc, pdf_file)
                file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                
                try:
                    doc = fitz.open(pdf_path)
                    page_count = len(doc)
                    doc.close()
                except Exception as e:
                    validation_errors.append(f"{pdf_file}: Unable to read PDF ({str(e)})")
                    continue
                
                if file_size_mb > MAX_FILE_SIZE_MB:
                    validation_errors.append(f"{pdf_file}: File too large ({file_size_mb:.1f} MB, max {MAX_FILE_SIZE_MB} MB)")
                if page_count > MAX_PAGES:
                    validation_errors.append(f"{pdf_file}: Too many pages ({page_count} pages, max {MAX_PAGES} pages)")
            
            if validation_errors:
                error_message = "Cannot add documents - PDF validation failed:\n" + "\n".join(f"• {err}" for err in validation_errors)
                yield f"data: {json.dumps({'type': 'error', 'message': error_message})}\n\n"
                return
            
            # Send start event
            yield f"data: {json.dumps({'type': 'start', 'total_new_pdfs': len(new_pdfs), 'new_pdfs': new_pdfs, 'existing_chapters': len(existing_chapters)})}\n\n"
            
            yield f"data: {json.dumps({'type': 'phase', 'phase': 'adding', 'message': f'Adding {len(new_pdfs)} new document(s) to curriculum...'})}\n\n"
            
            # Create progress callback for streaming updates
            progress_queue = asyncio.Queue()
            
            async def progress_callback(pdf_name, status, index, total):
                await progress_queue.put({
                    "pdf_name": pdf_name,
                    "status": status,
                    "index": index,
                    "total": total
                })
            
            # Import the add_documents function
            try:
                from nodes import add_documents_to_curriculum
            except ImportError as e:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Backend function not available: {str(e)}'})}\n\n"
                return
            
            # Run the add documents function with progress streaming
            import concurrent.futures
            
            # Since add_documents_to_curriculum is async but may have blocking parts,
            # we'll run it and poll for progress
            result = None
            add_task = asyncio.create_task(
                add_documents_to_curriculum(
                    user_id=user_id,
                    pdf_files_loc=user_pdf_loc,
                    save_to=SAVE_TO,
                    progress_callback=progress_callback
                )
            )
            
            # Poll for progress updates while task runs
            while not add_task.done():
                try:
                    progress = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps({'type': 'progress', 'pdf_index': progress['index'], 'pdf_name': progress['pdf_name'], 'status': progress['status']})}\n\n"
                except asyncio.TimeoutError:
                    # No progress update, keep waiting
                    continue
            
            # Get final result
            result = await add_task
            
            # Drain any remaining progress updates
            while not progress_queue.empty():
                progress = await progress_queue.get()
                yield f"data: {json.dumps({'type': 'progress', 'pdf_index': progress['index'], 'pdf_name': progress['pdf_name'], 'status': progress['status']})}\n\n"
            
            if result.get("success"):
                yield f"data: {json.dumps({'type': 'complete', 'success': True, 'new_chapters': len(result.get('new_chapters', [])), 'total_chapters': result.get('total_chapters', 0), 'message': result.get('message', 'Documents added successfully.')})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': result.get('message', 'Failed to add documents.')})}\n\n"
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        add_documents_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/{user_id}", response_model=CurriculumResponse)
async def get_curriculum(user_id: str):
    """
    Get the curriculum for a user.
    """
    backend = _get_backend()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        user_state = backend["load_user_state"](user_id)
        if user_state is None:
            raise HTTPException(status_code=404, detail=f"User state for '{user_id}' not found")
        
        curriculum_list = user_state.get("curriculum", [])
        if not curriculum_list or len(curriculum_list) == 0:
            raise HTTPException(
                status_code=404, 
                detail=f"No curriculum found for user '{user_id}'. Generate one first."
            )
        
        curriculum = curriculum_list[0]
        safe_curriculum = backend["convert_to_json_safe"](curriculum)
    else:
        # Use mock data
        safe_curriculum = _get_mock_curriculum(user_id)
    
    active_chapter = safe_curriculum.get("active_chapter")
    next_chapter = safe_curriculum.get("next_chapter")
    study_plan = safe_curriculum.get("study_plan")
    
    return CurriculumResponse(
        active_chapter=_chapter_to_response(active_chapter) if active_chapter else None,
        next_chapter=_chapter_to_response(next_chapter) if next_chapter else None,
        study_plan={
            "study_plan": [
                _chapter_to_response(ch) 
                for ch in (study_plan.get("study_plan", []) if study_plan else [])
            ]
        } if study_plan else None,
        status=[_convert_status(s) for s in safe_curriculum.get("status", [])] if safe_curriculum.get("status") else None,
    )


@router.post("/generate", response_model=CurriculumGenerateResponse)
async def generate_curriculum(request: CurriculumGenerateRequest):
    """
    Generate a curriculum for a user from uploaded PDFs.
    """
    backend = _get_backend()
    user_id = request.user_id
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        # Check for existing curriculum
        if backend["user_exists"](user_id):
            user_state = backend["load_user_state"](user_id)
            if user_state and user_state.get("curriculum"):
                safe_user = backend["convert_to_json_safe"](user_state)
                return CurriculumGenerateResponse(
                    success=True,
                    user=safe_user,
                    message="Curriculum already exists for this user",
                )
        
        # Determine PDF location
        user_pdf_loc = os.path.join(SAVE_TO, user_id, "pdfs")
        if os.path.exists(user_pdf_loc) and os.listdir(user_pdf_loc):
            pdf_location = user_pdf_loc
        else:
            pdf_location = PDF_LOC
        
        # Check if PDFs exist
        if not os.path.exists(pdf_location):
            raise HTTPException(
                status_code=400,
                detail=f"PDF directory not found: {pdf_location}. Please upload PDFs first."
            )
        
        pdf_files = [f for f in os.listdir(pdf_location) if f.endswith('.pdf')]
        if not pdf_files:
            raise HTTPException(
                status_code=400,
                detail=f"No PDF files found in {pdf_location}. Please upload PDFs first."
            )
        
        # Validate PDF sizes and page counts before generation
        MAX_FILE_SIZE_MB = 4  # 4 MB file size limit
        MAX_PAGES = 50  # 50 pages limit
        
        import fitz  # PyMuPDF
        validation_errors = []
        
        for pdf_file in pdf_files:
            pdf_path = os.path.join(pdf_location, pdf_file)
            
            # Check file size
            file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            
            # Check page count
            try:
                doc = fitz.open(pdf_path)
                page_count = len(doc)
                doc.close()
            except Exception as e:
                validation_errors.append(f"{pdf_file}: Unable to read PDF ({str(e)})")
                continue
            
            # Validate against limits
            if file_size_mb > MAX_FILE_SIZE_MB:
                validation_errors.append(f"{pdf_file}: File too large ({file_size_mb:.1f} MB, max {MAX_FILE_SIZE_MB} MB)")
            
            if page_count > MAX_PAGES:
                validation_errors.append(f"{pdf_file}: Too many pages ({page_count} pages, max {MAX_PAGES} pages)")
        
        # If validation errors exist, reject before generation
        if validation_errors:
            error_message = "Cannot generate curriculum - PDF validation failed:\n" + "\n".join(f"• {err}" for err in validation_errors)
            raise HTTPException(status_code=400, detail=error_message)
        
        user_dict = {
            "user_id": user_id,
            "study_buddy_preference": request.study_buddy_preference,
            "study_buddy_persona": None,
            "study_buddy_name": request.study_buddy_name,
            "curriculum": None,
        }
        
        try:
            global_state = await backend["run_for_first_time_user"](
                user=user_dict,
                uploaded_pdf_loc=pdf_location,
                save_to=SAVE_TO,
                study_buddy_preference=request.study_buddy_preference,
            )
            
            safe_state = backend["convert_to_json_safe"](global_state)
            
            return CurriculumGenerateResponse(
                success=True,
                user=safe_state.get("user"),
                message="Curriculum generated successfully",
            )
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Error generating curriculum: {str(e)}"
            )
    else:
        # Return mock curriculum
        mock_curriculum = _get_mock_curriculum(user_id)
        mock_user = {
            "user_id": user_id,
            "study_buddy_preference": request.study_buddy_preference,
            "study_buddy_persona": f"I'm your friendly study buddy! {request.study_buddy_preference}",
            "study_buddy_name": request.study_buddy_name,
            "curriculum": [mock_curriculum],
        }
        
        return CurriculumGenerateResponse(
            success=True,
            user=mock_user,
            message="Mock curriculum generated (backend unavailable)",
        )


@router.post("/{user_id}/next-chapter", response_model=NextChapterResponse)
async def next_chapter(user_id: str):
    """
    Move user to the next chapter in their curriculum.
    """
    backend = _get_backend()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        try:
            updated_user = await backend["move_to_next_chapter"](user_id, SAVE_TO)
            
            curriculum_list = updated_user.get("curriculum", [])
            if curriculum_list and len(curriculum_list) > 0:
                curriculum = curriculum_list[0]
                active_chapter = curriculum.get("active_chapter")
                
                if active_chapter:
                    safe_chapter = backend["convert_to_json_safe"](active_chapter)
                    return NextChapterResponse(
                        success=True,
                        chapter=_chapter_to_response(safe_chapter),
                        message="Moved to next chapter successfully",
                    )
            
            return NextChapterResponse(
                success=False,
                chapter=None,
                message="No next chapter available",
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error moving to next chapter: {str(e)}"
            )
    else:
        # Mock: swap active and next chapter
        curriculum = _get_mock_curriculum(user_id)
        if curriculum.get("next_chapter"):
            old_active = curriculum["active_chapter"]
            curriculum["active_chapter"] = curriculum["next_chapter"]
            curriculum["active_chapter"]["status"] = "started"
            curriculum["next_chapter"] = None
            
            return NextChapterResponse(
                success=True,
                chapter=_chapter_to_response(curriculum["active_chapter"]),
                message="Moved to next chapter (mock)",
            )
        
        return NextChapterResponse(
            success=False,
            chapter=None,
            message="No next chapter available",
        )


@router.patch("/{user_id}/subtopic/{subtopic_number}/status", response_model=SubtopicStatusUpdateResponse)
async def update_subtopic(
    user_id: str, 
    subtopic_number: int, 
    request: SubtopicStatusUpdateRequest
):
    """
    Update a subtopic's status and optionally add feedback.
    """
    backend = _get_backend()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        backend_status = backend["Status"](request.status.value)
        
        try:
            updated_user = await backend["update_subtopic_status"](
                user_id=user_id,
                save_to=SAVE_TO,
                subtopic_number=subtopic_number,
                new_status=backend_status,
                feedback=request.feedback,
            )
            
            curriculum_list = updated_user.get("curriculum", [])
            if curriculum_list and len(curriculum_list) > 0:
                curriculum = curriculum_list[0]
                active_chapter = curriculum.get("active_chapter")
                
                if active_chapter:
                    sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])
                    
                    if sub_topics and subtopic_number < len(sub_topics):
                        subtopic = sub_topics[subtopic_number]
                        safe_subtopic = backend["convert_to_json_safe"](subtopic)
                        
                        return SubtopicStatusUpdateResponse(
                            success=True,
                            subtopic=_subtopic_to_response(safe_subtopic),
                            message="Subtopic status updated successfully",
                        )
            
            return SubtopicStatusUpdateResponse(
                success=True,
                subtopic=None,
                message="Status updated but subtopic data unavailable",
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error updating subtopic status: {str(e)}"
            )
    else:
        # Mock update
        curriculum = _get_mock_curriculum(user_id)
        active_chapter = curriculum.get("active_chapter", {})
        sub_topics = active_chapter.get("sub_topics", [])
        
        if subtopic_number < len(sub_topics):
            sub_topics[subtopic_number]["status"] = request.status.value
            if request.feedback:
                sub_topics[subtopic_number]["feedback"] = request.feedback
            
            return SubtopicStatusUpdateResponse(
                success=True,
                subtopic=_subtopic_to_response(sub_topics[subtopic_number]),
                message="Subtopic status updated (mock)",
            )
        
        raise HTTPException(status_code=404, detail=f"Subtopic {subtopic_number} not found")


@router.get("/{user_id}/subtopic/{subtopic_number}", response_model=SubTopicResponse)
async def get_subtopic(user_id: str, subtopic_number: int):
    """
    Get a specific subtopic's data including study material.
    """
    backend = _get_backend()
    
    if backend["available"]:
        backend["init_user_storage"](SAVE_TO, user_id)
        
        if not backend["user_exists"](user_id):
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        
        user_state = backend["load_user_state"](user_id)
        if user_state is None:
            raise HTTPException(status_code=404, detail=f"User state for '{user_id}' not found")
        
        curriculum_list = user_state.get("curriculum", [])
        if not curriculum_list or len(curriculum_list) == 0:
            raise HTTPException(status_code=404, detail="No curriculum found")
        
        curriculum = curriculum_list[0]
        active_chapter = curriculum.get("active_chapter")
        
        if not active_chapter:
            raise HTTPException(status_code=404, detail="No active chapter found")
        
        sub_topics = active_chapter.get("sub_topics", []) if isinstance(active_chapter, dict) else getattr(active_chapter, "sub_topics", [])
        
        if not sub_topics or subtopic_number >= len(sub_topics):
            raise HTTPException(status_code=404, detail=f"Subtopic {subtopic_number} not found")
        
        subtopic = sub_topics[subtopic_number]
        safe_subtopic = backend["convert_to_json_safe"](subtopic)
        
        return _subtopic_to_response(safe_subtopic)
    else:
        # Mock data
        curriculum = _get_mock_curriculum(user_id)
        active_chapter = curriculum.get("active_chapter", {})
        sub_topics = active_chapter.get("sub_topics", [])
        
        if subtopic_number < len(sub_topics):
            return _subtopic_to_response(sub_topics[subtopic_number])
        
        raise HTTPException(status_code=404, detail=f"Subtopic {subtopic_number} not found")
