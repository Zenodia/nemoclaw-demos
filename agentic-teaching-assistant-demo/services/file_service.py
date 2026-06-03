"""
File Service - Gradio-agnostic file handling business logic.

This service handles file validation, copying, and NeMo Retriever upload.
It returns DTOs that can be converted to any UI framework format.

Usage:
    from services.file_service import FileService
    
    svc = FileService(mnt_folder="/path/to/mnt")
    result = svc.validate_files(file_paths)
    result = svc.upload_files(file_paths, username)
"""
import os
import sys
import json
import shutil
import asyncio
import time
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass, field

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from colorama import Fore

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

from nemo_retriever_client_utils import (
    delete_collections,
    fetch_collections,
    create_collection,
    upload_files_to_nemo_retriever
)


# =============================================================================
# Configuration Constants
# =============================================================================

MAX_FILES = 5
MAX_FILE_SIZE_GB = 1
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_GB * 1024 * 1024 * 1024  # 1GB in bytes
MAX_PAGES_PER_FILE = 50


# =============================================================================
# DTOs
# =============================================================================

@dataclass
class FileValidationResult:
    """Result of file validation."""
    is_valid: bool
    message: str
    validated_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class FileUploadResult:
    """Result of file upload operation."""
    success: bool
    message: str
    copied_files: List[str] = field(default_factory=list)
    uploaded_to_nemo: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# =============================================================================
# FileService
# =============================================================================

class FileService:
    """
    Gradio-agnostic file service.
    
    Handles file validation, copying, and NeMo Retriever upload.
    All methods return DTOs (dataclasses), not Gradio components.
    """
    
    def __init__(
        self,
        mnt_folder: str,
        max_files: int = MAX_FILES,
        max_file_size_gb: float = MAX_FILE_SIZE_GB,
        max_pages_per_file: int = MAX_PAGES_PER_FILE
    ):
        """
        Initialize FileService.
        
        Args:
            mnt_folder: Path to the mnt folder for user data storage
            max_files: Maximum number of files allowed
            max_file_size_gb: Maximum file size in GB
            max_pages_per_file: Maximum pages per PDF file
        """
        self.mnt_folder = mnt_folder
        self.max_files = max_files
        self.max_file_size_bytes = int(max_file_size_gb * 1024 * 1024 * 1024)
        self.max_file_size_gb = max_file_size_gb
        self.max_pages_per_file = max_pages_per_file
    
    def validate_files(self, file_paths: List[str]) -> FileValidationResult:
        """
        Validate uploaded files against size, count, and page limits.
        
        Args:
            file_paths: List of file paths to validate
            
        Returns:
            FileValidationResult with validation status
        """
        if not file_paths:
            return FileValidationResult(
                is_valid=True,
                message="",
                validated_files=[]
            )
        
        errors = []
        validated_files = []
        
        # Check number of files
        if len(file_paths) > self.max_files:
            return FileValidationResult(
                is_valid=False,
                message=f"❌ Error: You can upload a maximum of {self.max_files} files. You uploaded {len(file_paths)} files.",
                errors=[f"Too many files: {len(file_paths)} > {self.max_files}"]
            )
        
        # Check each file
        for file_path in file_paths:
            # Handle Gradio file objects
            path = file_path.name if hasattr(file_path, 'name') else file_path
            
            # Check if file exists
            if not os.path.exists(path):
                errors.append(f"File not found: {path}")
                continue
            
            # Check file size
            file_size = os.path.getsize(path)
            if file_size > self.max_file_size_bytes:
                file_size_gb = file_size / (1024 * 1024 * 1024)
                errors.append(
                    f"File '{os.path.basename(path)}' is {file_size_gb:.2f}GB. "
                    f"Maximum file size is {self.max_file_size_gb}GB."
                )
                continue
            
            # Check if it's a PDF
            if not path.lower().endswith('.pdf'):
                errors.append(f"File '{os.path.basename(path)}' is not a PDF file.")
                continue
            
            # Check page count if PyPDF2 is available
            if PdfReader is not None:
                try:
                    pdf_reader = PdfReader(path)
                    num_pages = len(pdf_reader.pages)
                    if num_pages > self.max_pages_per_file:
                        errors.append(
                            f"File '{os.path.basename(path)}' has {num_pages} pages. "
                            f"Maximum allowed is {self.max_pages_per_file} pages per file."
                        )
                        continue
                except Exception as e:
                    errors.append(f"Unable to read PDF file '{os.path.basename(path)}': {str(e)}")
                    continue
            
            validated_files.append(path)
        
        if errors:
            return FileValidationResult(
                is_valid=False,
                message="❌ " + errors[0],  # Show first error
                validated_files=validated_files,
                errors=errors
            )
        
        return FileValidationResult(
            is_valid=True,
            message=f"✅ {len(validated_files)} file(s) validated successfully!",
            validated_files=validated_files
        )
    
    def copy_files_to_user_dir(
        self,
        file_paths: List[str],
        username: str
    ) -> Tuple[List[str], str]:
        """
        Copy files to user's PDF directory.
        
        Args:
            file_paths: List of source file paths
            username: Username for directory creation
            
        Returns:
            Tuple of (copied_file_paths, pdf_directory)
        """
        pdf_dir = os.path.join(self.mnt_folder, "pdfs", username)
        user_dir = os.path.join(self.mnt_folder, username)
        
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(user_dir, exist_ok=True)
        
        copied_files = []
        for file_path in file_paths:
            path = file_path.name if hasattr(file_path, 'name') else file_path
            dest = shutil.copy(path, pdf_dir)
            copied_files.append(dest)
        
        return copied_files, pdf_dir
    
    def get_new_files_to_process(
        self,
        pdf_dir: str,
        username: str
    ) -> Tuple[List[str], List[str]]:
        """
        Determine which files are new and need processing.
        
        Args:
            pdf_dir: Directory containing PDF files
            username: Username for tracking processed files
            
        Returns:
            Tuple of (new_files_to_process, already_processed_files)
        """
        processed_files_path = os.path.join(self.mnt_folder, f"{username}_files.txt")
        processed_file = Path(processed_files_path)
        
        already_processed = []
        new_files = []
        
        if processed_file.is_file():
            with open(processed_files_path, "r") as f:
                already_processed = [line.strip() for line in f.readlines() if line.strip().endswith(".pdf")]
            
            # Find new files
            all_pdfs = [
                os.path.join(pdf_dir, f) 
                for f in os.listdir(pdf_dir) 
                if f.endswith(".pdf")
            ]
            new_files = [f for f in all_pdfs if f not in already_processed]
            
            # Append new files to processed list
            if new_files:
                with open(processed_files_path, "a") as f:
                    for file in new_files:
                        f.write(f"{file}\n")
        else:
            # First time - all files are new
            new_files = [
                os.path.join(pdf_dir, f) 
                for f in os.listdir(pdf_dir) 
                if f.endswith(".pdf")
            ]
            with open(processed_files_path, "w") as f:
                for file in new_files:
                    f.write(f"{file}\n")
        
        return new_files, already_processed
    
    async def _ensure_collection_exists(self, username: str) -> bool:
        """
        Ensure NeMo Retriever collection exists for user.
        
        Args:
            username: Collection name (user identifier)
            
        Returns:
            True if collection exists or was created
        """
        metadata_schema = [
            {
                "name": "source_ref",
                "type": "string",
                "description": "Reference name to the source pdf document"
            }
        ]
        
        output_collection = await fetch_collections()
        
        # fetch_collections() returns dict (or empty dict on error)
        if isinstance(output_collection, str):
            try:
                output_collection = json.loads(output_collection)
            except json.JSONDecodeError:
                print(Fore.RED + f"Failed to parse collections response: {output_collection[:100]}" + Fore.RESET)
                output_collection = {}
        
        # Check if collection exists
        collections = output_collection.get("collections", []) if isinstance(output_collection, dict) else []
        existing = [c for c in collections if isinstance(c, dict) and c.get("collection_name") == username]
        
        if existing:
            print(Fore.YELLOW + f"Collection for user {username} already exists." + Fore.RESET)
            return True
        else:
            print(Fore.YELLOW + f"Creating new collection: {username}" + Fore.RESET)
            await create_collection(
                collection_name=username,
                metadata_schema=metadata_schema
            )
            time.sleep(10)  # Wait for collection creation
            return True
    
    async def _upload_to_nemo_retriever(
        self,
        file_paths: List[str],
        username: str
    ) -> dict:
        """
        Upload files to NeMo Retriever.
        
        Args:
            file_paths: List of file paths to upload
            username: Collection name
            
        Returns:
            Upload result from NeMo Retriever
        """
        if not file_paths:
            return {"status": "skipped", "message": "No new files to upload"}
        
        result = await upload_files_to_nemo_retriever(file_paths, username, [])
        return result
    
    def upload_files(
        self,
        file_paths: List[str],
        username: str,
        start_fresh: bool = False
    ) -> FileUploadResult:
        """
        Complete file upload workflow: validate, copy, and upload to NeMo Retriever.
        
        Args:
            file_paths: List of file paths to upload
            username: Username for user-specific storage
            start_fresh: If True, delete existing collection first
            
        Returns:
            FileUploadResult with complete status
        """
        if not file_paths:
            return FileUploadResult(
                success=True,
                message=""
            )
        
        errors = []
        
        # Step 1: Validate files
        validation = self.validate_files(file_paths)
        if not validation.is_valid:
            return FileUploadResult(
                success=False,
                message=validation.message,
                errors=validation.errors
            )
        
        try:
            # Step 2: Copy files to user directory
            print(Fore.BLUE + f"mnt_folder = {self.mnt_folder}, username = {username}" + Fore.RESET)
            copied_files, pdf_dir = self.copy_files_to_user_dir(file_paths, username)
            print(Fore.BLUE + f"Copied files to pdf_dir: {copied_files}" + Fore.RESET)
            
            # Step 3: Determine new files
            new_files, already_processed = self.get_new_files_to_process(pdf_dir, username)
            print(Fore.CYAN + f"New files to process: {new_files}" + Fore.RESET)
            print(Fore.CYAN + f"Already processed: {already_processed}" + Fore.RESET)
            
            # Step 4: Delete existing collection if start_fresh
            if start_fresh:
                asyncio.run(delete_collections([username, "metadata_schema", "meta"]))
                time.sleep(10)
            
            # Step 5: Ensure collection exists
            asyncio.run(self._ensure_collection_exists(username))
            
            # Step 6: Upload new files to NeMo Retriever
            nemo_result = None
            if new_files:
                nemo_result = asyncio.run(self._upload_to_nemo_retriever(new_files, username))
                print(Fore.BLUE + f"NeMo Retriever upload result: {nemo_result}" + Fore.RESET)
                time.sleep(20)  # Wait for processing
            else:
                print(Fore.YELLOW + "No new files to upload, skipping NeMo upload" + Fore.RESET)
            
            return FileUploadResult(
                success=True,
                message=validation.message,
                copied_files=copied_files,
                uploaded_to_nemo=new_files,
                skipped_files=already_processed
            )
            
        except Exception as e:
            print(Fore.RED + f"Error during file upload: {e}" + Fore.RESET)
            import traceback
            traceback.print_exc()
            return FileUploadResult(
                success=False,
                message=f"❌ Error during upload: {str(e)}",
                errors=[str(e)]
            )
    
    def get_uploaded_files(self, username: str) -> List[str]:
        """
        Get list of files uploaded by a user.
        
        Args:
            username: Username to check
            
        Returns:
            List of uploaded file paths
        """
        pdf_dir = os.path.join(self.mnt_folder, "pdfs", username)
        
        if not os.path.exists(pdf_dir):
            return []
        
        return [
            os.path.join(pdf_dir, f)
            for f in os.listdir(pdf_dir)
            if f.endswith(".pdf")
        ]

