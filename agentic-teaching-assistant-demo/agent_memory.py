import os
import json
import uuid
import re
import time
import subprocess
import tempfile
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from colorama import Fore
from enum import Enum
from dataclasses import dataclass

from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from llm import create_llm
import asyncio
import yaml


class PeriodType(Enum):
    """Period types for hierarchical memory compaction."""
    DIRECT = "just now"
    DAILY = "today"
    WEEKLY = "this week"
    MONTHLY = "this month"


@dataclass
class PeriodMeta:
    """Metadata for each period type."""
    max_length: str
    focus: str
    time_period: str
    example: str


# Period metadata configuration (aligned with teaching Skills4Claude.pdf — skills, progressive disclosure, SKILL.md, agent workflows)
PERIOD_META: Dict[PeriodType, PeriodMeta] = {
    PeriodType.DIRECT: PeriodMeta(
        max_length="1-2 sentences",
        focus="""
- which **Skills4Claude** subtopic or section we were on (e.g. when to use a skill, SKILL.md structure, progressive disclosure, hooks/rules vs skills)
- the **top ideas** the learner needs to retain from this exchange (at most three)
- **misconceptions** or quiz/chat mistakes tied to that material
- anything **new from tools** (RAG quotes, uploads, quiz results) that should carry forward — ignore duplicate tool noise; only net-new facts

Since tool calls might have several repeated calls, make sure to only summarize content taken based on the NEW information from the tools.
""",
        time_period="just now",
        example="""
- We clarified that a skill should stay thin in the main body and push detail into referenced files; the learner confused that with putting everything in one giant SKILL.md.
- They asked me to fold their uploaded diagram into the notes for the “evaluating when to add a skill” section and to book two hours Friday morning to finish the next chapter.
"""
    ),
    PeriodType.DAILY: PeriodMeta(
        max_length="2-3 sentences",
        focus="""
- **progress** through the Skills4Claude curriculum today (chapters / subtopics completed or revisited)
- **confidence vs struggle** (frustration, “I get it now”, shaky quiz performance)
- **concrete wins** (e.g. they drafted a skill outline, named trigger phrases, or compared skills to MCP)
- what should **roll forward** for the rest of the week (review items, open questions, next study focus)
""",
        time_period="today",
        example="""
- Today we worked through progressive disclosure; the learner nailed the idea of loading heavy reference only when needed but stumbled on naming conventions for supporting files under the skill folder.
- They completed the quiz on “when not to add a skill” with mixed results and asked for a short recap before tomorrow; I noted they want to tie skills back to their own repo layout next session.
- They felt overwhelmed comparing hooks/rules to skills until we mapped each to a concrete workflow; by the end they could articulate one example where a skill is the better fit.
"""
    ),
    PeriodType.WEEKLY: PeriodMeta(
        max_length="3-4 sentences",
        focus="""
- **arc across sessions**: how far they moved through Skills4Claude material and whether pace matched their goal
- **patterns**: recurring gaps (e.g. frontmatter, triggers, testing skills in isolation) vs steady improvements
- **study habits**: show-up rate, homework between sessions, use of quizzes vs chat-only review
- what to **prioritize next week** and any **longer-horizon** reminders (month/year) if the learner stated them
""",
        time_period="this week",
        example="""
- This week we held four sessions on Skills4Claude; the learner moved from “what belongs in a skill” to drafting a real SKILL.md skeleton, though they still conflate MCP tool wiring with skill content in two of three practice prompts.
- Quiz scores improved on progressive disclosure but flat on lifecycle/maintenance questions; I am steering next week toward versioning skills and when to split vs merge files.
- They missed one planned block due to work travel but sent two async questions about hook scripts vs skills; I answered both and we agreed to resume with the “testing and iterating skills” section when they return.
"""
    ),
}


class MemoryHandler:
    """
    Enhanced Memory Handler with LLM-based fact extraction and intelligent routing.
    
    Based on: https://github.com/Zenodia/standalone_agent_memory/blob/main/MemoryManager.py
    """
    
    def __init__(
        self, 
        username: str, 
        llm=None,
        memory_dir: str = None,
        use_streaming: bool = False,
        rate_limit_delay: float = 2.0,  # Delay between LLM calls to avoid rate limits
        summary_interval: int = 10  # Create summaries every N turns
    ):
        """
        Initialize the Enhanced Memory Handler.
        
        Args:
            username: User ID for memory storage
            llm: LLM instance for LLM operations (ChatOpenAI via create_llm)
            memory_dir: Directory to store memory files
            use_streaming: Whether to use streaming for LLM responses
            rate_limit_delay: Seconds to wait between LLM calls (default 2.0)
            summary_interval: Create summaries every N turns (default 10)
        """
        self.username = username
        self.user_id = username  # Alias for compatibility
        self.current_input = ""
        self.use_streaming = use_streaming
        self.datetime = datetime.now().strftime("%Y-%m-%d")
        self.config = None
        self.rate_limit_delay = rate_limit_delay
        self.last_llm_call_time = 0  # Track last LLM call for rate limiting
        self.turn_counter = 0  # Track conversation turns
        self.background_tasks = []  # Track background summarization tasks
        self.summary_interval = summary_interval  # Create summaries every N turns
        
        # Set up memory directory
        if memory_dir is None:
            try:
                docker_compose_path = Path("/workspace/docker-compose.yml")
                if docker_compose_path.exists():
                    with open(docker_compose_path, "r") as f:
                        yaml_data = yaml.safe_load(f)
                        mnt_folder = yaml_data["services"]["agenticta"]["volumes"][-1].split(":")[-1]
                        memory_dir = os.path.join(mnt_folder, username, "memory")
                else:
                    memory_dir = os.path.join("mnt", username, "memory")
            except Exception as e:
                print(Fore.YELLOW + f"Could not load mnt_folder from docker-compose.yml: {e}", Fore.RESET)
                memory_dir = os.path.join("mnt", username, "memory")
        
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.memory_dir / f"{username}_conversation_memory.txt"
        
        # Initialize LLM
        if llm is None:
            self.llm = create_llm("memory_extraction")
        else:
            self.llm = llm
        
        # Memory settings (NO VECTOR STORE - pure text-based)
        self.summary = ""
        self._all_interactions = []  # Store raw interactions for text file
        self._last_saved_turn = 0  # Track last saved turn for append-only updates
        
        # Create memory extraction chain with Orin-style prompt
        memory_extract_prompt = """You are the **teaching assistant** for a learner working through **Skills4Claude.pdf** (Claude skills: progressive disclosure, SKILL.md and supporting files, when and how to use skills with agents, hooks/rules vs skills, and related practice).

You are writing **your own session memory** for the window: **{time_period}**. Use **first person** as the assistant (e.g. "We covered…", "They asked…", "I explained…", "They confused…"). Stay grounded in the teaching interaction, not in marketing tone.

Keep your summary to **{max_length}** maximum.

Here is your past memory if you'd like to incorporate any aspects of it into your response.
Do not summarize this or include it in your response – this is just background information:

— BEGIN BACKGROUND INFORMATION —
{existing_memory}
— END BACKGROUND INFORMATION —

This is the new content that you must summarize:
{content}

For your summary, prioritize:
{focus}

The tone and granularity should resemble these examples (adapt to facts actually present; do not copy unrelated scenarios):
{example}

CRITICAL: Only use information explicitly stated in the new content (and names/dates already in background if the user confirmed them). Do NOT invent file paths, quiz scores, or learner commitments.

Your summary:
"""
        
        extract_prompt_template = PromptTemplate(
            input_variables=["time_period", "max_length", "existing_memory", "content", "focus", "example"],
            template=memory_extract_prompt,
        )
        self.mem_extract_chain = (extract_prompt_template | self.llm | StrOutputParser())
        
        # Defer memory load — don't block __init__ with file I/O.
        # load_memory_from_file() is called lazily on first access via _ensure_loaded().
        self._memory_loaded = False

        print(Fore.GREEN + f"✓ Text-Based Memory Handler initialized for user: {username}", Fore.RESET)
        print(Fore.CYAN + f"  Memory file: {self.memory_file}", Fore.RESET)
        print(Fore.CYAN + f"  Mode: Plain text with grep-friendly anchors (NO vector store)", Fore.RESET)
    
    async def _rate_limit_wait(self):
        """Wait to avoid rate limits between LLM calls."""
        if self.last_llm_call_time > 0:
            elapsed = time.time() - self.last_llm_call_time
            if elapsed < self.rate_limit_delay:
                wait_time = self.rate_limit_delay - elapsed
                print(Fore.YELLOW + f"Rate limiting: waiting {wait_time:.1f}s...", Fore.RESET)
                await asyncio.sleep(wait_time)
    
    def cleanup_background_tasks(self):
        """Remove completed background tasks from tracking list."""
        self.background_tasks = [task for task in self.background_tasks if not task.done()]
    
    async def wait_for_background_tasks(self, timeout: float = None):
        """
        Wait for all background summarization tasks to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)
        """
        if not self.background_tasks:
            return
        
        print(Fore.CYAN + f"Waiting for {len(self.background_tasks)} background tasks...", Fore.RESET)
        
        try:
            if timeout:
                await asyncio.wait_for(
                    asyncio.gather(*self.background_tasks, return_exceptions=True),
                    timeout=timeout
                )
            else:
                await asyncio.gather(*self.background_tasks, return_exceptions=True)
            
            print(Fore.GREEN + "✓ All background tasks completed", Fore.RESET)
        except asyncio.TimeoutError:
            print(Fore.YELLOW + f"Warning: Some background tasks timed out after {timeout}s", Fore.RESET)
        finally:
            self.cleanup_background_tasks()
    
    async def _background_summarize_and_update(
        self,
        turn_number: int,
        content: str,
        period_type: PeriodType,
        existing_memory: str
    ):
        """
        Background task: Create summary and update interaction.
        
        Args:
            turn_number: Turn number to update
            content: Content to summarize
            period_type: Period type for summary
            existing_memory: Existing memory context
        """
        try:
            # Create the summary
            summary = await self.create_memory_summary(
                content=content,
                period_type=period_type,
                existing_memory=existing_memory
            )
            
            # Update the interaction with the summary
            if summary:
                self.update_interaction_summary(turn_number, summary)
        except Exception as e:
            print(Fore.RED + f"Error in background summarization for turn {turn_number}: {e}", Fore.RESET)
    
    async def create_memory_summary(
        self, 
        content: str, 
        period_type: PeriodType = PeriodType.DIRECT,
        existing_memory: str = "None",
        max_retries: int = 3
    ) -> str:
        """
        Create a memory summary for a given period type using LLM with retry logic.
        
        Args:
            content: The new content to summarize
            period_type: The period type (DIRECT, DAILY, WEEKLY, MONTHLY)
            existing_memory: Previous memory to incorporate (optional)
            max_retries: Number of retry attempts on rate limit
            
        Returns:
            Summary string
        """
        # Rate limiting: wait if needed
        await self._rate_limit_wait()
        
        # Get period metadata
        meta = PERIOD_META[period_type]
        
        output = ""
        inputs = {
            "time_period": meta.time_period,
            "max_length": meta.max_length,
            "existing_memory": existing_memory,
            "content": content,
            "focus": meta.focus,
            "example": meta.example
        }
        
        # Retry logic for rate limits
        for attempt in range(max_retries):
            try:
                # Use astream for streaming-compatible execution
                async for chunk in self.mem_extract_chain.astream(inputs):
                    if chunk:
                        output += str(chunk)
                
                # Update last call time on success
                self.last_llm_call_time = time.time()
                break
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg:
                    wait_time = (attempt + 1) * 5  # 5, 10, 15 seconds
                    print(Fore.YELLOW + f"Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...", Fore.RESET)
                    await asyncio.sleep(wait_time)
                    if attempt == max_retries - 1:
                        print(Fore.RED + f"Max retries reached for memory summary. Returning empty summary.", Fore.RESET)
                        return ""
                else:
                    print(Fore.RED + f"Error creating memory summary: {e}", Fore.RESET)
                    return ""
        
        summary = output.strip()
        print(Fore.LIGHTMAGENTA_EX + f"Created {period_type.value} memory summary ({len(summary)} chars)", Fore.RESET)
        return summary
    
    def add_interaction(self, user_msg: str, bot_msg: str, turn_number: int, summary: str = "") -> Dict[str, Any]:
        """
        Add a conversation interaction to memory (plain text storage).

        Args:
            user_msg: User message
            bot_msg: Bot response
            turn_number: Conversation turn number
            summary: Optional summary of the interaction

        Returns:
            Dictionary with interaction data
        """
        self._ensure_loaded()
        interaction = {
            "turn": turn_number,
            "timestamp": datetime.now().isoformat(),
            "date": self.datetime,
            "user_id": self.user_id,
            "user_message": user_msg,
            "bot_message": bot_msg,
            "summary": summary,
            "id": str(uuid.uuid4())
        }

        self._all_interactions.append(interaction)
        print(Fore.GREEN + f"✓ Added interaction turn #{turn_number} to memory", Fore.RESET)
        
        # Auto-save to file
        self.save_memory_to_file()
        
        return interaction
    
    def update_interaction_summary(self, turn_number: int, summary: str) -> bool:
        """
        Update the summary for an existing interaction (called by background task).
        Uses sed to update in-place for efficiency.
        
        Args:
            turn_number: Turn number to update
            summary: New summary text
            
        Returns:
            True if updated successfully
        """
        for interaction in self._all_interactions:
            if interaction['turn'] == turn_number:
                interaction['summary'] = summary
                print(Fore.LIGHTMAGENTA_EX + f"✓ Updated summary for turn #{turn_number} (background)", Fore.RESET)
                
                # Update summary in file using sed (more efficient than rewriting)
                if self.memory_file.exists():
                    self._update_turn_summary_in_file(turn_number, summary)
                else:
                    # File doesn't exist yet, just save normally
                    self.save_memory_to_file()
                
                return True
        
        print(Fore.YELLOW + f"Warning: Could not find turn #{turn_number} to update", Fore.RESET)
        return False
    
    def _update_turn_summary_in_file(self, turn_number: int, summary: str) -> None:
        """
        Update a turn's summary in the file using sed and temp files.
        Strategy: Delete old summary (if exists), then insert new one using awk.
        """
        file_path = str(self.memory_file)
        turn_str = f"{turn_number:04d}"
        
        # Create backup before modifying
        backup_path = f"{file_path}.backup"
        try:
            subprocess.run(['cp', file_path, backup_path], check=True, capture_output=True)
        except Exception as e:
            print(Fore.YELLOW + f"Warning: Could not create backup: {e}", Fore.RESET)
        
        try:
            # Check if summary already exists for this turn
            result = subprocess.run(
                ['grep', '-q', f'>>>SUMMARY:{turn_str}>>>', file_path],
                capture_output=True
            )
            
            if result.returncode == 0:
                # Summary exists, delete it first using sed
                result = subprocess.run(
                    ['sed', '-i.bak', f'/>>>SUMMARY:{turn_str}>>>/,/<<<SUMMARY:{turn_str}<<</d', file_path],
                    check=False,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    print(Fore.YELLOW + f"Warning: sed delete failed: {result.stderr}", Fore.RESET)
                    raise Exception(f"sed delete failed: {result.stderr}")
            
            # Create temp file with the summary block to insert
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmp:
                tmp.write(f">>>SUMMARY:{turn_str}>>>\n")
                tmp.write(f"{summary}\n")
                tmp.write(f"<<<SUMMARY:{turn_str}<<<\n")
                tmp.write("\n")
                tmp_path = tmp.name
            
            try:
                # Use awk to insert the summary before <<<END_TURN:turn_str>>>
                # This avoids all the escaping issues with sed
                result = subprocess.run(
                    ['bash', '-c',
                     f'awk \'BEGIN{{inserted=0}} /<<<END_TURN:{turn_str}>>>/ && inserted==0 {{system("cat {tmp_path}"); inserted=1}} {{print}}\' {file_path} > {file_path}.tmp && mv {file_path}.tmp {file_path}'],
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    print(Fore.RED + f"Error: awk command failed: {result.stderr}", Fore.RESET)
                    raise Exception(f"awk failed: {result.stderr}")
                
                # Verify the file still has all turns
                verify_result = subprocess.run(
                    ['grep', '-c', '<<<TURN:', file_path],
                    capture_output=True,
                    text=True
                )
                turn_count = int(verify_result.stdout.strip()) if verify_result.returncode == 0 else 0
                expected_count = len(self._all_interactions)
                
                if turn_count != expected_count:
                    print(Fore.RED + f"Error: Turn count mismatch! Expected {expected_count}, found {turn_count}", Fore.RESET)
                    print(Fore.YELLOW + f"Restoring from backup...", Fore.RESET)
                    subprocess.run(['cp', backup_path, file_path], check=True, capture_output=True)
                    raise Exception(f"Turn count mismatch after update")
                
                print(Fore.LIGHTCYAN_EX + f"✓ Updated summary in file for turn #{turn_number} using awk", Fore.RESET)
                
                # Remove backup on success
                if os.path.exists(backup_path):
                    os.unlink(backup_path)
                
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
        except Exception as e:
            print(Fore.YELLOW + f"Warning: Could not update summary with subprocess: {e}", Fore.RESET)
            print(Fore.YELLOW + f"Restoring from backup and falling back to full rewrite...", Fore.RESET)
            
            # Restore from backup
            if os.path.exists(backup_path):
                try:
                    subprocess.run(['cp', backup_path, file_path], check=True, capture_output=True)
                    print(Fore.GREEN + f"✓ Restored from backup", Fore.RESET)
                except:
                    pass
            
            # Fallback: mark turns from this one onwards as needing re-save
            if turn_number <= self._last_saved_turn:
                self._last_saved_turn = turn_number - 1
            self.save_memory_to_file()
        finally:
            # Clean up backup file if it still exists
            if os.path.exists(backup_path):
                try:
                    os.unlink(backup_path)
                except:
                    pass
    
    def search_text_file(self, pattern: str, case_sensitive: bool = False) -> List[str]:
        """
        Search the memory text file using subprocess with grep.
        
        Args:
            pattern: Regex pattern to search for
            case_sensitive: Whether search is case sensitive
            
        Returns:
            List of matching lines
        """
        if not self.memory_file.exists():
            return []
        
        try:
            # Build grep command
            grep_cmd = ['grep']
            if not case_sensitive:
                grep_cmd.append('-i')  # case insensitive
            grep_cmd.extend(['-E', pattern, str(self.memory_file)])  # Extended regex
            
            # Run grep command
            result = subprocess.run(
                grep_cmd,
                capture_output=True,
                text=True,
                check=False  # Don't raise exception if no matches (exit code 1)
            )
            
            # grep returns exit code 1 if no matches found, which is not an error
            if result.returncode == 0:
                matches = result.stdout.strip().split('\n')
                matches = [m for m in matches if m]  # Filter empty strings
            elif result.returncode == 1:
                matches = []  # No matches found
            else:
                # Actual error occurred
                print(Fore.RED + f"grep error: {result.stderr}", Fore.RESET)
                return []
            
            print(Fore.CYAN + f"Found {len(matches)} matches for pattern: {pattern}", Fore.RESET)
            return matches
            
        except Exception as e:
            print(Fore.RED + f"Error searching text file with grep: {e}", Fore.RESET)
            return []
    
    def save_memory_to_file(self) -> bool:
        """Save interactions to file using subprocess (efficient append for existing files)."""
        try:
            if not hasattr(self, '_all_interactions'):
                self._all_interactions = []
            
            file_path = str(self.memory_file)
            file_exists = self.memory_file.exists()
            
            if not file_exists:
                # First time: Create complete file structure using echo and redirection
                self._create_new_memory_file()
            else:
                # File exists: Update metadata and append only new turns
                self._append_to_memory_file()
            
            # Verify file integrity after save
            if not self.verify_file_integrity():
                print(Fore.YELLOW + "File integrity check failed, attempting repair...", Fore.RESET)
                # Force full rewrite as repair
                self._last_saved_turn = 0
                self._create_new_memory_file()
                # Verify again
                if not self.verify_file_integrity():
                    print(Fore.RED + "✗ Repair failed - file may be corrupted", Fore.RESET)
                    return False
                else:
                    print(Fore.GREEN + "✓ File repaired successfully", Fore.RESET)
            
            print(Fore.GREEN + f"✓ Saved {len(self._all_interactions)} interactions to {self.memory_file.name}", Fore.RESET)
            print(Fore.CYAN + f"  Use grep '<<<TURN:' to find all turns", Fore.RESET)
            print(Fore.CYAN + f"  Use grep '>>>USER:' to find all user messages", Fore.RESET)
            return True
            
        except Exception as e:
            print(Fore.RED + f"Error saving memories to file: {e}", Fore.RESET)
            import traceback
            traceback.print_exc()
            return False
    
    def _create_new_memory_file(self) -> None:
        """Create new memory file from scratch (using temp file + mv for atomicity)."""
        # Build the complete file content
        lines = []
        lines.append("@@@MEMORY_LOG_START@@@")
        lines.append(f"@USERNAME:{self.username}@")
        lines.append(f"@USER_ID:{self.user_id}@")
        lines.append(f"@LAST_UPDATED:{datetime.now().isoformat()}@")
        lines.append(f"@TOTAL_TURNS:{len(self._all_interactions)}@")
        lines.append("=" * 80)
        
        # Summary section (with no extra empty line before it)
        if self.summary:
            lines.append("###SUMMARY_START###")
            lines.append(self.summary)
            lines.append("###SUMMARY_END###")
            lines.append("")  # One empty line after summary
        
        # Turns section
        lines.append(f">>>TURNS_START<<< (Total: {len(self._all_interactions)})")
        lines.append("=" * 80)
        lines.append("")
        
        # Add all interactions
        for interaction in self._all_interactions:
            lines.extend(self._format_interaction(interaction))
        
        lines.append(">>>TURNS_END<<<")
        lines.append("@@@MEMORY_LOG_END@@@")
        
        content = '\n'.join(lines)
        
        # Write to temp file then use mv for atomic operation
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', dir=self.memory_dir) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            # Use mv command to atomically move temp file to final location
            subprocess.run(
                ['mv', tmp_path, str(self.memory_file)],
                check=True,
                capture_output=True
            )
            
            self._last_saved_turn = max([i['turn'] for i in self._all_interactions]) if self._all_interactions else 0
            print(Fore.LIGHTCYAN_EX + f"✓ Created new memory file with {len(self._all_interactions)} turns", Fore.RESET)
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise e
    
    def _append_to_memory_file(self) -> None:
        """Append new interactions to existing file using sed and echo."""
        file_path = str(self.memory_file)
        
        # Create backup before any modifications
        backup_path = f"{file_path}.backup"
        try:
            subprocess.run(['cp', file_path, backup_path], check=True, capture_output=True)
        except Exception as e:
            print(Fore.YELLOW + f"Warning: Could not create backup: {e}", Fore.RESET)
        
        try:
            # Update LAST_UPDATED using sed -i
            timestamp = datetime.now().isoformat()
            subprocess.run(
                ['sed', '-i', f's/@LAST_UPDATED:[^@]*@/@LAST_UPDATED:{timestamp}@/', file_path],
                check=True,
                capture_output=True
            )
            
            # Update TOTAL_TURNS using sed -i
            total_turns = len(self._all_interactions)
            subprocess.run(
                ['sed', '-i', f's/@TOTAL_TURNS:[^@]*@/@TOTAL_TURNS:{total_turns}@/', file_path],
                check=True,
                capture_output=True
            )
            
            # Update TURNS_START line using sed -i
            subprocess.run(
                ['sed', '-i', f's/>>>TURNS_START<<< (Total: [0-9]*)/>>>TURNS_START<<< (Total: {total_turns})/', file_path],
                check=True,
                capture_output=True
            )
            
            # Update summary section if it changed (use temp file approach to avoid escaping issues)
            if self.summary:
                # Check if summary section exists
                result = subprocess.run(
                    ['grep', '-q', '###SUMMARY_START###', file_path],
                    capture_output=True
                )
                
                # Create temp file with new summary (includes trailing blank line)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmp:
                    tmp.write(f"###SUMMARY_START###\n{self.summary}\n###SUMMARY_END###\n\n")
                    summary_tmp_path = tmp.name
                
                try:
                    if result.returncode == 0:
                        # Summary exists, delete old one INCLUDING trailing empty lines
                        # Use awk to delete from ###SUMMARY_START### to ###SUMMARY_END### 
                        # AND any consecutive empty lines that follow
                        subprocess.run(
                            ['bash', '-c',
                             f'awk \'/^###SUMMARY_START###$/{{skip=1}} skip==1 && /^###SUMMARY_END###$/{{skip=2; next}} skip==2 && /^$/ {{next}} skip==2 && /[^[:space:]]/ {{skip=0}} skip==0{{print}}\' {file_path} > {file_path}.tmp && mv {file_path}.tmp {file_path}'],
                            check=True,
                            capture_output=True,
                            text=True
                        )
                    
                    # Insert new summary after the header (after first line of 80 equals signs)
                    # The temp file already contains the trailing blank line, so don't add another one
                    subprocess.run(
                        ['bash', '-c', 
                         f'awk \'BEGIN{{found=0}} /^================================================================================$/ && found==0 {{print; system("cat {summary_tmp_path}"); found=1; next}} {{print}}\' {file_path} > {file_path}.tmp && mv {file_path}.tmp {file_path}'],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                finally:
                    # Clean up temp file
                    if os.path.exists(summary_tmp_path):
                        os.unlink(summary_tmp_path)
            
            # Append only NEW turns (after _last_saved_turn)
            new_interactions = [i for i in self._all_interactions if i['turn'] > self._last_saved_turn]
            
            if new_interactions:
                # Build content for new turns
                new_lines = []
                for interaction in new_interactions:
                    new_lines.extend(self._format_interaction(interaction))
                
                new_content = '\n'.join(new_lines)
                
                # Create temporary file with new content
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', dir=self.memory_dir) as tmp:
                    tmp.write(new_content + '\n')
                    tmp_path = tmp.name
                
                try:
                    # Insert new turns before the ending markers using sed
                    # This removes the ending markers, appends new content, then re-adds markers
                    subprocess.run(
                        ['sed', '-i', '/>>>TURNS_END<<</d', file_path],
                        check=True,
                        capture_output=True
                    )
                    subprocess.run(
                        ['sed', '-i', '/@@@MEMORY_LOG_END@@@/d', file_path],
                        check=True,
                        capture_output=True
                    )
                    
                    # Append new turns using cat
                    subprocess.run(
                        ['bash', '-c', f'cat {subprocess.list2cmdline([tmp_path])} >> {subprocess.list2cmdline([file_path])}'],
                        check=True,
                        capture_output=True
                    )
                    
                    # Re-add ending markers using echo
                    with open(file_path, 'a') as f:
                        f.write(">>>TURNS_END<<<\n")
                        f.write("@@@MEMORY_LOG_END@@@\n")
                    
                    # Verify the file integrity
                    verify_result = subprocess.run(
                        ['grep', '-c', '<<<TURN:', file_path],
                        capture_output=True,
                        text=True
                    )
                    turn_count = int(verify_result.stdout.strip()) if verify_result.returncode == 0 else 0
                    expected_count = len(self._all_interactions)
                    
                    if turn_count != expected_count:
                        print(Fore.RED + f"Error: Turn count mismatch! Expected {expected_count}, found {turn_count}", Fore.RESET)
                        print(Fore.YELLOW + f"Restoring from backup and doing full rewrite...", Fore.RESET)
                        # Restore from backup
                        if os.path.exists(backup_path):
                            subprocess.run(['cp', backup_path, file_path], check=True, capture_output=True)
                        # Force full rewrite
                        self._last_saved_turn = 0
                        self._create_new_memory_file()
                        return
                    
                    self._last_saved_turn = max([i['turn'] for i in self._all_interactions])
                    print(Fore.LIGHTCYAN_EX + f"✓ Appended {len(new_interactions)} new turn(s) to memory file", Fore.RESET)
                    
                    # Remove backup on success
                    if os.path.exists(backup_path):
                        os.unlink(backup_path)
                    
                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            else:
                print(Fore.LIGHTCYAN_EX + f"✓ Updated metadata (no new turns to append)", Fore.RESET)
                # Remove backup if no new turns
                if os.path.exists(backup_path):
                    os.unlink(backup_path)
        
        except Exception as e:
            print(Fore.RED + f"Error in _append_to_memory_file: {e}", Fore.RESET)
            # Restore from backup on error
            if os.path.exists(backup_path):
                try:
                    subprocess.run(['cp', backup_path, file_path], check=True, capture_output=True)
                    print(Fore.GREEN + f"✓ Restored from backup", Fore.RESET)
                except Exception as restore_error:
                    print(Fore.RED + f"Error restoring backup: {restore_error}", Fore.RESET)
            raise
        finally:
            # Clean up backup file if it still exists
            if os.path.exists(backup_path):
                try:
                    os.unlink(backup_path)
                except:
                    pass
    
    def _format_interaction(self, interaction: Dict[str, Any]) -> List[str]:
        """Format a single interaction into lines for file output."""
        turn_num = interaction['turn']
        lines = []
        
        # Turn marker
        lines.append(f"<<<TURN:{turn_num:04d}>>>")
        lines.append(f"@TURN_ID:{interaction['id']}@")
        lines.append(f"@TIMESTAMP:{interaction['timestamp']}@")
        lines.append(f"@DATE:{interaction['date']}@")
        lines.append(f"@USER_ID:{interaction['user_id']}@")
        lines.append("-" * 80)
        
        # User message
        lines.append(f">>>USER:{turn_num:04d}>>>")
        lines.append(interaction['user_message'])
        lines.append(f"<<<USER:{turn_num:04d}<<<")
        lines.append("")
        
        # Bot message
        lines.append(f">>>BOT:{turn_num:04d}>>>")
        lines.append(interaction['bot_message'])
        lines.append(f"<<<BOT:{turn_num:04d}<<<")
        lines.append("")
        
        # Summary if available
        if interaction.get('summary'):
            lines.append(f">>>SUMMARY:{turn_num:04d}>>>")
            lines.append(interaction['summary'])
            lines.append(f"<<<SUMMARY:{turn_num:04d}<<<")
            lines.append("")
        
        lines.append(f"<<<END_TURN:{turn_num:04d}>>>")
        lines.append("=" * 80)
        lines.append("")
        
        return lines
    
    def verify_file_integrity(self) -> bool:
        """
        Verify the integrity of the memory file.
        Checks that all turns in memory are present in the file.
        
        Returns:
            True if file is intact, False otherwise
        """
        if not self.memory_file.exists():
            print(Fore.YELLOW + "Memory file does not exist", Fore.RESET)
            return False
        
        try:
            # Count turns in file
            result = subprocess.run(
                ['grep', '-c', '<<<TURN:', str(self.memory_file)],
                capture_output=True,
                text=True
            )
            file_turn_count = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Count turns in memory
            memory_turn_count = len(self._all_interactions)
            
            if file_turn_count != memory_turn_count:
                print(Fore.RED + f"✗ Integrity check failed: File has {file_turn_count} turns, memory has {memory_turn_count} turns", Fore.RESET)
                return False
            
            # Check for essential markers
            essential_markers = [
                '@@@MEMORY_LOG_START@@@',
                '>>>TURNS_START<<<',
                '>>>TURNS_END<<<',
                '@@@MEMORY_LOG_END@@@'
            ]
            
            for marker in essential_markers:
                result = subprocess.run(
                    ['grep', '-q', marker, str(self.memory_file)],
                    capture_output=True
                )
                if result.returncode != 0:
                    print(Fore.RED + f"✗ Integrity check failed: Missing marker '{marker}'", Fore.RESET)
                    return False
            
            print(Fore.GREEN + f"✓ File integrity verified: {file_turn_count} turns", Fore.RESET)
            return True
            
        except Exception as e:
            print(Fore.RED + f"Error verifying file integrity: {e}", Fore.RESET)
            return False
    
    def diagnose_file(self) -> Dict[str, Any]:
        """
        Diagnose the memory file and return statistics.
        
        Returns:
            Dictionary with file diagnostics
        """
        if not self.memory_file.exists():
            return {
                "exists": False,
                "error": "File does not exist"
            }
        
        try:
            # Get file size
            file_size = os.path.getsize(self.memory_file)
            
            # Count turns
            result = subprocess.run(
                ['grep', '-c', '<<<TURN:', str(self.memory_file)],
                capture_output=True,
                text=True
            )
            turn_count = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Count user messages
            result = subprocess.run(
                ['grep', '-c', '>>>USER:', str(self.memory_file)],
                capture_output=True,
                text=True
            )
            user_msg_count = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Count bot messages
            result = subprocess.run(
                ['grep', '-c', '>>>BOT:', str(self.memory_file)],
                capture_output=True,
                text=True
            )
            bot_msg_count = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Count summaries
            result = subprocess.run(
                ['grep', '-c', '>>>SUMMARY:', str(self.memory_file)],
                capture_output=True,
                text=True
            )
            summary_count = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Check for essential markers
            markers_present = {}
            essential_markers = [
                '@@@MEMORY_LOG_START@@@',
                '@@@MEMORY_LOG_END@@@',
                '>>>TURNS_START<<<',
                '>>>TURNS_END<<<'
            ]
            for marker in essential_markers:
                result = subprocess.run(
                    ['grep', '-q', marker, str(self.memory_file)],
                    capture_output=True
                )
                markers_present[marker] = (result.returncode == 0)
            
            diagnostics = {
                "exists": True,
                "file_size": file_size,
                "turn_count": turn_count,
                "user_msg_count": user_msg_count,
                "bot_msg_count": bot_msg_count,
                "summary_count": summary_count,
                "markers_present": markers_present,
                "memory_turn_count": len(self._all_interactions),
                "integrity_ok": (turn_count == len(self._all_interactions) and 
                                all(markers_present.values()))
            }
            
            return diagnostics
            
        except Exception as e:
            return {
                "exists": True,
                "error": str(e)
            }
    
    def get_search_examples(self) -> str:
        """
        Return examples of bash/grep commands to search the memory text file.
        Optimized for the new anchor-based format.
        """
        examples = f"""
        === GREP/BASH SEARCH EXAMPLES FOR {self.memory_file} ===
        
        # Find all conversation turns (just markers):
        grep '<<<TURN:' {self.memory_file}
        
        # Find specific turn WITH CONTENT (shows 20 lines after):
        grep -A 20 '<<<TURN:0005>>>' {self.memory_file}
        
        # View full conversation for turn 3:
        sed -n '/<<<TURN:0003>>>/,/<<<END_TURN:0003>>>/p' {self.memory_file}
        
        # Find all user messages WITH CONTENT (1 line after):
        grep -A 1 '>>>USER:' {self.memory_file}
        
        # Find all bot responses WITH CONTENT (1 line after):
        grep -A 1 '>>>BOT:' {self.memory_file}
        
        # Find user message from turn 3 WITH CONTENT:
        sed -n '/>>>USER:0003>>>/,/<<<USER:0003<<</p' {self.memory_file}
        
        # Get total number of turns:
        grep '@TOTAL_TURNS:' {self.memory_file}
        
        # Search for keyword with context (5 lines before/after):
        grep -i -C 5 "algebra" {self.memory_file}
        
        # Search for date-specific entries with content:
        grep -A 10 '@DATE:2026-01-28@' {self.memory_file}
        
        # Get conversation summary:
        sed -n '/###SUMMARY_START###/,/###SUMMARY_END###/p' {self.memory_file}
        
        # Count total turns:
        grep -c '<<<TURN:' {self.memory_file}
        
        # Find turns containing specific word with context:
        grep -C 5 "quadratic" {self.memory_file}
        
        # Get all timestamps:
        grep '@TIMESTAMP:' {self.memory_file}
        
        # Find user ID:
        grep '@USER_ID:' {self.memory_file} | head -1
        
        # Extract turn numbers only:
        grep -o '<<<TURN:[0-9]\\{{4}}>>>' {self.memory_file}
        """
        return examples
    
    def _ensure_loaded(self) -> None:
        """Lazily load memory from file on first access (non-blocking init)."""
        if not self._memory_loaded:
            self._memory_loaded = True
            self.load_memory_from_file()

    def load_memory_from_file(self) -> bool:
        """Load interactions from plain text file using subprocess (grep/sed)."""
        try:
            if not self.memory_file.exists():
                print(Fore.YELLOW + f"No existing memory file found for user {self.username} (new user)", Fore.RESET)
                self._all_interactions = []
                self.turn_counter = 0
                self._last_saved_turn = 0
                return False
            
            # Parse header - Extract metadata using grep
            last_updated = "Unknown"
            total_turns = 0
            
            # Extract LAST_UPDATED using grep
            try:
                result = subprocess.run(
                    ['grep', '-oP', r'@LAST_UPDATED:\K[^@]+', str(self.memory_file)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0 and result.stdout.strip():
                    last_updated = result.stdout.strip()
            except Exception as e:
                print(Fore.YELLOW + f"Could not extract LAST_UPDATED: {e}", Fore.RESET)
            
            # Extract TOTAL_TURNS using grep
            try:
                result = subprocess.run(
                    ['grep', '-oP', r'@TOTAL_TURNS:\K[^@]+', str(self.memory_file)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0 and result.stdout.strip():
                    total_turns = int(result.stdout.strip())
            except Exception as e:
                print(Fore.YELLOW + f"Could not extract TOTAL_TURNS: {e}", Fore.RESET)
            
            # Extract summary using sed
            try:
                result = subprocess.run(
                    ['sed', '-n', '/###SUMMARY_START###/,/###SUMMARY_END###/p', str(self.memory_file)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0 and result.stdout.strip():
                    summary_text = result.stdout.strip()
                    # Remove the markers
                    summary_text = summary_text.replace('###SUMMARY_START###', '').replace('###SUMMARY_END###', '').strip()
                    self.summary = summary_text
                else:
                    self.summary = ""
            except Exception as e:
                print(Fore.YELLOW + f"Could not extract summary: {e}", Fore.RESET)
                self.summary = ""
            
            # Get all turn numbers using grep
            try:
                result = subprocess.run(
                    ['grep', '-oP', r'<<<TURN:\K\d{4}', str(self.memory_file)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode != 0 or not result.stdout.strip():
                    # No turns found
                    self._all_interactions = []
                    self.turn_counter = 0
                    return True
                
                turn_numbers = [int(num) for num in result.stdout.strip().split('\n')]
            except Exception as e:
                print(Fore.RED + f"Error extracting turn numbers: {e}", Fore.RESET)
                self._all_interactions = []
                self.turn_counter = 0
                return False
            
            # Parse all turns using sed
            interactions = []
            for turn_num in turn_numbers:
                try:
                    turn_str = f"{turn_num:04d}"
                    
                    # Extract entire turn block using sed
                    result = subprocess.run(
                        ['sed', '-n', f'/<<<TURN:{turn_str}>>>/,/<<<END_TURN:{turn_str}>>>/p', str(self.memory_file)],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if result.returncode != 0 or not result.stdout.strip():
                        continue
                    
                    turn_content = result.stdout
                    
                    # Extract turn details using regex (after sed extraction)
                    turn_id_match = re.search(r'@TURN_ID:([^@]+)@', turn_content)
                    timestamp_match = re.search(r'@TIMESTAMP:([^@]+)@', turn_content)
                    date_match = re.search(r'@DATE:([^@]+)@', turn_content)
                    user_id_match = re.search(r'@USER_ID:([^@]+)@', turn_content)
                    
                    # Extract user message using sed for this specific turn content
                    user_msg_match = re.search(rf'>>>USER:{turn_str}>>>\n(.*?)\n<<<USER:{turn_str}<<<', turn_content, re.DOTALL)
                    user_msg = user_msg_match.group(1).strip() if user_msg_match else ""
                    
                    # Extract bot message
                    bot_msg_match = re.search(rf'>>>BOT:{turn_str}>>>\n(.*?)\n<<<BOT:{turn_str}<<<', turn_content, re.DOTALL)
                    bot_msg = bot_msg_match.group(1).strip() if bot_msg_match else ""
                    
                    # Extract summary if available
                    summary_match = re.search(rf'>>>SUMMARY:{turn_str}>>>\n(.*?)\n<<<SUMMARY:{turn_str}<<<', turn_content, re.DOTALL)
                    turn_summary = summary_match.group(1).strip() if summary_match else ""
                    
                    interaction = {
                        "turn": turn_num,
                        "id": turn_id_match.group(1) if turn_id_match else str(uuid.uuid4()),
                        "timestamp": timestamp_match.group(1) if timestamp_match else "unknown",
                        "date": date_match.group(1) if date_match else "unknown",
                        "user_id": user_id_match.group(1) if user_id_match else self.user_id,
                        "user_message": user_msg,
                        "bot_message": bot_msg,
                        "summary": turn_summary
                    }
                    
                    interactions.append(interaction)
                    
                except Exception as e:
                    print(Fore.YELLOW + f"Warning: Could not parse turn {turn_num}: {e}", Fore.RESET)
                    continue
            
            self._all_interactions = interactions
            self.turn_counter = max([i['turn'] for i in interactions]) if interactions else 0
            self._last_saved_turn = self.turn_counter  # Track what's already saved
            
            print(Fore.GREEN + f"✓ Loaded {len(interactions)} interactions from file (returning user)", Fore.RESET)
            print(Fore.CYAN + f"  Last updated: {last_updated}", Fore.RESET)
            print(Fore.CYAN + f"  Total turns: {self.turn_counter}", Fore.RESET)
            if self.summary:
                print(Fore.CYAN + f"  Summary: {self.summary[:100]}...", Fore.RESET)
            
            return True
            
        except Exception as e:
            print(Fore.RED + f"Error loading memories from file: {e}", Fore.RESET)
            import traceback
            traceback.print_exc()
            self._all_interactions = []
            self.turn_counter = 0
            self._last_saved_turn = 0
            return False


class MemoryOps:
    """
    Enhanced Memory Operations with sophisticated conversation management.
    
    Based on: https://github.com/Zenodia/standalone_agent_memory/blob/main/utils.py
    """
    
    def __init__(
        self,
        username: str,
        llm=None,
        memory_dir: str = None,
        use_streaming: bool = False,
        rate_limit_delay: float = 2.0,  # Delay between LLM calls
        summary_interval: int = 10  # Create summaries every N turns
    ):
        """
        Initialize Text-Based Memory Operations.
        
        Args:
            username: User ID
            llm: Optional LLM instance
            memory_dir: Directory for memory files
            use_streaming: Whether to use streaming
            rate_limit_delay: Seconds to wait between LLM calls (default 2.0)
            summary_interval: Create summaries every N turns (default 10)
        """
        self.username = username
        self.memory_manager = MemoryHandler(username, llm, memory_dir, use_streaming, rate_limit_delay, summary_interval)
        self.chat_history: List[BaseMessage] = []
        self.number_of_turns = 3
        
        # Load summary from memory manager
        self.summary = self.memory_manager.summary
        
        # Initialize LLM (reuse from memory_manager)
        self.llm = self.memory_manager.llm
        
        print(Fore.GREEN + f"✓ Text-Based Memory Operations initialized for user: {username}", Fore.RESET)
        print(Fore.CYAN + f"  Rate limit delay: {rate_limit_delay}s between LLM calls", Fore.RESET)
        print(Fore.CYAN + f"  Summary interval: Every {summary_interval} turns", Fore.RESET)
    
    def check_turns(self) -> int:
        """Count user message turns in chat history."""
        return sum(1 for msg in self.chat_history if isinstance(msg, HumanMessage))
    
    def conv_items_to_list_of_strs(self, chat_history: List[BaseMessage]) -> List[str]:
        """Convert message objects to string list."""
        ls = []
        for item in chat_history:
            if isinstance(item, HumanMessage):
                ls.append("Human:" + item.content)
            elif isinstance(item, AIMessage):
                ls.append("AI:" + item.content)
            elif isinstance(item, SystemMessage):
                ls.append("System:" + item.content)
        return ls
    
    async def summarize_history(self) -> str:
        """
        Progressively summarize conversation history using LangChain LLM with streaming support.
        
        Based on: https://github.com/Zenodia/standalone_agent_memory/blob/main/utils.py
        Uses astream for streaming-compatible execution.
        """
        if not self.chat_history:
            return ""
        
        conv_summary_prompt = """You are Orin, an AI tutor, creating a memory summary from your current tutoring session. Write in FIRST PERSON ("I worked with...", "My student showed...").

Keep your summary to 2-3 sentences maximum.

Here is your past memory if you'd like to incorporate any aspects of it into your response.
Do not summarize this or include it in your response – this is just background information:

— BEGIN BACKGROUND INFORMATION —
{summary}
— END BACKGROUND INFORMATION —

This is the new content from this tutoring session that you must summarize:
{conversations}

For your summary focus on things like:
- what happened today? did you talk to anyone? did you prep anything?
- who was involved in the day? did anything noticeable happen?
- what progress was made toward goals?
- what did you notice from the session?
- what information should be remembered for the rest of the week? month? year?

CRITICAL: Only use information explicitly stated in the conversation. Do NOT add details or infer anything.

Your summary:
"""
        
        # Convert chat history to string
        chat_history_ls = self.conv_items_to_list_of_strs(self.chat_history)
        conversations_str = "\n".join(chat_history_ls)
        
        # Format prompt
        conv_summary_prompt_template = PromptTemplate(
            template=conv_summary_prompt,
            input_variables=["summary", "conversations"]
        )
        
        # Use LangChain directly (compatible with ChatOpenAI)
        summary_chain = (conv_summary_prompt_template | self.llm | StrOutputParser())
        
        try:
            # Rate limiting: wait if needed
            await self.memory_manager._rate_limit_wait()
            
            # Use astream for streaming-compatible execution
            output = ""
            async for chunk in summary_chain.astream({"summary": self.summary, "conversations": conversations_str}):
                if chunk:
                    output += str(chunk)
            
            # Update last call time on success
            self.memory_manager.last_llm_call_time = time.time()
            
            # StrOutputParser already returns a string
            if not isinstance(output, str):
                output = str(output)
            
            self.summary = output
            self.memory_manager.summary = output
            print(Fore.CYAN + f"✓ Conversation summarized ({len(self.chat_history)} messages)", Fore.RESET)
            
            # Save summary to file
            self.memory_manager.save_memory_to_file()
            
            # Reset chat history
            self.chat_history = []
            
            return output
        except Exception as e:
            print(Fore.RED + f"Error summarizing conversation: {e}", Fore.RESET)
            import traceback
            traceback.print_exc()
            return self.summary
    
    async def process_message(
        self,
        message: str,
        bot_response: str,
        context: Optional[Dict[str, Any]] = None,
        create_summary: bool = True,
        background_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Process a message exchange and save to text file.
        Summaries are only created every N turns (configured by summary_interval).
        
        Args:
            message: User message
            bot_response: Assistant response
            context: Optional context information
            create_summary: Whether to create an LLM summary (default True)
            background_summary: Whether to create summary in background (default True)
            
        Returns:
            Dictionary with memory operation results
        """
        # Add to chat history
        self.chat_history.append(HumanMessage(content=message))
        self.chat_history.append(AIMessage(content=bot_response))
        
        # Increment turn counter
        self.memory_manager.turn_counter += 1
        current_turn = self.memory_manager.turn_counter
        
        # Add interaction to memory immediately (without summary - non-blocking!)
        interaction = self.memory_manager.add_interaction(
            user_msg=message,
            bot_msg=bot_response,
            turn_number=current_turn,
            summary=""  # Will be updated by background task if this is a summary turn
        )
        
        # Create interaction summary ONLY every N turns (configured interval)
        interaction_summary = ""
        should_create_summary = create_summary and (current_turn % self.memory_manager.summary_interval == 0)
        
        if should_create_summary:
            # Get the last N turns since the last summary
            start_turn = max(1, current_turn - self.memory_manager.summary_interval + 1)
            recent_interactions = [
                inter for inter in self.memory_manager._all_interactions 
                if start_turn <= inter['turn'] <= current_turn
            ]
            
            # Build content from multiple turns
            interaction_content_parts = []
            for inter in recent_interactions:
                interaction_content_parts.append(f"Turn {inter['turn']}:")
                interaction_content_parts.append(f"User: {inter['user_message']}")
                interaction_content_parts.append(f"Assistant: {inter['bot_message']}")
                interaction_content_parts.append("")
            
            interaction_content = "\n".join(interaction_content_parts)
            
            if background_summary:
                # Launch background task to create summary (NON-BLOCKING!)
                task = asyncio.create_task(
                    self.memory_manager._background_summarize_and_update(
                        turn_number=current_turn,
                        content=interaction_content,
                        period_type=PeriodType.DIRECT,
                        existing_memory=self.memory_manager.summary
                    )
                )
                self.memory_manager.background_tasks.append(task)
                print(Fore.LIGHTCYAN_EX + f"🔄 Summary for turns {start_turn}-{current_turn} running in background...", Fore.RESET)
                interaction_summary = f"[Summary pending for turns {start_turn}-{current_turn}]"
            else:
                # Blocking mode (original behavior)
                interaction_summary = await self.memory_manager.create_memory_summary(
                    content=interaction_content,
                    period_type=PeriodType.DIRECT,
                    existing_memory=self.memory_manager.summary
                )
                # Update interaction with summary
                self.memory_manager.update_interaction_summary(current_turn, interaction_summary)
        else:
            # Not a summary turn
            next_summary_turn = ((current_turn // self.memory_manager.summary_interval) + 1) * self.memory_manager.summary_interval
            interaction_summary = f"[No summary - next summary at turn {next_summary_turn}]"
        
        # Cleanup completed background tasks
        self.memory_manager.cleanup_background_tasks()
        
        # Check if we need to summarize (uses LangChain LLM internally)
        turns = self.check_turns()
        if turns > self.number_of_turns:
            await self.summarize_history()
        
        return {
            "turn": current_turn,
            "interaction": interaction,
            "summary": interaction_summary,
            "total_turns": turns,
            "overall_summary": self.summary,
            "background_tasks": len(self.memory_manager.background_tasks),
            "is_summary_turn": should_create_summary
        }
    
    def get_memory_context(self, query: str) -> str:
        """Get formatted memory context using text search."""
        self.memory_manager._ensure_loaded()
        # Simple keyword search in memory file
        keywords = query.lower().split()
        matches = []

        for interaction in self.memory_manager._all_interactions:
            # Check if any keywords appear in user or bot messages
            text = f"{interaction['user_message']} {interaction['bot_message']} {interaction['summary']}".lower()
            if any(keyword in text for keyword in keywords):
                matches.append(interaction)
        
        if not matches:
            return ""
        
        context_parts = ["**Relevant Past Conversations:**"]
        for i, interaction in enumerate(matches[:5], 1):  # Top 5
            turn = interaction['turn']
            summary = interaction.get('summary', interaction['user_message'][:80])
            context_parts.append(f"{i}. Turn {turn}: {summary}")
        
        return "\n".join(context_parts)
    
    def get_history_summary(self) -> str:
        """Get formatted conversation summary."""
        self.memory_manager._ensure_loaded()
        if self.summary:
            return f"**Conversation Summary:** {self.summary}"
        return ""
    
    def search_memory_text(self, pattern: str, case_sensitive: bool = False) -> List[str]:
        """
        Search memory file using regex pattern (like grep).
        
        Args:
            pattern: Regex pattern to search for
            case_sensitive: Whether search is case sensitive
            
        Returns:
            List of matching lines
        """
        return self.memory_manager.search_text_file(pattern, case_sensitive)
    
    async def wait_for_summaries(self, timeout: float = None):
        """
        Wait for all background summary tasks to complete.
        
        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)
        """
        await self.memory_manager.wait_for_background_tasks(timeout)
    
    def get_pending_summaries_count(self) -> int:
        """
        Get the number of background summary tasks still running.
        
        Returns:
            Number of pending background tasks
        """
        self.memory_manager.cleanup_background_tasks()
        return len(self.memory_manager.background_tasks)


# Singleton instance cache
_memory_ops_cache: Dict[str, MemoryOps] = {}


def get_memory_ops(
    username: str,
    llm=None,
    memory_dir: str = None,
    use_streaming: bool = False,
    rate_limit_delay: float = 2.0,
    summary_interval: int = 10
) -> MemoryOps:
    """
    Get or create a text-based MemoryOps instance for a user.
    
    Args:
        username: User ID
        llm: Optional ChatNVIDIA instance
        memory_dir: Directory for memory files
        use_streaming: Whether to use streaming
        rate_limit_delay: Seconds to wait between LLM calls (default 2.0)
        summary_interval: Create summaries every N turns (default 10)
    """
    cache_key = f"{username}_{use_streaming}_{rate_limit_delay}_{summary_interval}"
    if cache_key not in _memory_ops_cache:
        _memory_ops_cache[cache_key] = MemoryOps(username, llm, memory_dir, use_streaming, rate_limit_delay, summary_interval)
    return _memory_ops_cache[cache_key]


def clear_user_memory(username: str) -> bool:
    """Clear all memories for a user."""
    try:
        # Remove from cache
        keys_to_remove = [k for k in _memory_ops_cache.keys() if k.startswith(username)]
        for key in keys_to_remove:
            del _memory_ops_cache[key]
        
        # Delete memory file
        try:
            docker_compose_path = Path("/workspace/docker-compose.yml")
            if docker_compose_path.exists():
                with open(docker_compose_path, "r") as f:
                    yaml_data = yaml.safe_load(f)
                    mnt_folder = yaml_data["services"]["agenticta"]["volumes"][-1].split(":")[-1]
                    memory_dir = Path(mnt_folder) / username / "memory"
            else:
                memory_dir = Path("mnt") / username / "memory"
        except:
            memory_dir = Path("mnt") / username / "memory"
        
        memory_file = memory_dir / f"{username}_conversation_memory.txt"
        if memory_file.exists():
            memory_file.unlink()
            print(Fore.GREEN + f"✓ Cleared memory for user: {username}", Fore.RESET)
        
        return True
    except Exception as e:
        print(Fore.RED + f"Error clearing memory: {e}", Fore.RESET)
        return False
