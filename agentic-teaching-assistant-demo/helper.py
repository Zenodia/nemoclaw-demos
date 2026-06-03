from study_buddy_client import study_buddy_client_requests
from agent_mem_client import agentic_mem_mcp_client
#from quiz_gen_client import quiz_generation_client
#from chapter_gen import process_parallel_titles
from extract_sub_chapters import parallel_extract_pdf_page_and_text, post_process_extract_sub_chapters
from threading import Thread
import os
import typing
import asyncio
import inspect
import time
from colorama import Fore
import colorama
import sys
import threading
import datetime
import subprocess

# Initialize colorama early so ANSI color codes are handled on Windows consoles
colorama.init(autoreset=True)

# Save the original stdout/stderr streams at import time. Using these as the
# tee targets avoids nested thread-altered sys.stdout values and preserves
# console color handling provided by colorama.
ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr

# Force all per-task logs into a single directory and ensure it exists.
# This prevents malformed filenames when callers use keys that include
# path-like content (e.g. "quiz_/workspace/mnt/pdfs/SwedenFacts").
LOG_DIR = "/workspace/mnt/logs"
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    # best-effort, if we can't create the directory, fall back to CWD
    LOG_DIR = "."


def run_python_script(script_path: str, *script_args) -> int:
    """Run an external Python script using the same Python interpreter.

    This function does NOT capture output; subprocess will inherit the current
    stdout/stderr so output streams live into the per-task log when called from
    inside the worker thread where sys.stdout has been redirected.

    Returns the process return code.
    """
    cmd = [sys.executable, script_path, *map(str, script_args)]
    proc = subprocess.run(cmd)
    return proc.returncode


def run_together(tasks: typing.Dict[typing.Hashable, tuple],
                 except_errors: tuple = None) -> dict:
    """
    Run multiple callables in separate threads and collect results.

    :param tasks: a dict of task keys matched to a tuple of callable and its arguments
        e.g. tasks = {'task1': (add, 1, 2), 'task2': (add, 3, 4)}
    :param except_errors: a tuple of errors that should be caught. Defaults to (Exception,)
    :return: a dictionary of results with the same keys as `tasks` parameter
        e.g. results = {'task1': 3, 'task2': 7}
    """
    # catch all exceptions by default
    if not except_errors:
        except_errors = (Exception,)
    threads = []
    results = dict()
    log_lock = threading.Lock()
    #log_path = "log.txt"
    # open file once for append and share the handle
    #log_file = open(log_path, "a", encoding="utf-8")

    class StreamToLog:
        """A file-like object that writes with a prefix and flushes immediately.

        Multiple threads share the same file handle; writes are guarded by log_lock.
        """

        def __init__(self, file_handle, lock, prefix: str):
            self.file_handle = file_handle
            self.lock = lock
            self.prefix = prefix
            # optional stream to also write to (e.g. the original stdout/stderr)
            self.tee_stream = None

        def write(self, msg):
            # Avoid writing empty strings
            if not msg:
                return
            # Normalize newlines: write each line with prefix
            lines = msg.splitlines(keepends=True)
            # First, optionally write the raw message to the tee stream so console
            # output (including color codes) still appears.
            try:
                if self.tee_stream is not None:
                    try:
                        self.tee_stream.write(msg)
                    except Exception:
                        # ignore errors writing to tee
                        pass
            except Exception:
                pass

            # Now write prefixed lines into the task log file under lock
            with self.lock:
                for line in lines:
                    timestamp = datetime.datetime.now().isoformat()
                    try:
                        self.file_handle.write(f"{timestamp} {self.prefix}{line}")
                    except Exception:
                        # best-effort: ignore logging errors
                        pass
                try:
                    self.file_handle.flush()
                except Exception:
                    pass

        def flush(self):
            try:
                with self.lock:
                    self.file_handle.flush()
            except Exception:
                pass

    def save_results(task_spec, key):
        def wrapped(*args, **kwargs):
            # open a per-task log file inside LOG_DIR and sanitize the key so
            # keys that contain path separators don't create nested paths.
            safe_key = str(key).replace(os.sep, "_").replace("/", "_").lstrip("_")
            if not safe_key:
                safe_key = "task"
            task_log_path = os.path.join(LOG_DIR, f"{safe_key}_log.txt")
            try:
                task_log_file = open(task_log_path, "a", encoding="utf-8")
            except FileNotFoundError:
                # try to create the directory and reopen
                try:
                    os.makedirs(LOG_DIR, exist_ok=True)
                except Exception:
                    # fallback to current directory
                    task_log_path = f"{safe_key}_log.txt"
                task_log_file = open(task_log_path, "a", encoding="utf-8")
            # prepare prefixed stream objects for stdout/stderr pointing to task-specific file
            stdout_stream = StreamToLog(task_log_file, log_lock, f"[{key}] ")
            stderr_stream = StreamToLog(task_log_file, log_lock, f"[{key}][ERR] ")
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            try:
                # set up tee streams so the original console stream still receives output
                stdout_stream.tee_stream = ORIGINAL_STDOUT
                stderr_stream.tee_stream = ORIGINAL_STDERR
                sys.stdout = stdout_stream
                sys.stderr = stderr_stream

                def run_one(func, *f_args):
                    try:
                        # If func is a special marker string 'run_script', support calling external scripts
                        if not callable(func):
                            # If func is not callable, attempt no-op or error
                            raise TypeError(f"Step first element is not callable: {func}")

                        # If func is an async function, run it inside a worker thread so the
                        # coroutine is created and awaited in the same thread/event loop.
                        if inspect.iscoroutinefunction(func):
                            # Special-case the quiz generation task to poll every 5 seconds
                            # while it runs.
                            if key == 'quiz_gen':
                                result_holder = {"done": False, "result": None, "error": None}

                                def _worker_call():
                                    try:
                                        r = asyncio.run(func(*f_args))
                                        result_holder["result"] = r
                                    except Exception as e:
                                        result_holder["error"] = e
                                    finally:
                                        result_holder["done"] = True

                                # log start
                                try:
                                    stderr_stream.write("quiz_gen task started\n")
                                except Exception:
                                    pass

                                worker_thread = threading.Thread(target=_worker_call)
                                worker_thread.start()

                                # poll every 10 seconds until finished (silent)
                                while not result_holder["done"]:
                                    time.sleep(10)

                                # join to clean up thread resources
                                try:
                                    worker_thread.join(timeout=0)
                                except Exception:
                                    pass

                                # log finish or error
                                try:
                                    if result_holder.get("error") is not None:
                                        stderr_stream.write(f"quiz_gen task finished with error: {result_holder.get('error')}\n")
                                    else:
                                        stderr_stream.write("quiz_gen task finished successfully\n")
                                except Exception:
                                    pass

                                if result_holder.get("error") is not None:
                                    # Propagate the error to results as an exception object
                                    return result_holder.get("error")
                                return result_holder.get("result")
                            else:
                                # run other async functions synchronously in this worker
                                return asyncio.run(func(*f_args))

                        # synchronous callable: call directly
                        return func(*f_args)
                    except except_errors as e:
                        stderr_stream.write(f"Exception: {e}\n")
                        return e
                    except Exception as e:
                        stderr_stream.write(f"Unhandled exception: {e}\n")
                        return e

                # determine if task_spec is a sequence of steps or a single step
                if isinstance(task_spec, list) or isinstance(task_spec, tuple) and len(task_spec) > 0 and callable(task_spec[0]):
                    # single tuple step: (func, *args)
                    if callable(task_spec[0]):
                        func = task_spec[0]
                        step_args = task_spec[1:]
                        result = run_one(func, *step_args)
                    else:
                        # list of steps
                        step_results = []
                        for step in task_spec:
                            if not step:
                                continue
                            func = step[0]
                            step_args = step[1:] if len(step) > 1 else []
                            step_results.append(run_one(func, *step_args))
                        result = step_results
                else:
                    # unexpected format; try to call directly
                    try:
                        result = task_spec()
                    except Exception as e:
                        stderr_stream.write(f"Task spec not callable: {e}\n")
                        result = e

                results[key] = result
            finally:
                # restore stdout/stderr
                try:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
                except Exception:
                    pass
                try:
                    task_log_file.flush()
                    task_log_file.close()
                except Exception:
                    pass

        return wrapped

    # tasks values may be either:
    # - a tuple like (func, *args)
    # - or a list of tuples [(func1, *args1), (func2, *args2), ...]
    for key, task_spec in tasks.items():
        # save_results will handle single tuple or list of tuples
        thread = Thread(
            target=save_results(task_spec, key),
        )
        thread.start()
        threads.append(thread)

    for t in threads:
        t.join()

    return results


if __name__ == "__main__":
    # Prepare tasks that can run in parallel immediately. We intentionally do NOT
    # start `chapter_gen` here because it must wait for `quiz_gen` to finish and
    # provide its output.
    save_logs = True  # set to False to disable log saving
    pdf_files=os.listdir(uploaded_pdf_loc)
    pdf_files=[f for f in pdf_files if f.endswith('.pdf')]
    """
    tasks={}
    if len(pdf_files) >1:
        for pdf_file in pdf_files:
            pdf_file_name=pdf_file.split(".pdf")[0]
            save_to_pdf=os.makedirs(os.path.join(save_to, pdf_file_name),exist_ok=True)
            tasks[f"quiz_{pdf_file_name}"]=(quiz_generation_client, uploaded_pdf_loc, save_to_pdf)

    save_logs = True   
    ## adding study_buddy client as task 
    tasks["study_buddy"]= (study_buddy_client_requests,"someone who has a good sense of humor, and can make funny joke out of the boring subject I'd studying")
    tasks["agentic_mem"]=( agentic_mem_mcp_client,
            "babe",
            "someone who has a good sense of humor, and can make funny joke out of the boring subject I'd studying",
        )

    # Run parallel tasks and wait for completion. quiz_gen result will be used
    # to invoke chapter generation afterwards.
    results = run_together(tasks)

    # print parallel task results/logs
    i=0
    for key, result in results.items():
        print(f"------------------------------ processing {str(i)} ------------------------------")
        print(Fore.LIGHTBLUE_EX + f"Result from {key}:\n{result}\n\n")
        i+=1

    # Extract quiz_gen output and try to parse it into summaries and chapter numbers.
    quiz_output = results.get("quiz_gen")
    """
    #print(Fore.MAGENTA + f"\n\n\n ################ Quiz generation output ################\n{quiz_output}\n" + Fore.RESET)
    # Helper: attempt to extract summaries and chapter numbers from quiz output.
    def extract_summaries_and_chapters(quiz_res):
        """Try a few reasonable formats for quiz_res and return (summaries, chapter_nrs).

        Supported heuristics:
        - If quiz_res is a list/tuple of (summary, chapter_nr) pairs, use directly.
        - If quiz_res is a string containing JSON with keys 'summaries' and 'chapter_nrs', parse it.
        - Fallback: use module-level `summaries` and `chapters` variables defined in chapter_gen.py (if imported names exist).
        """
        # case: already a list of tuples
        try:
            if isinstance(quiz_res, (list, tuple)) and len(quiz_res) > 0 and isinstance(quiz_res[0], (list, tuple)):
                s = [item[0] for item in quiz_res]
                c = [item[1] for item in quiz_res]
                return s, c
        except Exception:
            pass

        # case: JSON string
        import json

        try:
            if isinstance(quiz_res, str):
                text = quiz_res.strip()
                # try to load JSON directly
                try:
                    parsed = json.loads(text)
                    # common shapes
                    if isinstance(parsed, dict):
                        if "summaries" in parsed and "chapter_nrs" in parsed:
                            return parsed["summaries"], parsed["chapter_nrs"]
                        # maybe list of pairs
                        if all(isinstance(x, (list, tuple)) and len(x) >= 2 for x in parsed.get("items", [])):
                            pairs = parsed.get("items")
                            s = [p[0] for p in pairs]
                            c = [p[1] for p in pairs]
                            return s, c
                except json.JSONDecodeError:
                    # try to split by double-newlines into summaries
                    parts = [p.strip() for p in text.split('\n\n') if p.strip()]
                    if parts:
                        # assign chapter numbers starting at 1
                        return parts, list(range(1, len(parts) + 1))
        except Exception:
            pass

        # fallback: try to use pre-defined names if available
        try:
            from chapter_gen import summaries as _default_summaries, chapters as _default_chapters
            return _default_summaries, _default_chapters
        except Exception:
            # as a last resort return empty lists
            return [], []

    """
    summaries_for_chapter, chapters_for_chapter = extract_summaries_and_chapters(quiz_output)

    # Only run chapter generation if we have summaries to process
    if summaries_for_chapter and chapters_for_chapter:
        print(Fore.GREEN + f"\n ================== Running chapter generation for {len(summaries_for_chapter)} summaries...==============" + Fore.RESET)
        chapter_results = process_parallel_titles(summaries_for_chapter, chapters_for_chapter)
        print(Fore.GREEN + "=====> \nChapter generation results:\n", chapter_results, Fore.RESET)
    else:
        print(Fore.YELLOW + "\n ==================No summaries available from quiz_gen; skipping chapter generation. ==================" + Fore.RESET)
    
    if not save_logs :
        # clear up the logs each time if not needing to save it 
        for key in tasks.keys():
            log_path = f"{key}_log.txt"
            try:
                os.remove(log_path)
                
            except Exception as e:
                print("error occured while deleting log file:", e)
                pass
    """